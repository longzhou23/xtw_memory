#!/usr/bin/env python3
"""Run 150-message regression replay using 5K scaled models."""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
XTW_PLAYGROUND = PROJECT_ROOT / "xtw-playground"
if str(XTW_PLAYGROUND) not in sys.path:
    sys.path.insert(0, str(XTW_PLAYGROUND))

from memory.scripts.two_stage.common import RAW_WINDOW_150_PATH
from memory.scripts.gpu_gate import GpuLock
from memory.scripts.two_stage.run_refined_replay import RefinedTwoStageRouter

import torch
import laya
from xtw_core.episode_router.p0 import (
    EpisodeRouterConfig,
    EpisodeStore,
    EpisodeEvent,
    ConversationContextBuffer,
    SimpleEpisodeSummarizer,
)

OUT_BASE = PROJECT_ROOT / "memory/benchmark-results/router-v0.2-dual-model-5k-scaling-v0.1"
REPLAY_OUT = OUT_BASE / "replay-150"
REPLAY_OUT.mkdir(parents=True, exist_ok=True)

BOUNDARY_CKPT = OUT_BASE / "training/boundary/checkpoint"
RANKING_CKPT = OUT_BASE / "training/ranking/checkpoint"


def main():
    print("=== Running 150-Message Regression Replay with 5K Models ===")
    print(f"Boundary 5K: {BOUNDARY_CKPT}")
    print(f"Ranking 5K:  {RANKING_CKPT}")

    events_raw = []
    with open(RAW_WINDOW_150_PATH) as f:
        for line in f:
            events_raw.append(json.loads(line))

    assert len(events_raw) == 150

    with GpuLock(job_name="replay_5k_150"):
        print("[GPU] Acquired exclusive GPU lock for 150 replay.")
        agent_a = laya.load(str(BOUNDARY_CKPT), device="cuda")
        agent_b = laya.load(str(RANKING_CKPT), device="cuda")

        config = EpisodeRouterConfig()
        store = EpisodeStore(config)
        context_buffer = ConversationContextBuffer()
        summarizer = SimpleEpisodeSummarizer()

        router = RefinedTwoStageRouter(
            store=store,
            judge_a_model=agent_a.model,
            judge_a_tok=agent_a.tok,
            judge_b_model=agent_b.model,
            judge_b_tok=agent_b.tok,
            config=config,
            boundary_threshold=0.50,
            device="cuda",
        )

        records = []
        t0 = time.time()
        for row in events_raw:
            timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            event = EpisodeEvent(
                row["eventId"],
                timestamp,
                row.get("senderId"),
                row.get("senderName"),
                row["text"],
                row.get("replyTo"),
                tuple(row.get("mentions", [])),
            )

            store.close_expired(event.timestamp)
            local_context = context_buffer.recent(config.local_context_events)
            reply_target = context_buffer.find(event.reply_to) if event.reply_to else None
            result = router.route(event, local_context=local_context, reply_target=reply_target)

            if result.decision == "NEW":
                episode = store.create_episode(event)
            else:
                episode = store.append_event(result.episode_id or "", event)

            if len(episode.event_ids) % store.lifecycle.summary_update_every_n_events == 0:
                episode.summary = summarizer.summarize(episode)

            context_buffer.append(event)

            records.append({
                "rawIndex": row["rawIndex"],
                "eventId": row["eventId"],
                "text": row["text"],
                "replyTo": row.get("replyTo"),
                "senderName": row.get("senderName"),
                "timestamp": row["timestamp"],
                "decision": result.decision,
                "episodeId": episode.id,
                "decisionBasis": result.decision_basis,
                "bestScore": result.best_score,
                "candidateScores": result.candidate_scores,
                "reason": result.reason,
                "episodeSummary": episode.summary,
            })

        elapsed = time.time() - t0
        episodes = list(store.episodes.values())
        ep_count = len(episodes)
        new_count = sum(1 for r in records if r["decision"] == "NEW")
        cont_count = sum(1 for r in records if r["decision"] == "CONTINUE")
        mean_len = sum(len(e.event_ids) for e in episodes) / len(episodes) if episodes else 0.0

        print(f"\n150 Regression Replay with 5K Models Completed in {elapsed:.2f}s ({elapsed/150*1000:.2f} ms/event).")
        print(f"  Episodes Formed: {ep_count}")
        print(f"  NEW:  {new_count}")
        print(f"  CONT: {cont_count}")
        print(f"  Mean Episode Length: {mean_len:.2f}")

        # Audit explicit replies
        rec_map = {r["eventId"]: r for r in records}
        replies = [r for r in records if r.get("replyTo") and r.get("replyTo") in rec_map]
        joined_replies = 0
        failed_replies = []
        for r in replies:
            t = rec_map[r["replyTo"]]
            if r["episodeId"] == t["episodeId"]:
                joined_replies += 1
            else:
                failed_replies.append({
                    "rawIndex": r["rawIndex"],
                    "text": r["text"],
                    "targetRawIndex": t["rawIndex"],
                    "targetText": t["text"],
                    "targetEpisode": t["episodeId"],
                    "replyEpisode": r["episodeId"],
                    "decision": r["decision"],
                })

        print(f"  Explicit Replies Joined: {joined_replies}/{len(replies)} ({joined_replies/len(replies)*100:.1f}%)")
        print(f"  Failed Replies: {len(failed_replies)}")
        for fr in failed_replies:
            print("    Failure:", fr)

        # Check hard case 10087
        rec_10087 = next((r for r in records if r["rawIndex"] == 10087), None)
        rec_10057 = next((r for r in records if r["rawIndex"] == 10057), None)
        long_gap_10087_joined = (rec_10087 and rec_10057 and rec_10087["episodeId"] == rec_10057["episodeId"])
        print(f"  Long-gap Hard Case 10087 Rejoined: {long_gap_10087_joined} (ep: {rec_10087['episodeId'] if rec_10087 else None})")

        # Check known mixing pair 10047 vs 10049
        rec_10047 = next((r for r in records if r["rawIndex"] == 10047), None)
        rec_10049 = next((r for r in records if r["rawIndex"] == 10049), None)
        mixing_pair_same = (rec_10047 and rec_10049 and rec_10047["episodeId"] == rec_10049["episodeId"])
        print(f"  Food (10047) vs Privazer (10049) in same Episode: {mixing_pair_same} (ep: {rec_10047['episodeId'] if rec_10047 else None})")

        result_payload = {
            "experiment": "router_v0_2_dual_model_5k_scaling_v0_1",
            "type": "150_message_regression_replay",
            "status": "REGRESSION_EVALUATED_NOT_FRESH",
            "boundary_model": "Judge A 5K (epoch-2)",
            "ranking_model": "Judge B 5K (epoch-1)",
            "boundary_threshold": 0.50,
            "total_messages": 150,
            "episodes_count": ep_count,
            "new_count": new_count,
            "continue_count": cont_count,
            "mean_episode_length": mean_len,
            "explicit_replies": {
                "total": len(replies),
                "joined": joined_replies,
                "accuracy": joined_replies / len(replies) if replies else 0.0,
                "failures": failed_replies,
            },
            "long_gap_10087_rejoined": long_gap_10087_joined,
            "mixing_pair_10047_10049_same": mixing_pair_same,
            "records": records,
        }

        with open(REPLAY_OUT / "results.json", "w", encoding="utf-8") as f:
            json.dump(result_payload, f, indent=2, ensure_ascii=False)

        print(f"Results saved to {REPLAY_OUT / 'results.json'}")


if __name__ == "__main__":
    main()
