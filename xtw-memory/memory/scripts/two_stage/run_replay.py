#!/usr/bin/env python3
"""Execute 150-message continuous system replay for Router v0.2 Two-Stage vs Baselines.

Spec requirements:
  - 150-message replay on raw-window.jsonl (SHA-256 bce62c19d65d931cb047f8db92b9be60c9d833e6a4529ef270a1cc40d8ec1075)
  - message identity identical, order identical, runtime identical
  - candidate builder identical, memory system identical
  - Compare:
      1. Bare Laya (historical a01)
      2. Laya 20K one-stage (historical l02)
      3. HNR one-stage (81f048e6...)
      4. Two-Stage Router v0.2 (Judge A + Judge B)
      5. Qwen q02 reference (historical q02)
"""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

# Add project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Add xtw-playground for xtw_core
XTW_PLAYGROUND = PROJECT_ROOT / "xtw-playground"
if str(XTW_PLAYGROUND) not in sys.path:
    sys.path.insert(0, str(XTW_PLAYGROUND))

from memory.scripts.two_stage.common import (
    RESULTS_DIR,
    RAW_WINDOW_150_PATH,
    BASE_CHECKPOINT_DIR,
)
from memory.scripts.gpu_gate import GpuLock

import torch
import laya
from laya.common import build_sequence, collate_items, QTYPES
from xtw_core.episode_router.p0 import (
    EpisodeRouterConfig,
    EpisodeStore,
    EpisodeEvent,
    EpisodeRuntime,
    RoutingResult,
    build_candidates,
    is_low_information_event,
)


class TwoStageRouter:
    """Router v0.2 Two-Stage Decision Architecture."""

    def __init__(
        self,
        store: EpisodeStore,
        judge_a_model,
        judge_a_tok,
        judge_b_model,
        judge_b_tok,
        config: Optional[EpisodeRouterConfig] = None,
        boundary_threshold: float = 0.50,
        device: str = "cuda",
    ):
        self.store = store
        self.config = config or store.config
        self.judge_a_model = judge_a_model
        self.judge_a_tok = judge_a_tok
        self.judge_b_model = judge_b_model
        self.judge_b_tok = judge_b_tok
        self.boundary_threshold = boundary_threshold
        self.device = device

    def route(
        self,
        event: EpisodeEvent,
        *,
        local_context: Sequence[EpisodeEvent] = (),
        reply_target: Optional[EpisodeEvent] = None,
    ) -> RoutingResult:
        # 1. Low-information filter (frozen invariant)
        if (
            is_low_information_event(event)
            and not event.reply_to
            and not any(item.text.strip() and not is_low_information_event(item) for item in local_context)
        ):
            return RoutingResult("NEW", None, 0.0, {}, reason="INSUFFICIENT_CONTEXT")

        # 2. Build candidates
        candidates = build_candidates(event, self.store, self.config)
        if not candidates:
            return RoutingResult("NEW", None, 0.0, {}, reason="NO_CANDIDATES")

        # 3. Stage 1: Judge A (Boundary Decision: NEW vs CONTINUE)
        p_cont, p_new = self._evaluate_judge_a(event, candidates, local_context)

        # Decision threshold on NEW
        if p_new >= self.boundary_threshold:
            return RoutingResult(
                "NEW",
                None,
                p_new,
                {"NEW": p_new, "CONTINUE": p_cont},
                reason="BOUNDARY_NEW",
                best_score=p_new,
                decision_basis="NEW",
            )

        # 4. Stage 2: Judge B (Ranking Candidate Episodes)
        cand_scores = self._evaluate_judge_b(event, candidates, local_context)
        if not cand_scores:
            return RoutingResult("NEW", None, 0.0, {}, reason="JUDGE_B_EMPTY")

        ranked = sorted(cand_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
        best_id, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) >= 2 else None
        margin = best_score - second_score if second_score is not None else None

        return RoutingResult(
            "CONTINUE",
            best_id,
            best_score,
            cand_scores,
            reason="RANKING_SELECTED",
            best_score=best_score,
            second_best_score=second_score,
            margin=margin,
            decision_basis="HIGH_THRESHOLD",
        )

    def _evaluate_judge_a(self, event, candidates, local_context) -> tuple[float, float]:
        ctx_lines = [
            f"{m.sender_name or m.sender_id or '用户'}: {m.text}"
            for m in local_context[-8:]
        ]
        reply_str = f" (回复: {event.reply_to})" if event.reply_to else ""
        target_str = f"{event.sender_name or event.sender_id or '用户'}: {event.text}{reply_str}"

        cand_lines = []
        for i, c in enumerate(candidates[:8]):
            snip = " ; ".join(m.text[:28] for m in c.recent_events[-2:]) if c.recent_events else c.summary[:28]
            cand_lines.append(f"- 话题 {i+1}: {snip}")
        cand_section = f"\n[活跃候选话题]\n" + "\n".join(cand_lines)

        state = f"[近期上下文]\n" + "\n".join(ctx_lines) + cand_section + f"\n[当前消息] {target_str}"

        q = {
            "t": "choice",
            "ins": "判断当前目标消息是开启独立新话题还是延续已有话题？",
            "crit": {
                "CONTINUE": "延续话题: 属于候选话题之一或群聊历史讨论",
                "NEW": "新话题: 开启完全独立的新讨论线程"
            }
        }

        # Deterministic option order
        seed = int(hashlib.md5(event.id.encode()).hexdigest()[:8], 16)
        keys = ["CONTINUE", "NEW"]
        order = [1, 0] if seed % 2 == 1 else [0, 1]
        ordered_keys = [keys[i] for i in order]

        ids, markers = build_sequence(
            self.judge_a_tok,
            state,
            q,
            max_len=1024,
            head_max_len=256,
            option_order=order,
            truncate_left=True,
        )

        item = {
            "ids": ids,
            "markers": markers,
            "qtype": QTYPES["choice"],
            "target": [0.0, 0.0],
            "label": 0,
        }

        batch = collate_items([[item]], pad_id=self.judge_a_tok.pad_token_id)
        input_ids = batch["input_ids"].to(self.device)
        attention_mask = batch["attention_mask"].to(self.device)
        marker_pos = batch["marker_pos"].to(self.device)
        marker_mask = batch["marker_mask"].to(self.device)
        qtype = batch["qtype"].to(self.device)

        with torch.no_grad():
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                logits, _ = self.judge_a_model(input_ids, attention_mask, marker_pos, marker_mask, qtype)

        c_idx = ordered_keys.index("CONTINUE")
        n_idx = ordered_keys.index("NEW")

        l_c = logits[0, c_idx].item()
        l_n = logits[0, n_idx].item()

        probs = torch.softmax(torch.tensor([l_c, l_n], dtype=torch.float32), dim=-1).tolist()
        return probs[0], probs[1]

    def _evaluate_judge_b(self, event, candidates, local_context) -> Dict[str, float]:
        ctx_lines = [
            f"{m.sender_name or m.sender_id or '用户'}: {m.text}"
            for m in local_context[-8:]
        ]
        reply_str = f" (回复: {event.reply_to})" if event.reply_to else ""
        target_str = f"{event.sender_name or event.sender_id or '用户'}: {event.text}{reply_str}"
        state = f"[近期上下文]\n" + "\n".join(ctx_lines) + f"\n[当前消息] {target_str}"

        criteria = {}
        for c in candidates:
            snip = " ; ".join(m.text[:28] for m in c.recent_events[-2:]) if c.recent_events else c.summary[:28]
            criteria[c.id] = f"延续话题: {snip}"

        keys = list(criteria.keys())
        seed = int(hashlib.md5(event.id.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        order = list(range(len(keys)))
        rng.shuffle(order)
        ordered_keys = [keys[i] for i in order]

        q = {
            "t": "choice",
            "ins": "当前目标消息延续哪个候选话题？",
            "crit": criteria
        }

        ids, markers = build_sequence(
            self.judge_b_tok,
            state,
            q,
            max_len=1024,
            head_max_len=256,
            option_order=order,
            truncate_left=True,
        )

        item = {
            "ids": ids,
            "markers": markers,
            "qtype": QTYPES["choice"],
            "target": [0.0] * len(keys),
            "label": 0,
        }

        batch = collate_items([[item]], pad_id=self.judge_b_tok.pad_token_id)
        input_ids = batch["input_ids"].to(self.device)
        attention_mask = batch["attention_mask"].to(self.device)
        marker_pos = batch["marker_pos"].to(self.device)
        marker_mask = batch["marker_mask"].to(self.device)
        qtype = batch["qtype"].to(self.device)

        with torch.no_grad():
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                logits, _ = self.judge_b_model(input_ids, attention_mask, marker_pos, marker_mask, qtype)

        k = len(ordered_keys)
        raw_logits = logits[0, :k].float()
        probs = torch.softmax(raw_logits, dim=-1).cpu().tolist()

        return {ordered_keys[i]: probs[i] for i in range(k)}


class HnrOneStageEventCachedScorer:
    """One-Stage Scorer using the frozen HNR checkpoint."""

    def __init__(self, agent, store, config):
        self.agent = agent
        self.store = store
        self.config = config
        self._current_event_id = None
        self._cached_scores: Dict[str, float] = {}

    def score(self, event, episode, reply_signal=False, local_context=(), reply_target=None) -> float:
        if self._current_event_id != event.id:
            self._current_event_id = event.id
            self._cached_scores = {}

            candidates = build_candidates(event, self.store, self.config)
            if not candidates:
                return 0.0

            ctx_lines = [
                f"{m.sender_name or m.sender_id or '用户'}: {m.text}"
                for m in local_context[-8:]
            ]
            reply_str = f" (回复: {event.reply_to})" if event.reply_to else ""
            target_str = f"{event.sender_name or event.sender_id or '用户'}: {event.text}{reply_str}"
            state = f"[近期上下文]\n" + "\n".join(ctx_lines) + f"\n[当前消息] {target_str}"

            criteria = {}
            for cand in candidates:
                c_snips = " ; ".join(m.text[:28] for m in cand.recent_events[-2:]) if cand.recent_events else cand.summary[:28]
                criteria[cand.id] = f"延续话题: {c_snips}"
            criteria["NEW"] = "新话题: 开启完全独立的新讨论线程"
            criteria["UNKNOWN"] = "信息不足: 缺乏上下文、图片未展示或代词指代不明"

            q = {
                "type": "choice",
                "instructions": "当前目标消息属于哪个 Episode？",
                "criteria": criteria
            }

            res = self.agent.system_one(state, {"routing": q})
            ans = res["answers"]["routing"]
            probs = ans["probabilities"]
            for cand in candidates:
                self._cached_scores[cand.id] = float(probs.get(cand.id, 0.0))

        return self._cached_scores.get(episode.id, 0.0)


import random

def run_replay(router_kind: str, raw_window_path: str, boundary_th: float = 0.50) -> Dict[str, Any]:
    print(f"\n==========================================")
    print(f"Running 150 Replay: {router_kind}")
    print(f"==========================================")

    # Load 150 events
    events_raw = []
    with open(raw_window_path) as f:
        for line in f:
            events_raw.append(json.loads(line))

    assert len(events_raw) == 150, f"Expected exactly 150 events, got {len(events_raw)}"

    config = EpisodeRouterConfig()
    store = EpisodeStore(config)

    if router_kind == "two_stage":
        judge_a_ckpt = Path(RESULTS_DIR) / "boundary/checkpoint"
        judge_b_ckpt = Path(RESULTS_DIR) / "ranking/checkpoint"

        agent_a = laya.load(str(judge_a_ckpt), device="cuda")
        agent_b = laya.load(str(judge_b_ckpt), device="cuda")

        two_stage_router = TwoStageRouter(
            store=store,
            judge_a_model=agent_a.model,
            judge_a_tok=agent_a.tok,
            judge_b_model=agent_b.model,
            judge_b_tok=agent_b.tok,
            config=config,
            boundary_threshold=boundary_th,
            device="cuda",
        )

        class CustomRuntime:
            def __init__(self, store, router, config):
                self.store = store
                self.router = router
                self.config = config
                from xtw_core.episode_router.p0 import ConversationContextBuffer, SimpleEpisodeSummarizer
                self.context_buffer = ConversationContextBuffer()
                self.summarizer = SimpleEpisodeSummarizer()

            def ingest_with_result(self, event):
                self.store.close_expired(event.timestamp)
                local_context = self.context_buffer.recent(self.config.local_context_events)
                reply_target = self.context_buffer.find(event.reply_to) if event.reply_to else None
                result = self.router.route(event, local_context=local_context, reply_target=reply_target)
                if result.decision == "NEW":
                    episode = self.store.create_episode(event)
                else:
                    episode = self.store.append_event(result.episode_id or "", event)
                if len(episode.event_ids) % self.store.lifecycle.summary_update_every_n_events == 0:
                    episode.summary = self.summarizer.summarize(episode)
                self.context_buffer.append(event)
                return episode, result

        runtime = CustomRuntime(store, two_stage_router, config)

    elif router_kind == "hnr_one_stage":
        hnr_ckpt = Path("/home/longzhooou/Documents/Programs/小天文设计素材/bot/projects/memory/benchmark-results/laya-episode-routing-hard-negative-ranking-v0.1/training/one-run/best-dev-ranking")
        from laya.agent import Agent
        agent = Agent(str(hnr_ckpt), device="cuda")
        scorer = HnrOneStageEventCachedScorer(agent, store, config)
        from xtw_core.episode_router.p0 import EpisodeRouter
        router = EpisodeRouter(store=store, scorer=scorer, config=config)
        runtime = EpisodeRuntime(store=store, router=router)

    records = []
    seen = set()
    prev_time = None
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
        episode, result = runtime.ingest_with_result(event)
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

    # Collect summary stats
    episodes = list(store.episodes.values())
    ep_count = len(episodes)
    new_count = sum(1 for r in records if r["decision"] == "NEW")
    cont_count = sum(1 for r in records if r["decision"] == "CONTINUE")

    ep_lens = [len(e.event_ids) for e in episodes]
    mean_len = sum(ep_lens) / len(ep_lens) if ep_lens else 0.0

    print(f"Replay completed in {elapsed:.2f}s ({elapsed/150*1000:.2f} ms/event)")
    print(f"Episodes: {ep_count} | NEW: {new_count} | CONTINUE: {cont_count} | Mean Length: {mean_len:.2f}")

    return {
        "router_kind": router_kind,
        "events_processed": len(records),
        "episodes_count": ep_count,
        "new_count": new_count,
        "continue_count": cont_count,
        "mean_episode_length": mean_len,
        "elapsed_seconds": elapsed,
        "episodes": [
            {
                "id": e.id,
                "status": e.status,
                "summary": e.summary,
                "event_ids": e.event_ids,
                "created_at": e.created_at.isoformat(),
                "last_event_at": e.last_event_at.isoformat(),
            }
            for e in episodes
        ],
        "records": records,
    }


def main():
    with GpuLock(job_name="router_two_stage_replay_150"):
        print("[GPU] Acquired exclusive GPU lock for 150-message continuous replay.")

        replay_dir = Path(RESULTS_DIR) / "replay"
        replay_dir.mkdir(parents=True, exist_ok=True)

        # 1. Run Two-Stage Router v0.2
        two_stage_res = run_replay("two_stage", RAW_WINDOW_150_PATH, boundary_th=0.50)
        with open(replay_dir / "two_stage_replay.json", "w") as f:
            json.dump(two_stage_res, f, indent=2, ensure_ascii=False)

        # 2. Run HNR one-stage on same 150 messages for exact direct comparison
        hnr_one_stage_res = run_replay("hnr_one_stage", RAW_WINDOW_150_PATH)
        with open(replay_dir / "hnr_one_stage_replay.json", "w") as f:
            json.dump(hnr_one_stage_res, f, indent=2, ensure_ascii=False)

        print("\nAll replay runs completed and saved successfully!")


if __name__ == "__main__":
    main()
