#!/usr/bin/env python3
"""Orchestrator for Zero-Trust Fresh-Process Inferences and Controls."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[2]
PYTHON_EXEC = "/tmp/opencode/qwen-alt/venv/bin/python"

BASE_CKPT = Path("/home/longzhooou/.cache/hf-laya-alt/models--convaiinnovations--laya/snapshots/55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851/multilingual")
RUNS_DIR = PROJECT_DIR / "memory" / "benchmark-results" / "laya-episode-routing-weak-silver-scaling-v0.2" / "runs"
AUDIT_DIR = PROJECT_DIR / "memory" / "benchmark-results" / "laya-episode-routing-zero-trust-audit-v0.1"

DEV_CASES = PROJECT_DIR / "memory" / "judgment" / "v0.1.0" / "splits" / "dev.jsonl"
TEST_CASES = PROJECT_DIR / "memory" / "benchmarks" / "judgment" / "episode-routing-v0.1.0" / "test_benchmark.jsonl"
HOLDOUT_CASES = PROJECT_DIR / "memory" / "judgment" / "v0.1.0" / "splits" / "holdout.jsonl"


def run_cmd(cmd_list):
    print(f"Executing: {' '.join(str(x) for x in cmd_list)}")
    t0 = time.time()
    res = subprocess.run(cmd_list, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"FAILED: {res.stderr}", file=sys.stderr)
        sys.exit(1)
    print(f"Done in {time.time()-t0:.2f}s.")
    return res.stdout


def main():
    print("=== Zero-Trust Independent Evaluation Orchestrator ===")
    
    # Verify HOLDOUT is strictly untouched
    with open(HOLDOUT_CASES, "rb") as f:
        import hashlib
        h = hashlib.sha256(f.read()).hexdigest()
    assert h == "400caf54e3efff7832df1707341aaefe207af28d03533948b9f3f53b37def474", "HOLDOUT MODIFIED!"
    print("[HOLDOUT INVARIANT]: Strictly verified unchanged. SEALED.")

    pred_dir = AUDIT_DIR / "predictions"
    metrics_dir = AUDIT_DIR / "metrics"
    controls_dir = AUDIT_DIR / "controls"
    pred_dir.mkdir(parents=True, exist_ok=True)
    metrics_dir.mkdir(parents=True, exist_ok=True)
    controls_dir.mkdir(parents=True, exist_ok=True)

    inference_script = SCRIPT_DIR / "zero_trust_inference.py"
    scorer_script = SCRIPT_DIR / "zero_trust_score.py"
    gpu_gate_script = PROJECT_DIR / "memory" / "scripts" / "gpu_gate.py"

    tasks = [
        # 1. Negative Control: Base Model on DEV
        ("BASE", BASE_CKPT, DEV_CASES, pred_dir / "base_dev.jsonl", metrics_dir / "base_dev_metrics.json"),
        # 2. 5k on DEV
        ("5K", RUNS_DIR / "322m-5k" / "best-dev", DEV_CASES, pred_dir / "5k_dev.jsonl", metrics_dir / "5k_dev_metrics.json"),
        # 3. 10k on DEV
        ("10K", RUNS_DIR / "322m-10k" / "best-dev", DEV_CASES, pred_dir / "10k_dev.jsonl", metrics_dir / "10k_dev_metrics.json"),
        # 4. 20k on DEV
        ("20K", RUNS_DIR / "322m-20k" / "best-dev", DEV_CASES, pred_dir / "20k_dev.jsonl", metrics_dir / "20k_dev_metrics.json"),
        # 5. 5k on TEST_SILVER
        ("5K_TEST", RUNS_DIR / "322m-5k" / "best-dev", TEST_CASES, pred_dir / "5k_test.jsonl", metrics_dir / "5k_test_metrics.json"),
        # 6. 10k on TEST_SILVER
        ("10K_TEST", RUNS_DIR / "322m-10k" / "best-dev", TEST_CASES, pred_dir / "10k_test.jsonl", metrics_dir / "10k_test_metrics.json"),
        # 7. 20k on TEST_SILVER
        ("20K_TEST", RUNS_DIR / "322m-20k" / "best-dev", TEST_CASES, pred_dir / "20k_test.jsonl", metrics_dir / "20k_test_metrics.json"),
    ]

    all_results = {}

    for label, ckpt_dir, cases_file, pred_out, metric_out in tasks:
        print(f"\n--- Running Independent Inference: {label} ---")
        # Run inference in a completely fresh process through GPU gate
        cmd = [
            sys.executable, str(gpu_gate_script), "run", "--",
            PYTHON_EXEC, str(inference_script),
            "--checkpoint-dir", str(ckpt_dir),
            "--cases-file", str(cases_file),
            "--output-file", str(pred_out),
            "--device", "cuda",
            "--batch-size", "16",
        ]
        run_cmd(cmd)

        # Run independent scoring
        print(f"--- Scoring: {label} ---")
        score_cmd = [
            PYTHON_EXEC, str(scorer_script),
            "--predictions", str(pred_out),
            "--ground-truth", str(cases_file),
            "--output-json", str(metric_out),
        ]
        score_out = run_cmd(score_cmd)
        metrics = json.loads(metric_out.read_text())
        all_results[label] = metrics
        print(f"[{label} INDEPENDENT RESULT] Acc: {metrics['accuracy']*100:.2f}%, Macro F1: {metrics['macro_f1']:.4f}")

    # Save consolidated independent metrics
    with open(metrics_dir / "independent_metrics.json", "w") as f:
        json.dump(all_results, f, indent=2)

    print("\nAll independent fresh-process evaluations completed successfully.")


if __name__ == "__main__":
    main()
