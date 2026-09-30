#!/usr/bin/env python3
"""Execute 400-message continuous replay on fresh unseen community using frozen Refined Two-Stage Router v0.2."""

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

BASE_EXP_DIR = PROJECT_ROOT / "memory/benchmark-results/router-v0.2-small-scale-refinement-v0.1"
JUDGE_A_CKPT = BASE_EXP_DIR / "boundary/checkpoint"
JUDGE_B_CKPT = BASE_EXP_DIR / "ranking/checkpoint"

REPLAY_DIR = PROJECT_ROOT / "memory/benchmark-results/router-v0.2-fresh-unseen-community-replay-v0.1"
WINDOW_FILE = REPLAY_DIR / "replay-window.jsonl"
RUNTIME_DIR = REPLAY_DIR / "runtime"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

EXPECTED_WINDOW_SHA256 = "063de8ca5a18891a9b64898a186220945a05e9beb48402d7a2d0b3f56d49375d"
EXPECTED_JUDGE_A_SHA256 = "482963c38aa714a710ac97a27cdd1c231f77911f4fbc527eeb3d6c645aa139cd"
EXPECTED_JUDGE_B_SHA256 = "41a06635613e3969ecf27315b37f68b36e835ad2df39c4e403fade575a4cbb18"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192 * 1024):
            h.update(chunk)
    return h.hexdigest()


class TwoStageRouterFresh:
    """Frozen Two-Stage Router v0.2."""

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

        # Frozen formal boundary threshold: 0.50
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


def main():
    # Preflight verification of frozen models and window
    print("=== Preflight Integrity Check ===")
    assert file_sha256(WINDOW_FILE) == EXPECTED_WINDOW_SHA256, "Window file modified after freezing!"
    assert file_sha256(JUDGE_A_CKPT / "model.safetensors") == EXPECTED_JUDGE_A_SHA256, "Judge A checkpoint mismatch!"
    assert file_sha256(JUDGE_B_CKPT / "model.safetensors") == EXPECTED_JUDGE_B_SHA256, "Judge B checkpoint mismatch!"
    print("All checksums verified. Starting fresh replay...")

    with GpuLock(job_name="fresh_unseen_replay_400"):
        print("[GPU] Acquired exclusive lock for RTX 5060 Ti.")

        # Load models
        agent_a = laya.load(str(JUDGE_A_CKPT), device="cuda")
        agent_b = laya.load(str(JUDGE_B_CKPT), device="cuda")

        # Load window events
        events_raw = []
        with open(WINDOW_FILE) as f:
            for line in f:
                events_raw.append(json.loads(line))

        assert len(events_raw) == 400

        config = EpisodeRouterConfig()
        store = EpisodeStore(config)
        context_buffer = ConversationContextBuffer()
        summarizer = SimpleEpisodeSummarizer()

        router = TwoStageRouterFresh(
            store=store,
            judge_a_model=agent_a.model,
            judge_a_tok=agent_a.tok,
            judge_b_model=agent_b.model,
            judge_b_tok=agent_b.tok,
            config=config,
            boundary_threshold=0.50,  # Frozen formal threshold
            device="cuda",
        )

        decisions = []
        traces = []
        t0 = time.time()

        for idx, row in enumerate(events_raw):
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

            start_t = time.perf_counter()
            result = router.route(event, local_context=local_context, reply_target=reply_target)
            lat_ms = round((time.perf_counter() - start_t) * 1000, 2)

            if result.decision == "NEW":
                episode = store.create_episode(event)
            else:
                episode = store.append_event(result.episode_id or "", event)

            if len(episode.event_ids) % store.lifecycle.summary_update_every_n_events == 0:
                episode.summary = summarizer.summarize(episode)

            context_buffer.append(event)

            decision_record = {
                "rawIndex": row["rawIndex"],
                "eventId": row["eventId"],
                "timestamp": row["timestamp"],
                "senderId": row.get("senderId"),
                "senderName": row.get("senderName"),
                "text": row["text"],
                "replyTo": row.get("replyTo"),
                "decision": result.decision,
                "selectedEpisodeId": episode.id,
                "decisionBasis": result.decision_basis,
                "bestScore": result.best_score,
                "candidateScores": result.candidate_scores,
                "reason": result.reason,
                "latencyMs": lat_ms,
                "episodeSummary": episode.summary,
            }
            decisions.append(decision_record)

            traces.append({
                "eventId": row["eventId"],
                "rawIndex": row["rawIndex"],
                "latencyMs": lat_ms,
                "decision": result.decision,
                "selectedEpisodeId": episode.id,
                "candidateScores": result.candidate_scores,
            })

            if (idx + 1) % 100 == 0:
                print(f"Processed {idx + 1}/400 events...")

        elapsed = time.time() - t0
        print(f"\nFresh Replay completed in {elapsed:.2f}s ({elapsed/400*1000:.2f} ms/event).")

        # Save routing-decisions.jsonl
        with open(RUNTIME_DIR / "routing-decisions.jsonl", "w", encoding="utf-8") as f:
            for d in decisions:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")

        # Save traces.jsonl
        with open(RUNTIME_DIR / "traces.jsonl", "w", encoding="utf-8") as f:
            for t in traces:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")

        # Save episodes.json
        episodes_list = [
            {
                "id": ep.id,
                "status": ep.status,
                "summary": ep.summary,
                "event_ids": ep.event_ids,
                "event_count": len(ep.event_ids),
                "participants": list(ep.participants),
                "created_at": ep.created_at.isoformat(),
                "last_event_at": ep.last_event_at.isoformat(),
            }
            for ep in store.episodes.values()
        ]
        with open(RUNTIME_DIR / "episodes.json", "w", encoding="utf-8") as f:
            json.dump(episodes_list, f, indent=2, ensure_ascii=False)

        new_count = sum(1 for d in decisions if d["decision"] == "NEW")
        cont_count = sum(1 for d in decisions if d["decision"] == "CONTINUE")
        lengths = [ep["event_count"] for ep in episodes_list]
        import statistics
        mean_len = sum(lengths) / len(lengths) if lengths else 0.0
        median_len = statistics.median(lengths) if lengths else 0.0
        singletons = sum(1 for l in lengths if l == 1)

        print(f"\nReplay Statistics:")
        print(f"  Processed: {len(decisions)} messages")
        print(f"  Episodes:  {len(episodes_list)}")
        print(f"  NEW:       {new_count} ({new_count/len(decisions)*100:.1f}%)")
        print(f"  CONTINUE:  {cont_count} ({cont_count/len(decisions)*100:.1f}%)")
        print(f"  Mean Size: {mean_len:.2f}")
        print(f"  Med Size:  {median_len:.1f}")
        print(f"  Singletons: {singletons} ({singletons/len(episodes_list)*100:.1f}%)")


if __name__ == "__main__":
    main()
