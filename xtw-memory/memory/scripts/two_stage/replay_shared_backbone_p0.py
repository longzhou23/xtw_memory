#!/usr/bin/env python3
"""One paired, threshold-0.50 regression replay on the frozen 150-message set.

The P0 EpisodeRuntime, candidate builder and refined router formatting are
reused unchanged. Only the two model views are swapped for the shared model.
No c_000008 input, threshold sweep, or historical output writes.
"""

import gc
import hashlib
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "xtw-playground"))
from memory.scripts.two_stage.common import RAW_WINDOW_150_PATH
from memory.scripts.gpu_gate import GpuLock
from memory.scripts.two_stage.run_refined_replay import RefinedTwoStageRouter
from memory.scripts.two_stage.shared_backbone_p0 import load_parts, parameter_audit

import laya
import torch
from torch import nn
from xtw_core.episode_router.p0 import (
    EpisodeEvent, EpisodeRouterConfig, EpisodeRuntime, EpisodeStore,
    SimpleEpisodeSummarizer,
)

OUT = ROOT / "memory/benchmark-results/router-v0.2-shared-backbone-p0"
REF = ROOT / "memory/benchmark-results/router-v0.2-small-scale-refinement-v0.1"
EXPECTED_HASH = "bce62c19d65d931cb047f8db92b9be60c9d833e6a4529ef270a1cc40d8ec1075"


class ModelView(nn.Module):
    def __init__(self, shared, task):
        super().__init__()
        self.shared = shared
        self.task = task

    def forward(self, input_ids, attention_mask, marker_pos, marker_mask, qtype):
        return self.shared(input_ids, attention_mask, marker_pos, marker_mask, qtype, task=self.task), None


class TimedRefinedRouter(RefinedTwoStageRouter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.times = {"boundary": [], "ranking": []}

    def _evaluate_judge_a(self, event, candidates, local_context):
        torch.cuda.synchronize()
        start = time.perf_counter()
        value = super()._evaluate_judge_a(event, candidates, local_context)
        torch.cuda.synchronize()
        self.times["boundary"].append(1000 * (time.perf_counter() - start))
        return value

    def _evaluate_judge_b(self, event, candidates, local_context):
        torch.cuda.synchronize()
        start = time.perf_counter()
        value = super()._evaluate_judge_b(event, candidates, local_context)
        torch.cuda.synchronize()
        self.times["ranking"].append(1000 * (time.perf_counter() - start))
        return value


def replay(events, a, tok_a, b, tok_b):
    config = EpisodeRouterConfig()
    store = EpisodeStore(config)
    router = TimedRefinedRouter(store, a, tok_a, b, tok_b, config=config,
                                boundary_threshold=0.50, device="cuda")
    runtime = EpisodeRuntime(store=store, router=router,
                             summarizer=SimpleEpisodeSummarizer(), config=config)
    rows = []
    for row in events:
        event = EpisodeEvent(row["eventId"], datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")),
                             row.get("senderId"), row.get("senderName"), row["text"], row.get("replyTo"),
                             tuple(row.get("mentions", [])))
        torch.cuda.synchronize()
        start = time.perf_counter()
        episode, result = runtime.ingest_with_result(event)
        torch.cuda.synchronize()
        elapsed = 1000 * (time.perf_counter() - start)
        rows.append({"rawIndex": row["rawIndex"], "eventId": row["eventId"],
                     "decision": result.decision, "episodeId": episode.id,
                     "replyTo": row.get("replyTo"), "reason": result.reason,
                     "candidateScores": result.candidate_scores, "latency_ms": elapsed})
    return {"messages": len(rows), "episodes": len(store.episodes),
            "new": sum(r["decision"] == "NEW" for r in rows),
            "continue": sum(r["decision"] == "CONTINUE" for r in rows),
            "records": rows, "episodes_list": [{"id": ep.id, "event_ids": list(ep.event_ids)}
                                            for ep in store.episodes.values()],
            "latency": {"boundary_ms_median": statistics.median(router.times["boundary"]),
                        "ranking_ms_median": statistics.median(router.times["ranking"]) if router.times["ranking"] else None,
                        "decision_ms_median": statistics.median(r["latency_ms"] for r in rows)}}


def trial(events, shared):
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    if shared:
        from memory.scripts.two_stage.shared_backbone_p0 import SharedBackboneDualHead
        agent = laya.load(str(REF / "boundary/checkpoint"), device="cuda")
        tok = agent.tok
        base = agent.model
        # Instantiate placeholder scoring head; load_parts replaces its values.
        import copy
        model = SharedBackboneDualHead(base.encoder, base.head, base.type_emb,
                                       base.scorer, copy.deepcopy(base.scorer)).cuda().eval()
        del base, agent
        load_parts(model, OUT / "model")
        counts = parameter_audit(model)
        views = (ModelView(model, "boundary"), tok, ModelView(model, "ranking"), tok)
        assert views[0].shared is views[2].shared
    else:
        agent_a = laya.load(str(REF / "boundary/checkpoint"), device="cuda")
        agent_b = laya.load(str(REF / "ranking/checkpoint"), device="cuda")
        counts = {"total_unique": sum(p.numel() for p in agent_a.model.parameters())
                  + sum(p.numel() for p in agent_b.model.parameters())}
        views = (agent_a.model.eval(), agent_a.tok, agent_b.model.eval(), agent_b.tok)
    idle_bytes = torch.cuda.memory_allocated()
    result = replay(events, *views)
    result["efficiency"] = {"total_unique_params": counts["total_unique"],
                            "idle_allocated_vram_bytes": idle_bytes,
                            "peak_allocated_vram_bytes": torch.cuda.max_memory_allocated()}
    del views
    if shared:
        del model
    else:
        del agent_a, agent_b
    gc.collect()
    torch.cuda.empty_cache()
    return result


def main():
    output = OUT / "replay-150/results.json"
    if output.exists():
        raise SystemExit("Refusing to overwrite an existing paired regression")
    digest = hashlib.sha256(Path(RAW_WINDOW_150_PATH).read_bytes()).hexdigest()
    if digest != EXPECTED_HASH:
        raise SystemExit("Frozen 150-message input fingerprint mismatch")
    manifest = json.loads((OUT / "manifest.json").read_text())
    if not manifest.get("offline_gate", {}).get("all_pass"):
        raise SystemExit("Offline dual-task parity did not pass; 150 regression not authorized")
    assert manifest["inputs"]["replay_150"]["sha256"] == digest
    events = [json.loads(line) for line in Path(RAW_WINDOW_150_PATH).open()]
    assert len(events) == 150
    with GpuLock(job_name="shared_backbone_paired_regression"):
        control = trial(events, shared=False)
        experiment = trial(events, shared=True)
    # The historical control is preserved as an additional consistency check.
    historical = json.loads((REF / "replay-150/replay_th50.json").read_text())
    same = [(a["eventId"], a["decision"], a["episodeId"]) for a in control["records"]] == [
        (x["eventId"], x["decision"], x["episodeId"]) for x in historical["records"]]
    result = {"input_sha256": digest, "threshold": 0.50,
              "runtime": "xtw_core.episode_router.p0.EpisodeRuntime + RefinedTwoStageRouter",
              "historical_control_exact_record_agreement": same,
              "control": control, "experiment": experiment}
    output.parent.mkdir(parents=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    (OUT / "efficiency/vram-latency.json").write_text(json.dumps({
        "measurement": "CUDA process allocated bytes; peak includes model load and replay; synchronized wall-clock timings",
        "control": {**control["efficiency"], **control["latency"]},
        "experiment": {**experiment["efficiency"], **experiment["latency"]}}, indent=2))
    print(f"Paired 150 replay: control {control['episodes']} episodes; shared {experiment['episodes']}; control historical consistency={same}")


if __name__ == "__main__":
    main()
