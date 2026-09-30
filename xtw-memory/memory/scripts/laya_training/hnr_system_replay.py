"""System replay evaluation comparing baseline vs HNR ranking checkpoint.

Runs EpisodeRuntime continuous replay over the clean evaluation window and
computes macro system-level metrics:
- Episode creation rate (CONTINUE vs NEW vs UNKNOWN)
- Average episode length / lifespan
- Confidence margin distribution
- End-to-end routing latency
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/home/longzhooou/Documents/Programs/小天文设计素材/bot/projects/xtw-playground")
sys.path.insert(0, "/home/longzhooou/.cache/uv-laya-alt/archive-v0/FX854Ga3GurRg6vZ")

from xtw_core.episode_router.p0 import (
    EpisodeConfig, EpisodeEvent, EpisodeRouter, EpisodeRuntime, EpisodeStore,
)
from laya.agent import Agent
from memory.scripts.gpu_gate import GpuLock
import memory.scripts.laya_training.hnr_source_preflight as source
from memory.scripts.laya_training.hnr_runtime_capture import BaselineScorer, WARMUP_START


def run_replay(model_dir: Path, output_file: Path, max_events: int = 5000,
               audit_file: Path | None = None) -> dict:
    assert not output_file.exists(), f"Do not overwrite existing replay: {output_file}"
    if audit_file is not None:
        assert not audit_file.exists(), f"Do not overwrite existing audit: {audit_file}"
    config = EpisodeConfig()
    store = EpisodeStore(config)
    latencies = []
    decisions = {"CONTINUE": 0, "NEW": 0, "UNKNOWN": 0}
    reasons = {}
    event_digest = hashlib.sha256()
    audit = []

    with GpuLock(job_name=f"laya_hnr_replay_{output_file.stem}"):
        agent = Agent(str(model_dir), device="cuda")
        scorer = BaselineScorer(agent, store, config)
        router = EpisodeRouter(store=store, scorer=scorer, config=config)
        runtime = EpisodeRuntime(store=store, router=router)

        start_time = time.time()
        event_count = 0

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

                event = EpisodeEvent(
                    row["message_id"], when, row["participant_id"],
                    row["participant_id"], row.get("text") or "",
                    row.get("reply_to_message_id"), ()
                )
                # Fingerprint raw input, not model-dependent routing output.
                event_digest.update((json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n").encode())

                t0 = time.time()
                _, result = runtime.ingest_with_result(event)
                latencies.append((time.time() - t0) * 1000.0)

                decisions[result.decision] = decisions.get(result.decision, 0) + 1
                if result.reason:
                    reasons[result.reason] = reasons.get(result.reason, 0) + 1
                if audit_file is not None:
                    audit.append({"message_id": event.id, "timestamp": when.isoformat(),
                                  "participant_id": row["participant_id"], "text": row.get("text") or "",
                                  "reply_to_message_id": row.get("reply_to_message_id"),
                                  "decision": result.decision, "episode_id": result.episode_id,
                                  "decision_basis": result.decision_basis,
                                  "best_score": result.best_score, "second_best_score": result.second_best_score,
                                  "candidate_scores": result.candidate_scores})

                event_count += 1
                if max_events is not None and event_count >= max_events:
                    break

        total_time = time.time() - start_time

    episodes = list(store.episodes.values())
    lengths = [len(ep.event_ids) for ep in episodes]
    sorted_lengths = sorted(lengths)

    summary = {
        "model_dir": str(model_dir),
        "events_processed": event_count,
        "input_sha256": event_digest.hexdigest(),
        "elapsed_seconds": total_time,
        "mean_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
        "decision_distribution": decisions,
        "decision_reasons": reasons,
        "total_episodes_created": len(episodes),
        "mean_episode_length": sum(lengths) / len(lengths) if lengths else 0.0,
        "max_episode_length": max(lengths) if lengths else 0,
        "median_episode_length": (sorted_lengths[(len(lengths)-1)//2] + sorted_lengths[len(lengths)//2])/2 if lengths else 0,
        "singleton_rate": sum(x == 1 for x in lengths) / len(lengths) if lengths else 0,
        "singleton_event_rate": sum(x == 1 for x in lengths) / event_count if event_count else 0,
    }
    if audit_file is not None:
        assignment = {mid: ep.id for ep in episodes for mid in ep.event_ids}
        assert len(assignment) == event_count, "Missing or duplicated event assignment"
        audit_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with audit_file.open("x") as stream:
            for item in audit:
                item["assigned_episode_id"] = assignment[item["message_id"]]
                stream.write(json.dumps(item, ensure_ascii=False) + "\n")
        audit_file.chmod(0o600)

    output_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-events", type=int, default=5000)
    parser.add_argument("--audit-output", type=Path)
    args = parser.parse_args()
    run_replay(args.model_dir, args.output, max_events=args.max_events, audit_file=args.audit_output)


if __name__ == "__main__":
    main()
