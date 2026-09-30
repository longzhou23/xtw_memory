#!/usr/bin/env python3
"""Isolated efficiency microbenchmark; never runs the 150 regression set.

This remains permitted when offline parity fails: measurement cannot be used
for checkpoint selection, threshold tuning, or claims of routing quality.
"""

import copy
import gc
import json
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "xtw-playground"))

from memory.scripts.two_stage.common import BASE_CHECKPOINT_DIR  # Laya env
from memory.scripts.gpu_gate import GpuLock
from memory.scripts.two_stage.run_refined_replay import RefinedTwoStageRouter
from memory.scripts.two_stage.shared_backbone_p0 import (
    SharedBackboneDualHead, load_parts, parameter_audit,
)

import laya
import torch
from torch import nn
from xtw_core.episode_router.p0 import EpisodeEvent, EpisodeRouterConfig, EpisodeStore, build_candidates

OUT = ROOT / "memory/benchmark-results/router-v0.2-shared-backbone-p0"
REF = ROOT / "memory/benchmark-results/router-v0.2-small-scale-refinement-v0.1"


class TaskView(nn.Module):
    def __init__(self, shared, task):
        super().__init__()
        self.shared = shared
        self.task = task

    def forward(self, input_ids, attention_mask, marker_pos, marker_mask, qtype):
        return self.shared(input_ids, attention_mask, marker_pos, marker_mask, qtype, task=self.task), None


def scenario():
    """Synthetic, non-private two-candidate event; no memory or replay input."""
    config = EpisodeRouterConfig()
    store = EpisodeStore(config)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    e0 = EpisodeEvent("synthetic-a", now, "p1", "甲", "今晚想在附近喝奶茶", None, ())
    e1 = EpisodeEvent("synthetic-b", now + timedelta(seconds=2), "p2", "乙", "茶馆里有几个空位", None, ())
    store.create_episode(e0)
    store.create_episode(e1)
    event = EpisodeEvent("synthetic-target", now + timedelta(seconds=3), "p3", "丙", "那个茶馆还开着吗？", None, ())
    assert len(build_candidates(event, store, config)) >= 2
    return store, config, event, (e0, e1)


def timed(call):
    torch.cuda.synchronize()
    start = time.perf_counter()
    call()
    torch.cuda.synchronize()
    return (time.perf_counter() - start) * 1000


def run_arm(shared):
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    if shared:
        agent = laya.load(str(REF / "boundary/checkpoint"), device="cuda")
        tok = agent.tok
        base = agent.model
        model = SharedBackboneDualHead(base.encoder, base.head, base.type_emb,
                                       base.scorer, copy.deepcopy(base.scorer)).cuda()
        del base, agent
        load_parts(model, OUT / "model")
        model.eval()
        a, b = TaskView(model, "boundary"), TaskView(model, "ranking")
        tok_a = tok_b = tok
        counts = parameter_audit(model)
    else:
        agent_a = laya.load(str(REF / "boundary/checkpoint"), device="cuda")
        agent_b = laya.load(str(REF / "ranking/checkpoint"), device="cuda")
        a, b = agent_a.model.eval(), agent_b.model.eval()
        tok_a, tok_b = agent_a.tok, agent_b.tok
        counts = {"total_unique": sum(p.numel() for p in a.parameters())
                  + sum(p.numel() for p in b.parameters())}
    torch.cuda.empty_cache()
    idle = torch.cuda.memory_allocated()
    store, config, event, context = scenario()
    router = RefinedTwoStageRouter(store, a, tok_a, b, tok_b,
                                   config=config, boundary_threshold=0.50, device="cuda")
    candidates = build_candidates(event, store, config)
    duration = {"boundary_ms": [], "ranking_ms": [], "router_decision_ms": []}
    with torch.no_grad():
        for i in range(30):
            times = {
                "boundary_ms": timed(lambda: router._evaluate_judge_a(event, candidates, context)),
                "ranking_ms": timed(lambda: router._evaluate_judge_b(event, candidates, context)),
                "router_decision_ms": timed(lambda: router.route(event, local_context=context)),
            }
            if i >= 5:  # same fixed warmup for both arms
                for key, value in times.items():
                    duration[key].append(value)
    result = {
        "params": counts["total_unique"],
        "idle_allocated_vram_bytes": idle,
        "peak_allocated_vram_bytes": torch.cuda.max_memory_allocated(),
        "latency_median_ms": {key: statistics.median(values) for key, values in duration.items()},
    }
    del router, a, b
    if shared:
        del model
    else:
        del agent_a, agent_b
    gc.collect()
    torch.cuda.empty_cache()
    return result


def main():
    path = OUT / "efficiency/vram-latency.json"
    if path.exists():
        raise SystemExit(f"Refusing to overwrite benchmark: {path}")
    manifest = json.loads((OUT / "manifest.json").read_text())
    if manifest.get("status") != "OFFLINE_EVALUATED":
        raise SystemExit("Run only after the single joint training and DEV evaluation")
    with GpuLock(job_name="shared_p0_efficiency_only"):
        control = run_arm(False)
        experiment = run_arm(True)
    control_size = sum((REF / stage / "checkpoint/model.safetensors").stat().st_size
                       for stage in ("boundary", "ranking"))
    shared_size = sum(p.stat().st_size for p in (OUT / "model").glob("*/model.safetensors"))
    result = {
        "measurement_type": "synthetic one-event microbenchmark, NOT 150-message regression",
        "device": "CUDA; process memory_allocated, excludes CUDA context and unrelated GPU processes",
        "sample_count": 25, "warmup_count": 5,
        "same_prompt_and_synthetic_candidate_store": True,
        "checkpoint_bytes": {"independent": control_size, "shared": shared_size},
        "independent": control, "shared": experiment,
    }
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
