"""Laya Decision Model Training, Calibration, and Evaluation Engine.

Adheres strictly to:
- Official Laya DecisionModel architecture and checkpoint format (Section 6 & 7)
- Choice question formulation with option order permutation (Section 12 & 14)
- Temperature calibration strictly on DEV slice (Section 20)
- Evaluation metrics: Macro F1, False Continue, False New, Confusion Matrix (Section 21)
- Model health check & reload verification (Section 34)
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import safetensors.torch
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.optim import AdamW
from torch.optim.lr_scheduler import LambdaLR

# Add Laya package path
LAYA_PKG_PATH = "/home/longzhooou/.cache/uv-laya-alt/archive-v0/FX854Ga3GurRg6vZ"
if LAYA_PKG_PATH not in sys.path:
    sys.path.insert(0, LAYA_PKG_PATH)

import laya
from laya.common import (
    DecisionModel,
    TEMP_MAX,
    TEMP_MIN,
    clamp_temperature,
    answer_confidence,
    ece_score,
)
from memory.scripts.laya_training.data_loader import (
    LayaRoutingDataset,
    create_dataloader,
)
from memory.scripts.gpu_gate import GpuLock

TZ_CST = timezone(timedelta(hours=8))


def get_cosine_schedule_with_warmup(optimizer, num_warmup_steps: int, num_training_steps: int):
    def lr_lambda(current_step: int):
        if current_step < num_warmup_steps:
            return float(current_step) / float(max(1, num_warmup_steps))
        progress = float(current_step - num_warmup_steps) / float(max(1, num_training_steps - num_warmup_steps))
        return max(0.05, 0.5 * (1.0 + math.cos(math.pi * progress)))
    return LambdaLR(optimizer, lr_lambda)


def evaluate_laya(
    model: nn.Module,
    tok,
    cases_path: str,
    device: str = "cuda",
    batch_size: int = 16,
    temperature: float = 1.0,
) -> Dict[str, Any]:
    """Evaluates Laya on a dataset (DEV or TEST) and computes all routing metrics."""
    model.eval()
    dataloader = create_dataloader(
        cases_path,
        tok,
        batch_size=batch_size,
        shuffle=False,
        max_len=1024,
        head_max_len=256,
        permute_options=True,
    )

    all_preds_full = []
    all_gts_full = []
    all_probs = []
    total_loss = 0.0
    step_count = 0

    with torch.no_grad():
        for batch in dataloader:
            if batch is None:
                continue
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            marker_pos = batch["marker_pos"].to(device)
            marker_mask = batch["marker_mask"].to(device)
            qtype = batch["qtype"].to(device)
            labels = batch["label"].to(device)

            with torch.autocast(device_type="cuda" if "cuda" in device else "cpu", dtype=torch.bfloat16):
                logits, _ = model(input_ids, attention_mask, marker_pos, marker_mask, qtype)
                loss = F.cross_entropy(logits, labels)

            total_loss += loss.item()
            step_count += 1

            # Scaled probabilities
            scaled_logits = logits / max(0.1, temperature)
            scaled_probs = torch.softmax(scaled_logits, dim=-1).cpu().numpy()

            preds = torch.argmax(logits, dim=-1).cpu().tolist()
            gts = labels.cpu().tolist()

            for i, (pred_idx, gt_idx) in enumerate(zip(preds, gts)):
                meta = batch["meta"][i]
                ordered_keys = meta["ordered_keys"]
                pred_key = ordered_keys[pred_idx]
                gt_key = meta["target_key"]

                # Standardize category
                pred_cat = "CONTINUE" if pred_key.startswith("cand_") else pred_key
                gt_cat = "CONTINUE" if gt_key.startswith("cand_") else gt_key

                all_preds_full.append((pred_cat, pred_key))
                all_gts_full.append((gt_cat, gt_key))
                all_probs.append(scaled_probs[i, : len(ordered_keys)])

    total = len(all_preds_full)
    if total == 0:
        return {"error": "Empty evaluation set"}

    avg_loss = total_loss / max(1, step_count)
    correct = sum(1 for p, g in zip(all_preds_full, all_gts_full) if p[1] == g[1])
    accuracy = correct / total

    # Category breakdowns
    by_cat_total = Counter(g[0] for g in all_gts_full)
    by_cat_correct = Counter()
    confusion_matrix = Counter()
    pred_cat_counts = Counter(p[0] for p in all_preds_full)

    false_continue = 0  # GT is NEW/UNKNOWN, pred is CONTINUE
    false_new = 0       # GT is CONTINUE, pred is NEW
    unknown_misuse = 0

    for p, g in zip(all_preds_full, all_gts_full):
        confusion_matrix[(g[0], p[0])] += 1
        if p[1] == g[1]:
            by_cat_correct[g[0]] += 1
        if g[0] != "CONTINUE" and p[0] == "CONTINUE":
            false_continue += 1
        if g[0] == "CONTINUE" and p[0] == "NEW":
            false_new += 1
        if g[0] != "UNKNOWN" and p[0] == "UNKNOWN":
            unknown_misuse += 1

    f1_list = []
    category_metrics = {}
    for cat in ("CONTINUE", "NEW", "UNKNOWN"):
        c_gt = by_cat_total[cat]
        tp = by_cat_correct[cat]
        fp = sum(1 for p, g in zip(all_preds_full, all_gts_full) if p[0] == cat and p[1] != g[1])
        fn = sum(1 for p, g in zip(all_preds_full, all_gts_full) if g[0] == cat and p[1] != g[1])
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0
        f1_list.append(f1)
        category_metrics[cat] = {
            "total": c_gt,
            "correct": tp,
            "accuracy": round(tp / c_gt, 4) if c_gt > 0 else 0.0,
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
        }

    macro_f1 = sum(f1_list) / len(f1_list)
    cont_gt = by_cat_total["CONTINUE"]
    non_cont_gt = by_cat_total["NEW"] + by_cat_total["UNKNOWN"]

    return {
        "loss": round(avg_loss, 4),
        "total_cases": total,
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "category_metrics": category_metrics,
        "prediction_distribution": {
            k: round(pred_cat_counts[k] / total, 4) for k in ("CONTINUE", "NEW", "UNKNOWN")
        },
        "critical_errors": {
            "false_continue_count": false_continue,
            "false_continue_rate": round(false_continue / non_cont_gt, 4) if non_cont_gt > 0 else 0.0,
            "false_new_count": false_new,
            "false_new_rate": round(false_new / cont_gt, 4) if cont_gt > 0 else 0.0,
            "unknown_misuse_count": unknown_misuse,
            "unknown_misuse_rate": round(unknown_misuse / (cont_gt + by_cat_total["NEW"]), 4) if (cont_gt + by_cat_total["NEW"]) > 0 else 0.0,
        },
        "confusion_matrix": {
            f"actual_{g}_pred_{p}": count
            for (g, p), count in sorted(confusion_matrix.items())
        },
        "all_preds": [p[1] for p in all_preds_full],
        "all_gts": [g[1] for g in all_gts_full],
    }


def fit_temperature_scaling(model: nn.Module, tok, dev_path: str, device: str = "cuda") -> float:
    """Fits post-training temperature scaling strictly on the DEV slice."""
    model.eval()
    dataloader = create_dataloader(dev_path, tok, batch_size=16, shuffle=False)
    all_logits = []
    all_labels = []

    with torch.no_grad():
        for batch in dataloader:
            if batch is None:
                continue
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            marker_pos = batch["marker_pos"].to(device)
            marker_mask = batch["marker_mask"].to(device)
            qtype = batch["qtype"].to(device)
            labels = batch["label"].to(device)
            logits, _ = model(input_ids, attention_mask, marker_pos, marker_mask, qtype)
            all_logits.append(logits)
            all_labels.append(labels)

    logits_tensor = torch.cat(all_logits, dim=0)
    labels_tensor = torch.cat(all_labels, dim=0)

    # Optimize scalar temperature parameter T > 0
    T = nn.Parameter(torch.ones(1, device=device))
    optimizer = AdamW([T], lr=0.02)
    criterion = nn.CrossEntropyLoss()

    for _ in range(50):
        optimizer.zero_grad()
        loss = criterion(logits_tensor / T.clamp(min=0.1), labels_tensor)
        loss.backward()
        optimizer.step()

    fitted_t = clamp_temperature(T.item(), lo=TEMP_MIN, hi=TEMP_MAX)
    return round(float(fitted_t), 4)


def save_laya_checkpoint(
    model: nn.Module,
    tok,
    base_checkpoint_dir: str,
    output_dir: Path,
    temperature: float = 1.0,
    metrics: Optional[Dict[str, Any]] = None,
) -> Path:
    """Saves a fully loadable Laya decision model bundle."""
    output_dir.mkdir(parents=True, exist_ok=True)
    base_path = Path(base_checkpoint_dir)

    # 1. Save weights via safetensors
    state_dict = model.state_dict()
    # Update buffer temperature
    state_dict["temperature"] = torch.tensor([temperature, temperature, temperature], dtype=torch.float32)
    weights_path = output_dir / "model.safetensors"
    safetensors.torch.save_file(state_dict, str(weights_path))

    # 2. Save rl_agent_config.json
    base_cfg_path = base_path / "rl_agent_config.json"
    with open(base_cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["temperature"] = [temperature, temperature, temperature]
    cfg["model_name"] = f"laya-episode-routing-{output_dir.name}"
    if metrics:
        cfg["training_metrics"] = {
            "dev_accuracy": metrics.get("accuracy"),
            "dev_macro_f1": metrics.get("macro_f1"),
        }
    with open(output_dir / "rl_agent_config.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    # 3. Copy encoder and tokenizer directories
    encoder_src = base_path / "encoder"
    tokenizer_src = base_path / "tokenizer"
    encoder_dst = output_dir / "encoder"
    tokenizer_dst = output_dir / "tokenizer"

    if encoder_src.exists() and not encoder_dst.exists():
        shutil.copytree(str(encoder_src), str(encoder_dst))
    if tokenizer_src.exists() and not tokenizer_dst.exists():
        shutil.copytree(str(tokenizer_src), str(tokenizer_dst))

    return output_dir


def verify_checkpoint_reload(checkpoint_dir: Path, device: str = "cuda") -> bool:
    """Verifies that the saved checkpoint can be cleanly reloaded by laya.load and execute inference."""
    verify_script = f"""
import sys
sys.path.insert(0, {repr(LAYA_PKG_PATH)})
import laya

agent = laya.load({repr(str(checkpoint_dir))}, device={repr(device)})
q = {{
    'route': {{
        'type': 'choice',
        'instructions': '当前目标消息属于哪个 Episode？',
        'criteria': {{
            'cand_1': '话题: 迎新活动',
            'cand_2': '话题: 充电器购买',
            'NEW': '新话题',
            'UNKNOWN': '信息不足'
        }}
    }}
}}
res = agent.predict('测试消息', q)
assert 'answers' in res and 'route' in res['answers']
assert res['answers']['route']['choice'] in ('cand_1', 'cand_2', 'NEW', 'UNKNOWN')
print('VERIFY_SUCCESS')
"""
    res = subprocess.run(
        [sys.executable, "-c", verify_script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if "VERIFY_SUCCESS" in res.stdout:
        return True
    print(f"[RELOAD VERIFICATION FAILED]: {res.stderr}", file=sys.stderr)
    return False


def train_laya_run(
    run_id: str,
    base_checkpoint_dir: str,
    train_cases_path: str,
    dev_cases_path: str,
    output_base_dir: Path,
    epochs: int = 4,
    batch_size: int = 8,
    grad_accum_steps: int = 2,
    lr: float = 3e-5,
    device: str = "cuda",
) -> Dict[str, Any]:
    """Executes a single end-to-end training run with DEV evaluation, calibration, and health check."""
    start_time = time.time()
    run_dir = output_base_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logs_file = run_dir / "training_log.jsonl"

    print(f"\n=======================================================")
    print(f"Starting Run: {run_id} (Epochs={epochs}, Batch={batch_size}x{grad_accum_steps}, LR={lr})")
    print(f"Train Source: {train_cases_path}")
    print(f"=======================================================")

    # 1. Load initial agent and model
    agent = laya.load(base_checkpoint_dir, device="cpu")
    tok = agent.tok
    model = agent.model.to(device)

    # 2. Data loaders
    train_loader = create_dataloader(
        train_cases_path,
        tok,
        batch_size=batch_size,
        shuffle=True,
        max_len=1024,
        head_max_len=256,
        permute_options=True,
    )

    total_train_cases = len(train_loader.dataset)
    steps_per_epoch = len(train_loader)
    total_steps = (steps_per_epoch // grad_accum_steps) * epochs
    warmup_steps = max(5, int(0.10 * total_steps))

    print(f"Dataset Size: {total_train_cases:,} cases | {steps_per_epoch} batches/epoch | Total opt steps: {total_steps}")

    # 3. Optimizer & Scheduler
    no_decay = ["bias", "LayerNorm.weight", "final_norm.weight"]
    optimizer_grouped_parameters = [
        {
            "params": [p for n, p in model.named_parameters() if not any(nd in n for nd in no_decay)],
            "weight_decay": 0.01,
        },
        {
            "params": [p for n, p in model.named_parameters() if any(nd in n for nd in no_decay)],
            "weight_decay": 0.0,
        },
    ]
    optimizer = AdamW(optimizer_grouped_parameters, lr=lr)
    scheduler = get_cosine_schedule_with_warmup(optimizer, warmup_steps, total_steps)

    best_dev_f1 = -1.0
    best_checkpoint_dir = run_dir / "best-dev"
    history = []
    opt_step = 0

    peak_vram_mb = 0.0
    if torch.cuda.is_available() and "cuda" in device:
        torch.cuda.reset_peak_memory_stats()

    # 4. Training loop
    for epoch in range(1, epochs + 1):
        model.train()
        epoch_loss = 0.0
        batch_count = 0
        optimizer.zero_grad()

        for b_idx, batch in enumerate(train_loader):
            if batch is None:
                continue

            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            marker_pos = batch["marker_pos"].to(device)
            marker_mask = batch["marker_mask"].to(device)
            qtype = batch["qtype"].to(device)
            labels = batch["label"].to(device)

            with torch.autocast(device_type="cuda" if "cuda" in device else "cpu", dtype=torch.bfloat16):
                logits, _ = model(input_ids, attention_mask, marker_pos, marker_mask, qtype)
                loss = F.cross_entropy(logits, labels) / grad_accum_steps

            if torch.isnan(loss):
                raise RuntimeError(f"MODEL_COLLAPSE: NaN loss encountered in {run_id} at epoch {epoch}")

            loss.backward()
            epoch_loss += loss.item() * grad_accum_steps
            batch_count += 1

            if (b_idx + 1) % grad_accum_steps == 0 or (b_idx + 1) == len(train_loader):
                nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()
                opt_step += 1

        avg_train_loss = epoch_loss / max(1, batch_count)

        if torch.cuda.is_available() and "cuda" in device:
            current_peak = torch.cuda.max_memory_allocated() / (1024 * 1024)
            if current_peak > peak_vram_mb:
                peak_vram_mb = current_peak

        # Evaluate on DEV
        dev_res = evaluate_laya(model, tok, dev_cases_path, device=device)
        dev_f1 = dev_res["macro_f1"]
        dev_acc = dev_res["accuracy"]

        # Check for model collapse (all same prediction)
        pred_dist = dev_res["prediction_distribution"]
        if any(pct > 0.98 for pct in pred_dist.values()):
            print(f"WARNING: Potential model collapse detected on DEV: {pred_dist}")

        print(f"Epoch {epoch}/{epochs} | Train Loss: {avg_train_loss:.4f} | DEV Acc: {dev_acc*100:.2f}% | DEV Macro F1: {dev_f1:.4f} | Peak VRAM: {peak_vram_mb:.0f}MB")

        epoch_record = {
            "epoch": epoch,
            "train_loss": round(avg_train_loss, 4),
            "dev_accuracy": dev_acc,
            "dev_macro_f1": dev_f1,
            "dev_category_metrics": dev_res["category_metrics"],
            "dev_critical_errors": dev_res["critical_errors"],
            "learning_rate": scheduler.get_last_lr()[0],
            "peak_vram_mb": round(peak_vram_mb, 1),
        }
        history.append(epoch_record)
        with open(logs_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(epoch_record, ensure_ascii=False) + "\n")

        # Save best dev checkpoint
        if dev_f1 > best_dev_f1:
            best_dev_f1 = dev_f1
            save_laya_checkpoint(
                model, tok, base_checkpoint_dir, best_checkpoint_dir,
                temperature=1.0, metrics=dev_res
            )
            print(f"  -> Saved new best-dev checkpoint (Macro F1={dev_f1:.4f})")

    # 5. Fit temperature calibration on DEV using best model
    print("Fitting temperature scaling on DEV...")
    best_agent = laya.load(str(best_checkpoint_dir), device=device)
    fitted_temp = fit_temperature_scaling(best_agent.model, tok, dev_cases_path, device=device)
    print(f"Fitted DEV temperature: {fitted_temp}")

    # Re-save best checkpoint with calibrated temperature
    save_laya_checkpoint(
        best_agent.model, tok, base_checkpoint_dir, best_checkpoint_dir,
        temperature=fitted_temp, metrics=dev_res
    )

    # 6. Verify checkpoint reload
    print("Verifying checkpoint reload...")
    reload_ok = verify_checkpoint_reload(best_checkpoint_dir, device=device)
    assert reload_ok, f"Failed checkpoint reload test for {best_checkpoint_dir}"
    print("  -> Reload verification: PASS")

    # Evaluate best model on DEV with calibrated temperature
    final_dev_metrics = evaluate_laya(
        best_agent.model, tok, dev_cases_path, device=device, temperature=fitted_temp
    )

    runtime_sec = time.time() - start_time
    run_summary = {
        "run_id": run_id,
        "model_architecture": "laya-322m-multilingual",
        "train_cases_count": total_train_cases,
        "epochs": epochs,
        "runtime_seconds": round(runtime_sec, 2),
        "peak_vram_mb": round(peak_vram_mb, 1),
        "calibrated_temperature": fitted_temp,
        "best_dev_accuracy": final_dev_metrics["accuracy"],
        "best_dev_macro_f1": final_dev_metrics["macro_f1"],
        "dev_category_metrics": final_dev_metrics["category_metrics"],
        "dev_critical_errors": final_dev_metrics["critical_errors"],
        "dev_confusion_matrix": final_dev_metrics["confusion_matrix"],
        "checkpoint_dir": str(best_checkpoint_dir),
        "reload_verified": reload_ok,
        "history": history,
    }

    with open(run_dir / "run_summary.json", "w", encoding="utf-8") as f:
        json.dump(run_summary, f, ensure_ascii=False, indent=2)

    return run_summary
