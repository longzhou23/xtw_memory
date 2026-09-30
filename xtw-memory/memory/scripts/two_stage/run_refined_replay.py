#!/usr/bin/env python3
"""Run 150-message replay for Refined Two-Stage Router v0.2."""

import argparse
from dataclasses import asdict
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

from memory.scripts.two_stage.common import (
    RAW_WINDOW_150_PATH,
)
from memory.scripts.gpu_gate import GpuLock

import torch
import laya
from laya.common import build_sequence, collate_items, QTYPES
from xtw_core.episode_router.p0 import (
    EpisodeRouterConfig,
    EpisodeStore,
    EpisodeEvent,
    build_candidates,
    is_low_information_event,
    ConversationContextBuffer,
    SimpleEpisodeSummarizer,
    RoutingResult,
)

OUT_BASE = PROJECT_ROOT / "memory/benchmark-results/router-v0.2-small-scale-refinement-v0.1"
REPLAY_OUT = OUT_BASE / "replay-150"
REPLAY_OUT.mkdir(parents=True, exist_ok=True)


class RefinedTwoStageRouter:
    """Refined Two-Stage Router v0.2 with Structural Reply Feature."""

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
        if (
            is_low_information_event(event)
            and not event.reply_to
            and not any(item.text.strip() and not is_low_information_event(item) for item in local_context)
        ):
            return RoutingResult("NEW", None, 0.0, {}, reason="INSUFFICIENT_CONTEXT")

        candidates = build_candidates(event, self.store, self.config)
        if not candidates:
            return RoutingResult("NEW", None, 0.0, {}, reason="NO_CANDIDATES")

        p_cont, p_new = self._evaluate_judge_a(event, candidates, local_context)

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
            has_reply = bool(event.reply_to and event.reply_to in c.event_ids)
            tag = " [包含回复目标]" if has_reply else ""
            cand_lines.append(f"- 话题 {i+1}{tag}: {snip}")
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
            has_reply = bool(event.reply_to and event.reply_to in c.event_ids)
            tag = " [包含回复目标]" if has_reply else ""
            criteria[c.id] = f"延续话题{tag}: {snip}"

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


def run_single_replay(boundary_th: float = 0.50):
    events_raw = []
    with open(RAW_WINDOW_150_PATH) as f:
        for line in f:
            events_raw.append(json.loads(line))

    config = EpisodeRouterConfig()
    store = EpisodeStore(config)

    judge_a_ckpt = OUT_BASE / "boundary/checkpoint"
    judge_b_ckpt = OUT_BASE / "ranking/checkpoint"

    agent_a = laya.load(str(judge_a_ckpt), device="cuda")
    agent_b = laya.load(str(judge_b_ckpt), device="cuda")

    router = RefinedTwoStageRouter(
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

    runtime = CustomRuntime(store, router, config)

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
    episodes = list(store.episodes.values())
    ep_count = len(episodes)
    new_count = sum(1 for r in records if r["decision"] == "NEW")
    cont_count = sum(1 for r in records if r["decision"] == "CONTINUE")
    mean_len = sum(len(e.event_ids) for e in episodes) / len(episodes) if episodes else 0.0

    print(f"Th={boundary_th:.2f} -> Episodes: {ep_count} | NEW: {new_count} | CONT: {cont_count} | Mean Length: {mean_len:.2f} | Latency: {elapsed/150*1000:.2f} ms/event")

    return {
        "boundary_threshold": boundary_th,
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
            }
            for e in episodes
        ],
        "records": records,
    }


def main():
    with GpuLock(job_name="refined_two_stage_replay"):
        print("[GPU] Acquired exclusive GPU lock for refined replay.")
        for th in [0.20, 0.30, 0.40, 0.50]:
            res = run_single_replay(boundary_th=th)
            with open(REPLAY_OUT / f"replay_th{int(th*100):02d}.json", "w", encoding="utf-8") as f:
                json.dump(res, f, indent=2, ensure_ascii=False)

    print("All refined replays complete!")


if __name__ == "__main__":
    main()
