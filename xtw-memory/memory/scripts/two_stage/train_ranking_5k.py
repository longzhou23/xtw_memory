#!/usr/bin/env python3
"""Train Ranking Judge B 5K on scaled multi-community dataset."""

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
from memory.scripts.two_stage.train_ranking_v02 import (
    format_ranking_item_semantic,
    format_ranking_item_weak,
    format_ranking_item_runtime_bank,
    RankingDevDataset,
    evaluate_ranking,
)

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.optim import AdamW
from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data import Dataset, DataLoader

import laya
from laya.common import collate_items

OUT_BASE = PROJECT_ROOT / "memory/benchmark-results/router-v0.2-dual-model-5k-scaling-v0.1"
RANKING_OUT = OUT_BASE / "training/ranking"
RANKING_OUT.mkdir(parents=True, exist_ok=True)
CKPT_DIR = RANKING_OUT / "checkpoint"
CKPT_DIR.mkdir(parents=True, exist_ok=True)

DATASET_FILE = OUT_BASE / "datasets/ranking-5k/ranking_train_5k.jsonl"


class Ranking5KDataset(Dataset):
    def __init__(self, data_file: Path, tok):
        self.items = []
        with open(data_file) as f:
            for line in f:
                r = json.loads(line)
                item = None
                if "packet" in r and "mapped" in r:
                    item = format_ranking_item_semantic(r["packet"], r["mapped"], tok, permute=True)
                elif "ground_truth" in r:
                    item = format_ranking_item_weak(r, tok, permute=True)
                elif "positive_episode_id" in r:
                    item = format_ranking_item_runtime_bank(r, tok, permute=True)

                if item is not None:
                    # If it's a runtime bank case, oversample 4x as in baseline recipe
                    if item.get("source") == "runtime_bank":
                        for _ in range(4):
                            self.items.append(item)
                    else:
                        self.items.append(item)

        print(f"Loaded {len(self.items)} Ranking 5K training cases.")
        rng = random.Random(42)
        rng.shuffle(self.items)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        return self.items[idx]


def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    assert device == "cuda", "CUDA required for Ranking 5K training."

    print("=== Training Ranking Judge B 5K (Dual-Model Scaling) ===")
    print(f"Base Checkpoint: {BASE_CHECKPOINT_DIR}")
    print(f"Training Dataset: {DATASET_FILE}")

    with GpuLock(job_name="judge_b_5k_train"):
        print("[GPU] Acquired exclusive GPU Lock.")
        agent = laya.load(BASE_CHECKPOINT_DIR, device=device)
        tok = agent.tok
        model = agent.model

        train_ds = Ranking5KDataset(DATASET_FILE, tok)
        dev_ds = RankingDevDataset(DEV_DATA_PATH, tok)

        print(f"Train Dataset: {len(train_ds)} cases")
        print(f"DEV Dataset: {len(dev_ds)} rankable cases")

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

        history = []
        best_epoch = None
        best_top1 = -1.0

        print(f"\nStarting Ranking 5K training: {epochs} epochs, LR={lr}, steps={total_steps}...")
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

                batch_losses = []

                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    logits, _ = model(input_ids, attention_mask, marker_pos, marker_mask, qtype)

                    for i, meta in enumerate(batch["meta"]):
                        k = len(meta["ordered_keys"])
                        item_logits = logits[i, :k]
                        target_idx = meta["label"]

                        ce = F.cross_entropy(item_logits.unsqueeze(0), torch.tensor([target_idx], device=device))

                        neg_indices = meta.get("negative_indices", [])
                        if neg_indices:
                            pos_logit = item_logits[target_idx]
                            neg_logits = item_logits[neg_indices]
                            rank_loss = torch.log1p(torch.exp(neg_logits - pos_logit)).mean()
                            item_loss = ce + 1.0 * rank_loss
                        else:
                            item_loss = ce

                        batch_losses.append(item_loss)

                    loss = torch.stack(batch_losses).mean()
                    scaled_loss = loss / grad_accum_steps

                scaled_loss.backward()
                epoch_loss += loss.item()

                if (step + 1) % grad_accum_steps == 0 or (step + 1) == len(train_loader):
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    optimizer.step()
                    scheduler.step()
                    optimizer.zero_grad()

            avg_train_loss = epoch_loss / len(train_loader)
            dev_metrics = evaluate_ranking(model, dev_loader, device=device)
            print(f"Epoch {epoch}/{epochs} | Train Loss: {avg_train_loss:.4f} | DEV Top-1: {dev_metrics['top1']*100:.2f}% | MRR: {dev_metrics['mrr']:.4f} | Hard-Neg Top-1: {dev_metrics['hard_negatives']['top1']*100:.2f}%")

            epoch_dir = RANKING_OUT / f"epoch-{epoch}"
            save_laya_checkpoint(
                model=model,
                tok=tok,
                base_checkpoint_dir=BASE_CHECKPOINT_DIR,
                output_dir=epoch_dir,
                metrics={"accuracy": dev_metrics["top1"], "mrr": dev_metrics["mrr"]},
            )

            if dev_metrics["top1"] > best_top1:
                best_top1 = dev_metrics["top1"]
                best_epoch = epoch

            history.append({
                "epoch": epoch,
                "train_loss": avg_train_loss,
                "dev_metrics": dev_metrics,
            })

        print(f"Ranking 5K training completed in {time.time()-t_start:.1f}s. Best Epoch: {best_epoch} with Top-1: {best_top1*100:.2f}%")

        # Final checkpoint is best epoch
        print(f"\nSelecting best epoch {best_epoch} as final Ranking 5K checkpoint...")
        best_dir = RANKING_OUT / f"epoch-{best_epoch}"
        import shutil
        if CKPT_DIR.exists():
            shutil.rmtree(CKPT_DIR)
        shutil.copytree(best_dir, CKPT_DIR)

        final_dev_metrics = history[best_epoch - 1]["dev_metrics"]
        result_payload = {
            "judge": "Judge B 5K — Ranking",
            "task": "Candidate Ranking (given CONTINUE)",
            "selected_epoch": best_epoch,
            "base_checkpoint_sha256": BASE_CHECKPOINT_SHA256,
            "dataset": {
                "file": str(DATASET_FILE),
                "total_cases": len(train_ds),
            },
            "dev_cases": {
                "rankable": 266,
                "hard_negative_cases": 258,
            },
            "final_dev_metrics": final_dev_metrics,
            "training_history": history,
        }

        with open(RANKING_OUT / "dev_metrics.json", "w", encoding="utf-8") as f:
            json.dump(result_payload, f, indent=2, ensure_ascii=False)

        # Save evaluation json
        with open(OUT_BASE / "evaluation/ranking.json", "w", encoding="utf-8") as f:
            json.dump(final_dev_metrics, f, indent=2, ensure_ascii=False)

        print("Saved ranking dev_metrics.json and evaluation/ranking.json successfully.")


if __name__ == "__main__":
    main()
