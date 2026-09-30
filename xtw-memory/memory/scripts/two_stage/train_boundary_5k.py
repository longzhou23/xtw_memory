#!/usr/bin/env python3
"""Train Boundary Judge A 5K on scaled multi-community dataset."""

import hashlib
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from memory.scripts.two_stage.common import (
    BASE_CHECKPOINT_DIR,
    BASE_CHECKPOINT_SHA256,
    DEV_DATA_PATH,
)
from memory.scripts.gpu_gate import GpuLock
from memory.scripts.laya_training.trainer import save_laya_checkpoint
from memory.scripts.two_stage.train_boundary_v02 import (
    format_boundary_item,
    BoundaryDevDataset,
    evaluate_boundary,
)

import torch
import torch.nn as nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data import Dataset, DataLoader

import laya
from laya.common import collate_items

OUT_BASE = PROJECT_ROOT / "memory/benchmark-results/router-v0.2-dual-model-5k-scaling-v0.1"
BOUNDARY_OUT = OUT_BASE / "training/boundary"
BOUNDARY_OUT.mkdir(parents=True, exist_ok=True)
CKPT_DIR = BOUNDARY_OUT / "checkpoint"
CKPT_DIR.mkdir(parents=True, exist_ok=True)

DATASET_FILE = OUT_BASE / "datasets/boundary-5k/boundary_train_5k.jsonl"


class Boundary5KDataset(Dataset):
    def __init__(self, data_file: Path, tok):
        self.items = []
        with open(data_file) as f:
            for line in f:
                r = json.loads(line)
                item = format_boundary_item(r["packet"], r["mapped"], tok, permute=True)
                self.items.append(item)
        print(f"Loaded {len(self.items)} Boundary 5K training cases.")
        rng = random.Random(42)
        rng.shuffle(self.items)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        return self.items[idx]


def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    assert device == "cuda", "CUDA required for Boundary 5K training."

    print("=== Training Boundary Judge A 5K (Dual-Model Scaling) ===")
    print(f"Base Checkpoint: {BASE_CHECKPOINT_DIR}")
    print(f"Training Dataset: {DATASET_FILE}")

    with GpuLock(job_name="judge_a_5k_train"):
        print("[GPU] Acquired exclusive GPU Lock.")
        agent = laya.load(BASE_CHECKPOINT_DIR, device=device)
        tok = agent.tok
        model = agent.model

        train_ds = Boundary5KDataset(DATASET_FILE, tok)
        dev_ds = BoundaryDevDataset(DEV_DATA_PATH, tok)

        print(f"Train Dataset: {len(train_ds)} cases")
        print(f"DEV Dataset: {len(dev_ds)} cases (natural distribution)")

        train_loader = DataLoader(
            train_ds,
            batch_size=8,
            shuffle=True,
            collate_fn=lambda items: collate_items([items], pad_id=tok.pad_token_id),
        )
        dev_loader = DataLoader(
            dev_ds,
            batch_size=16,
            shuffle=False,
            collate_fn=lambda items: collate_items([items], pad_id=tok.pad_token_id),
        )

        epochs = 2
        grad_accum_steps = 2
        lr = 1.5e-5

        optimizer = AdamW(model.parameters(), lr=lr, weight_decay=0.01)
        total_steps = (len(train_loader) // grad_accum_steps) * epochs
        warmup_steps = max(5, int(0.10 * total_steps))

        def lr_lambda(step):
            if step < warmup_steps:
                return float(step) / float(max(1, warmup_steps))
            progress = float(step - warmup_steps) / float(max(1, total_steps - warmup_steps))
            return max(0.05, 0.5 * (1.0 + torch.cos(torch.tensor(3.1415926535 * progress)).item()))

        scheduler = LambdaLR(optimizer, lr_lambda)

        # Baseline Boundary recipe class weights: [1.0, 3.43]
        class_weights = torch.tensor([1.0, 3.43], dtype=torch.float32, device=device)
        criterion = nn.CrossEntropyLoss(weight=class_weights)

        history = []
        best_epoch = None
        best_macro_f1 = -1.0

        print(f"\nStarting Boundary 5K training: {epochs} epochs, LR={lr}, class_weights=[1.0, 2.58], total_steps={total_steps}...")
        t_start = time.time()
        for epoch in range(1, epochs + 1):
            model.train()
            epoch_loss = 0.0
            optimizer.zero_grad()

            for step, batch in enumerate(train_loader):
                if batch is None:
                    continue
                input_ids = batch["input_ids"].to(device)
                attention_mask = batch["attention_mask"].to(device)
                marker_pos = batch["marker_pos"].to(device)
                marker_mask = batch["marker_mask"].to(device)
                qtype = batch["qtype"].to(device)

                canonical_targets = []
                canonical_logits_list = []

                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    logits, _ = model(input_ids, attention_mask, marker_pos, marker_mask, qtype)

                    for i, meta in enumerate(batch["meta"]):
                        ordered_keys = meta["ordered_keys"]
                        c_idx = ordered_keys.index("CONTINUE")
                        n_idx = ordered_keys.index("NEW")

                        l_c = logits[i, c_idx]
                        l_n = logits[i, n_idx]
                        canonical_logits_list.append(torch.stack([l_c, l_n]))

                        target_class = 0 if meta["target_name"] == "CONTINUE" else 1
                        canonical_targets.append(target_class)

                    batch_logits = torch.stack(canonical_logits_list)
                    batch_targets = torch.tensor(canonical_targets, dtype=torch.long, device=device)

                    loss = criterion(batch_logits, batch_targets)
                    scaled_loss = loss / grad_accum_steps

                scaled_loss.backward()
                epoch_loss += loss.item()

                if (step + 1) % grad_accum_steps == 0 or (step + 1) == len(train_loader):
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    optimizer.step()
                    scheduler.step()
                    optimizer.zero_grad()

            avg_train_loss = epoch_loss / len(train_loader)
            dev_metrics = evaluate_boundary(model, dev_loader, device=device, threshold=0.50)
            print(f"Epoch {epoch}/{epochs} | Train Loss: {avg_train_loss:.4f} | DEV Acc: {dev_metrics['accuracy']*100:.2f}% | DEV Macro F1: {dev_metrics['macro_f1']:.4f} | TRUE_NEW P/R/F1: {dev_metrics['true_new']['precision']:.4f}/{dev_metrics['true_new']['recall']:.4f}/{dev_metrics['true_new']['f1']:.4f} | False Continue: {dev_metrics['false_continue']}/27 | False New: {dev_metrics['false_new']}/274")

            epoch_dir = BOUNDARY_OUT / f"epoch-{epoch}"
            save_laya_checkpoint(
                model=model,
                tok=tok,
                base_checkpoint_dir=BASE_CHECKPOINT_DIR,
                output_dir=epoch_dir,
                metrics={"accuracy": dev_metrics["accuracy"], "macro_f1": dev_metrics["macro_f1"]},
            )

            if dev_metrics["macro_f1"] > best_macro_f1:
                best_macro_f1 = dev_metrics["macro_f1"]
                best_epoch = epoch

            history.append({
                "epoch": epoch,
                "train_loss": avg_train_loss,
                "dev_metrics": dev_metrics,
            })

        print(f"Boundary 5K training completed in {time.time()-t_start:.1f}s. Best Epoch: {best_epoch} with Macro F1: {best_macro_f1:.4f}")

        # Final checkpoint is best epoch
        print(f"\nSelecting best epoch {best_epoch} as final Boundary 5K checkpoint...")
        best_dir = BOUNDARY_OUT / f"epoch-{best_epoch}"
        import shutil
        if CKPT_DIR.exists():
            shutil.rmtree(CKPT_DIR)
        shutil.copytree(best_dir, CKPT_DIR)

        final_dev_metrics = history[best_epoch - 1]["dev_metrics"]
        result_payload = {
            "judge": "Judge A 5K — Boundary",
            "task": "NEW vs CONTINUE",
            "selected_epoch": best_epoch,
            "base_checkpoint_sha256": BASE_CHECKPOINT_SHA256,
            "dataset": {
                "file": str(DATASET_FILE),
                "total_cases": len(train_ds),
                "class_weights": [1.0, 3.43],
            },
            "dev_cases": {
                "continue": 274,
                "true_new": 27,
                "total": 301,
            },
            "final_dev_metrics": final_dev_metrics,
            "training_history": history,
        }

        with open(BOUNDARY_OUT / "dev_metrics.json", "w", encoding="utf-8") as f:
            json.dump(result_payload, f, indent=2, ensure_ascii=False)

        # Save evaluation json
        with open(OUT_BASE / "evaluation/boundary.json", "w", encoding="utf-8") as f:
            json.dump(final_dev_metrics, f, indent=2, ensure_ascii=False)

        print("Saved boundary dev_metrics.json and evaluation/boundary.json successfully.")


if __name__ == "__main__":
    main()
