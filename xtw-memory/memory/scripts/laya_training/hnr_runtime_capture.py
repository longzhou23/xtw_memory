"""Capture real Router candidate competition from frozen clean windows.

The frozen 20K checkpoint and existing Router/policy are used unchanged. The
fresh HOLDOUT trace is emitted to a separate sealed subtree and never used by
training. No semantic labels, review outcomes or teacher predictions are read.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import sys

import hnr_source_preflight as source
from hnr_blind_packets import EXPECTED_WINDOW_MANIFEST_SHA256, REVIEW_DIR, HOLDOUT_DIR

BASE_DIR = source.ROOT
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "xtw-playground"))
from xtw_core.episode_router.p0 import (
    EpisodeEvent, EpisodeRouter, EpisodeRouterConfig, EpisodeRoutingPolicyConfig,
    EpisodeRuntime, EpisodeStore, build_candidates,
)
from memory.scripts.gpu_gate import GpuLock

LAYA_PACKAGE = "/home/longzhooou/.cache/uv-laya-alt/archive-v0/FX854Ga3GurRg6vZ"
sys.path.insert(0, LAYA_PACKAGE)
from laya.agent import Agent

CHECKPOINT = source.ROOT / "memory/benchmark-results/laya-episode-routing-weak-silver-scaling-v0.2/runs/322m-20k/best-dev"
CHECKPOINT_SHA256 = "05688142b1501bb193253f1bbd5947f8fa7e91d9db2cdcf4ea3215d73d53fcfc"
# Start 3 days before the first TRAIN event to seed the frozen EpisodeStore TTL.
WARMUP_START = datetime.fromisoformat("2025-12-29T00:00:00+08:00")


class BaselineScorer:
    """Same native choice-state serialization as the frozen 20K audit scorer."""

    def __init__(self, agent: Agent, store: EpisodeStore, config: EpisodeRouterConfig) -> None:
        self.agent, self.store, self.config = agent, store, config
        self.last_event_id: str | None = None
        self.cached_scores: dict[str, float] = {}

    def score(self, event, episode, reply_signal=False, local_context=(), reply_target=None) -> float:
        if self.last_event_id != event.id:
            self.last_event_id = event.id
            self.cached_scores = {}
            candidates = build_candidates(event, self.store, self.config)
            if not candidates:
                return 0.0
            ctx = [f"{m.sender_name or m.sender_id or '用户'}: {m.text}" for m in local_context[-8:]]
            reply = f" (回复: {event.reply_to})" if event.reply_to else ""
            target = f"{event.sender_name or event.sender_id or '用户'}: {event.text}{reply}"
            state = "[近期上下文]\n" + "\n".join(ctx) + f"\n[当前消息] {target}"
            criteria = {
                cand.id: "延续话题: " + " ; ".join(m.text[:28] for m in cand.recent_events[-2:])
                for cand in candidates
            }
            criteria["NEW"] = "新话题: 开启完全独立的新讨论线程"
            criteria["UNKNOWN"] = "信息不足: 缺乏上下文、图片未展示或代词指代不明"
            answer = self.agent.system_one(state, {"routing": {
                "type": "choice", "instructions": "当前目标消息属于哪个 Episode？", "criteria": criteria
            }})
            probs = answer["answers"]["routing"]["probabilities"]
            self.cached_scores = {cand.id: float(probs.get(cand.id, 0.0)) for cand in candidates}
        return self.cached_scores.get(episode.id, 0.0)


def load_targets() -> dict[str, str]:
    assert source.file_sha256(source.OUTPUT / "window-manifest.json") == EXPECTED_WINDOW_MANIFEST_SHA256
    out: dict[str, str] = {}
    for name in ("TRAIN", "DEV", "HOLDOUT"):
        folder = HOLDOUT_DIR if name == "HOLDOUT" else REVIEW_DIR
        with (folder / f"{name.lower()}-blind.jsonl").open() as stream:
            for line in stream:
                row = json.loads(line)
                assert row["target_message_id"] not in out
                out[row["target_message_id"]] = name
    return out


def trace(event, candidates, result, recent_context) -> dict:
    target_terms = set(event.text.lower().split())
    records = []
    for cand in candidates:
        last = cand.recent_events[-1] if cand.recent_events else None
        cand_text = " ".join(m.text for m in cand.recent_events[-2:])
        terms = set(cand_text.lower().split())
        records.append({
            "runtime_episode_id": cand.id,
            "anchor_message_ids": [m.id for m in cand.recent_events],
            "all_episode_message_ids": list(cand.event_ids),
            "recent_messages": [{"message_id": m.id, "participant_id": m.sender_id,
                                 "timestamp": m.timestamp.isoformat(), "text": m.text}
                                for m in cand.recent_events[-2:]],
            "score": result.candidate_scores.get(cand.id),
            "same_speaker": event.sender_id in cand.participants,
            "lexical_overlap_count": len(target_terms & terms),
            "temporal_distance_seconds": (event.timestamp - last.timestamp).total_seconds() if last else None,
        })
    return {
        "target_message_id": event.id,
        "candidate_count": len(candidates),
        "candidates": records,
        "recent_state_message_ids": [m.id for m in recent_context],
        "baseline_decision": result.decision,
        "baseline_decision_basis": result.decision_basis,
        "baseline_selected_episode_id": result.episode_id,
        "baseline_best_score": result.best_score,
        "baseline_second_score": result.second_best_score,
        "baseline_margin": result.margin,
    }


def run(output: Path, max_events: int | None) -> None:
    assert source.file_sha256(source.DATA) == json.loads((source.OUTPUT / "window-manifest.json").read_text())["source"]["sha256"]
    assert source.file_sha256(CHECKPOINT / "model.safetensors") == CHECKPOINT_SHA256
    targets = load_targets()
    assert not output.exists(), "Do not overwrite or resume a partial candidate artifact"
    output.mkdir(parents=True, mode=0o700)
    config = EpisodeRouterConfig(routing_threshold=0.55,
                                 routing_policy=EpisodeRoutingPolicyConfig(high_threshold=0.55, low_floor=0.25, min_margin=0.15))
    counts: Counter[str] = Counter()
    files = {}
    try:
        # HOLDOUT is a distinct sealed directory, not imported by the trainer.
        for name in ("TRAIN", "DEV", "HOLDOUT"):
            folder = ((output / "holdout-smoke" if max_events is not None
                       else source.OUTPUT / "sealed-fresh-holdout/candidates")
                      if name == "HOLDOUT" else output)
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = folder / f"{name.lower()}-candidate-trace.jsonl"
            assert not path.exists(), f"Candidate trace already exists: {path}"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            files[name] = os.fdopen(fd, "w")
        with GpuLock(job_name="laya_hnr_baseline_candidate_capture"):
            agent = Agent(str(CHECKPOINT), device="cuda")
            store = EpisodeStore(config)
            scorer = BaselineScorer(agent, store, config)
            runtime = EpisodeRuntime(store=store, router=EpisodeRouter(store=store, scorer=scorer, config=config))
            with source.DATA.open() as stream:
                for line in stream:
                    row = json.loads(line)
                    if row["conversation_id"] != "c_000001":
                        continue
                    when = datetime.fromisoformat(row["timestamp"])
                    if when < WARMUP_START:
                        continue
                    if when.year > 2026 or (when.year == 2026 and when.month > 5):
                        break
                    event = EpisodeEvent(row["message_id"], when, row["participant_id"],
                                         row["participant_id"], row.get("text") or "",
                                         row.get("reply_to_message_id"), ())
                    store.close_expired(when)
                    candidates = build_candidates(event, store, config)
                    context = runtime.context_buffer.recent(config.local_context_events)
                    _, result = runtime.ingest_with_result(event)
                    counts["events"] += 1
                    window = targets.get(event.id)
                    if window:
                        files[window].write(json.dumps(trace(event, candidates, result, context), ensure_ascii=False) + "\n")
                        counts[window] += 1
                    if when.year == 2026:
                        counts["window_events"] += 1
                    if max_events is not None and counts["window_events"] >= max_events:
                        break
                    if counts["events"] % 5000 == 0:
                        print(f"[capture] events={counts['events']} train={counts['TRAIN']} dev={counts['DEV']} holdout={counts['HOLDOUT']}", flush=True)
    finally:
        for handle in files.values():
            handle.close()
    # Smoke output is engineering-only; no score or performance claims.
    if max_events is None:
        expected = json.loads((source.OUTPUT / "window-manifest.json").read_text())["windows"]
        for name in ("TRAIN", "DEV", "HOLDOUT"):
            assert counts[name] == expected[name]["fresh_eligible_message_count_upper_bound"]
    summary = {"checkpoint_sha256": CHECKPOINT_SHA256,
               "source_window_manifest_sha256": EXPECTED_WINDOW_MANIFEST_SHA256,
               "policy": {"high": 0.55, "floor": 0.25, "margin": 0.15},
               "warmup_start": WARMUP_START.isoformat(),
               "events_processed": counts["events"],
               "targets_by_window": {name: counts[name] for name in ("TRAIN", "DEV", "HOLDOUT")},
               "smoke_only": max_events is not None,
               "judgment_holdout_read": False}
    (output / "capture-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-events", type=int, default=None)
    args = parser.parse_args()
    assert args.output.resolve().is_relative_to((source.OUTPUT / "dataset").resolve()), "Output must be under HNR dataset"
    if args.max_events is not None:
        assert 1 <= args.max_events <= 128, "Only 128-event engineering smoke is allowed"
    run(args.output, args.max_events)


if __name__ == "__main__":
    main()
