#!/usr/bin/env python3
"""Zero-Trust Independent Inference Engine.

Strictly adheres to Spec v0.1 Section 17 & 18:
- Reads ONLY unlabeled input cases (strips any label fields if present).
- Loads checkpoint from disk in a fresh standalone process.
- Produces raw predictions without calculating metrics.
- Saves raw prediction records with latency.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List

import numpy as np
import torch

LAYA_PKG_PATH = "/home/longzhooou/.cache/uv-laya-alt/archive-v0/FX854Ga3GurRg6vZ"
if LAYA_PKG_PATH not in sys.path:
    sys.path.insert(0, LAYA_PKG_PATH)

import laya
from laya.common import build_sequence, collate_items, QTYPES
import random
import hashlib


def format_unlabeled_case(case: Dict[str, Any], tok, max_len: int = 1024, head_max_len: int = 256) -> Dict[str, Any]:
    """Formats an unlabeled case into a Laya sequence without reading ground truth."""
    # Build state from context and target
    ctx_lines = [
        f"{m['participant_id']}: {m['text']}"
        for m in case.get("recent_context", [])[-8:]
    ]
    t = case["target"]
    reply_tag = f" (回复: {t['reply_to_message_id']})" if t.get("reply_to_message_id") else ""
    target_str = f"{t['participant_id']}: {t['text']}{reply_tag}"
    state = f"[近期上下文]\n" + "\n".join(ctx_lines) + f"\n[当前消息] {target_str}"

    criteria = {}
    for cand in case.get("candidate_episodes", []):
        cand_id = cand["candidate_id"]
        c_snips = " ; ".join(m["text"][:28] for m in cand.get("messages", [])[-2:])
        criteria[cand_id] = f"延续话题: {c_snips}"

    criteria["NEW"] = "新话题: 开启完全独立的新讨论线程"
    criteria["UNKNOWN"] = "信息不足: 缺乏上下文、图片未展示或代词指代不明"

    keys = list(criteria.keys())

    # Deterministic option permutation based strictly on case_id
    seed = int(hashlib.md5(case["case_id"].encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    order = list(range(len(keys)))
    rng.shuffle(order)
    ordered_keys = [keys[i] for i in order]

    q = {
        "t": "choice",
        "ins": "当前目标消息属于哪个 Episode？",
        "crit": criteria,
    }

    ids, markers = build_sequence(
        tok,
        state,
        q,
        max_len=max_len,
        head_max_len=head_max_len,
        option_order=order,
        truncate_left=True,
    )

    return {
        "ids": ids,
        "markers": markers,
        "qtype": QTYPES["choice"],
        "case_id": case["case_id"],
        "ordered_keys": ordered_keys,
    }


def run_inference():
    parser = argparse.ArgumentParser(description="Zero-Trust Independent Inference")
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--cases-file", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--temperature", type=float, default=None)
    args = parser.parse_args()

    assert args.checkpoint_dir.exists(), f"Checkpoint not found: {args.checkpoint_dir}"
    assert args.cases_file.exists(), f"Cases file not found: {args.cases_file}"
    args.output_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"[ZERO-TRUST INFERENCE] Starting inference for {args.checkpoint_dir.name} on {args.cases_file.name}", flush=True)

    # 1. Load agent and config from disk
    agent = laya.load(str(args.checkpoint_dir), device=args.device)
    tok = agent.tok
    model = agent.model
    model.eval()

    # Temperature from config if not specified
    if args.temperature is None:
        temp_val = agent.cfg.get("temperature", [1.0])[0]
    else:
        temp_val = args.temperature

    # 2. Load cases and strip any labels
    unlabeled_cases = []
    with open(args.cases_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                raw = json.loads(line)
                # Strip ground_truth and labels to guarantee zero label reading
                clean_case = {k: v for k, v in raw.items() if k not in ("ground_truth", "label")}
                unlabeled_cases.append(clean_case)

    print(f"Loaded {len(unlabeled_cases):,} unlabeled cases.", flush=True)

    predictions = []
    total_time = 0.0

    # Process in batches
    for b_start in range(0, len(unlabeled_cases), args.batch_size):
        b_cases = unlabeled_cases[b_start : b_start + args.batch_size]
        items = [format_unlabeled_case(c, tok) for c in b_cases]

        # Collate items
        batch = collate_items([items], pad_id=tok.pad_token_id)
        input_ids = batch["input_ids"].to(args.device)
        attention_mask = batch["attention_mask"].to(args.device)
        marker_pos = batch["marker_pos"].to(args.device)
        marker_mask = batch["marker_mask"].to(args.device)
        qtype = batch["qtype"].to(args.device)

        if "cuda" in args.device and torch.cuda.is_available():
            torch.cuda.synchronize()
        t0 = time.perf_counter()

        with torch.no_grad():
            with torch.autocast(device_type="cuda" if "cuda" in args.device else "cpu", dtype=torch.bfloat16):
                logits, _ = model(input_ids, attention_mask, marker_pos, marker_mask, qtype)

        if "cuda" in args.device and torch.cuda.is_available():
            torch.cuda.synchronize()
        batch_latency_ms = (time.perf_counter() - t0) * 1000
        per_item_latency_ms = round(batch_latency_ms / len(items), 2)
        total_time += batch_latency_ms / 1000

        scaled_logits = logits / max(0.1, temp_val)
        probs = torch.softmax(scaled_logits, dim=-1).cpu().numpy()
        preds = torch.argmax(logits, dim=-1).cpu().tolist()

        for idx, (p_idx, item) in enumerate(zip(preds, items)):
            ordered_keys = item["ordered_keys"]
            pred_key = ordered_keys[p_idx]
            raw_scores = {
                k: round(float(probs[idx, i]), 4)
                for i, k in enumerate(ordered_keys)
            }
            predictions.append({
                "case_id": item["case_id"],
                "prediction": pred_key,
                "raw_scores": raw_scores,
                "latency_ms": per_item_latency_ms,
            })

    # Write output predictions
    with open(args.output_file, "w", encoding="utf-8") as f:
        for p in predictions:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"[ZERO-TRUST INFERENCE] Completed {len(predictions):,} cases in {total_time:.2f}s. Saved to {args.output_file.name}", flush=True)


if __name__ == "__main__":
    run_inference()
