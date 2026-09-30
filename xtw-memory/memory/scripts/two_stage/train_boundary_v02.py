#!/usr/bin/env python3
"""Train Judge A v0.2 (Boundary Judge) with Multi-Community Semantic Expansion.

Task:
  Binary classification: NEW vs CONTINUE
  Dataset:
    TRAIN:
      - 822 existing CONTINUE + 123 existing TRUE_NEW
      - 889 multi-community CONTINUE + 376 multi-community TRUE_NEW
      Total: 1,711 CONTINUE, 499 TRUE_NEW (2,210 cases)
    DEV:
      - 274 CONTINUE + 27 TRUE_NEW (301 cases, natural distribution preserved)

Training Rules:
  - Base checkpoint: Frozen Laya 322M-20K (05688142b1501bb...)
  - 3 epochs, AdamW LR=1.5e-5, batch_size=8, grad_accum=2
  - Single run, no hyperparameter sweep
"""
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
    TRAIN_DATA_PATH,
    DEV_DATA_PATH,
)
from memory.scripts.gpu_gate import GpuLock
from memory.scripts.laya_training.trainer import save_laya_checkpoint

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.optim import AdamW
from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data import Dataset, DataLoader

import laya
from laya.common import build_sequence, collate_items, QTYPES

OUT_BASE = PROJECT_ROOT / "memory/benchmark-results/router-v0.2-small-scale-refinement-v0.1"
BOUNDARY_OUT = OUT_BASE / "boundary"
BOUNDARY_OUT.mkdir(parents=True, exist_ok=True)
CKPT_DIR = BOUNDARY_OUT / "checkpoint"
CKPT_DIR.mkdir(parents=True, exist_ok=True)

MULTI_COMMUNITY_FILE = OUT_BASE / "multi-community-semantic/multi_community_semantic_cases.jsonl"


def format_boundary_item(packet, mapped, tok, permute: bool = True):
    ctx_lines = [
        f"{m['participant_id']}: {m['text']}"
        for m in packet.get("prior_context", [])[-8:]
    ]
    t = packet["target"]
    reply_tag = f" (回复: {t['reply_to_message_id']})" if t.get("reply_to_message_id") else ""
    target_str = f"{t['participant_id']}: {t['text']}{reply_tag}"

    cands = mapped.get("candidates", [])
    if cands:
        cand_lines = []
        for i, c in enumerate(cands[:8]):
            recent = c.get("recent_messages", [])
            snip = " ; ".join(m["text"][:28] for m in recent[-2:]) if recent else c.get("summary", "")[:28]
            cand_lines.append(f"- 话题 {i+1}: {snip}")
        cand_section = f"\n[活跃候选话题]\n" + "\n".join(cand_lines)
    else:
        cand_section = ""

    state = f"[近期上下文]\n" + "\n".join(ctx_lines) + cand_section + f"\n[当前消息] {target_str}"

    q = {
        "t": "choice",
        "ins": "判断当前目标消息是开启独立新话题还是延续已有话题？",
        "crit": {
            "CONTINUE": "延续话题: 属于候选话题之一或群聊历史讨论",
            "NEW": "新话题: 开启完全独立的新讨论线程"
        }
    }

    keys = ["CONTINUE", "NEW"]
    case_id = packet["case_id"]
    if permute:
        seed = int(hashlib.md5(case_id.encode()).hexdigest()[:8], 16)
        order = [1, 0] if seed % 2 == 1 else [0, 1]
    else:
        order = [0, 1]

    ordered_keys = [keys[i] for i in order]

    semantic_label = mapped["semantic_label"]
    target_name = "CONTINUE" if semantic_label == "TRUE_CONTINUE" else "NEW"
    target_idx = ordered_keys.index(target_name)
    target_vec = [1.0 if i == target_idx else 0.0 for i in range(len(keys))]

    ids, markers = build_sequence(
        tok,
        state,
        q,
        max_len=1024,
        head_max_len=256,
        option_order=order,
        truncate_left=True,
    )

    return {
        "ids": ids,
        "markers": markers,
        "qtype": QTYPES["choice"],
        "target": target_vec,
        "label": target_idx,
        "case_id": case_id,
        "ordered_keys": ordered_keys,
        "semantic_label": semantic_label,
        "target_name": target_name,
    }


class BoundaryExpandedTrainDataset(Dataset):
    def __init__(self, existing_train_path, mc_file_path, tok):
        self.items = []
        # 1. Existing train cases
        with open(existing_train_path) as f:
            for line in f:
                r = json.loads(line)
                item = format_boundary_item(r["packet"], r["mapped"], tok, permute=True)
                self.items.append(item)

        existing_len = len(self.items)

        # 2. Multi-community cases
        with open(mc_file_path) as f:
            for line in f:
                r = json.loads(line)
                item = format_boundary_item(r["packet"], r["mapped"], tok, permute=True)
                self.items.append(item)

        print(f"Loaded {existing_len} existing train cases + {len(self.items)-existing_len} multi-community cases. Total: {len(self.items)}")

        # Deterministic shuffle
        rng = random.Random(42)
        rng.shuffle(self.items)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        return self.items[idx]


class BoundaryDevDataset(Dataset):
    def __init__(self, dev_path, tok):
        self.items = []
        with open(dev_path) as f:
            for line in f:
                r = json.loads(line)
                item = format_boundary_item(r["packet"], r["mapped"], tok, permute=True)
                self.items.append(item)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        return self.items[idx]


def evaluate_boundary(model, dataloader, device="cuda", threshold: float = 0.50):
    model.eval()
    all_preds = []
    all_targets = []
    all_probs_new = []

    with torch.no_grad():
        for batch in dataloader:
            if batch is None:
                continue
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            marker_pos = batch["marker_pos"].to(device)
            marker_mask = batch["marker_mask"].to(device)
            qtype = batch["qtype"].to(device)

            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                logits, _ = model(input_ids, attention_mask, marker_pos, marker_mask, qtype)

            for i, meta in enumerate(batch["meta"]):
                ordered_keys = meta["ordered_keys"]
                cont_idx = ordered_keys.index("CONTINUE")
                new_idx = ordered_keys.index("NEW")

                l_c = logits[i, cont_idx].item()
                l_n = logits[i, new_idx].item()

                probs = torch.softmax(torch.tensor([l_c, l_n], dtype=torch.float32), dim=-1).tolist()
                p_cont, p_new = probs[0], probs[1]

                pred_label = "NEW" if p_new >= threshold else "CONTINUE"
                target_label = meta["target_name"]

                all_preds.append(pred_label)
                all_targets.append(target_label)
                all_probs_new.append(p_new)

    cm = Counter()
    for p, t in zip(all_preds, all_targets):
        cm[(t, p)] += 1

    tp_new = cm[("NEW", "NEW")]
    fn_new = cm[("NEW", "CONTINUE")]  # False Continue: actual NEW, predicted CONTINUE
    fp_new = cm[("CONTINUE", "NEW")]  # False New: actual CONTINUE, predicted NEW
    tn_new = cm[("CONTINUE", "CONTINUE")]

    prec_new = tp_new / (tp_new + fp_new) if (tp_new + fp_new) > 0 else 0.0
    rec_new = tp_new / (tp_new + fn_new) if (tp_new + fn_new) > 0 else 0.0
    f1_new = 2 * prec_new * rec_new / (prec_new + rec_new) if (prec_new + rec_new) > 0 else 0.0

    tp_cont = tn_new
    fn_cont = fp_new
    fp_cont = fn_new
    prec_cont = tp_cont / (tp_cont + fp_cont) if (tp_cont + fp_cont) > 0 else 0.0
    rec_cont = tp_cont / (tp_cont + fn_cont) if (tp_cont + fn_cont) > 0 else 0.0
    f1_cont = 2 * prec_cont * rec_cont / (prec_cont + rec_cont) if (prec_cont + rec_cont) > 0 else 0.0

    macro_f1 = (f1_new + f1_cont) / 2.0
    accuracy = (tp_new + tp_cont) / len(all_targets) if all_targets else 0.0

    return {
        "threshold": threshold,
        "total_cases": len(all_targets),
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "true_new": {
            "total": tp_new + fn_new,
            "precision": prec_new,
            "recall": rec_new,
            "f1": f1_new,
        },
        "true_continue": {
            "total": tp_cont + fn_cont,
            "precision": prec_cont,
            "recall": rec_cont,
            "f1": f1_cont,
        },
        "false_continue": fn_new,
        "false_new": fp_new,
        "confusion_matrix": {
            "actual_NEW_pred_NEW": tp_new,
            "actual_NEW_pred_CONTINUE": fn_new,
            "actual_CONTINUE_pred_NEW": fp_new,
            "actual_CONTINUE_pred_CONTINUE": tn_new,
        }
    }


def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    assert device == "cuda", "CUDA required."

    print("=== Training Boundary Judge A v0.2 (Multi-Community Refinement) ===")
    print(f"Base Checkpoint: {BASE_CHECKPOINT_DIR}")

    with GpuLock(job_name="judge_a_v02_train"):
        print("[GPU] Acquired exclusive GPU Lock.")
        # Load agent and tokenizer
        agent = laya.load(BASE_CHECKPOINT_DIR, device=device)
        tok = agent.tok
        model = agent.model

        # Datasets
        train_ds = BoundaryExpandedTrainDataset(TRAIN_DATA_PATH, MULTI_COMMUNITY_FILE, tok)
        dev_ds = BoundaryDevDataset(DEV_DATA_PATH, tok)

        print(f"Train Dataset: {len(train_ds)} cases (1711 CONTINUE, 499 TRUE_NEW)")
        print(f"DEV Dataset: {len(dev_ds)} cases (274 CONTINUE, 27 TRUE_NEW natural)")

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

        epochs = 3
        batch_size = 8
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

        # Class weights: 1711 / 499 = 3.43
        class_weights = torch.tensor([1.0, 3.43], dtype=torch.float32, device=device)
        criterion = nn.CrossEntropyLoss(weight=class_weights)

        history = []
        best_epoch = None
        best_macro_f1 = -1.0

        print(f"\nStarting training: {epochs} epochs, LR={lr}, class_weights=[1.0, 3.43], total_steps={total_steps}...")
        t_start = time.time()
        for epoch in range(1, epochs + 1):
            model.train()
            epoch_loss = 0.0
            accum_loss = 0.0
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
                accum_loss += scaled_loss.item()
                epoch_loss += loss.item()

                if (step + 1) % grad_accum_steps == 0 or (step + 1) == len(train_loader):
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    optimizer.step()
                    scheduler.step()
                    optimizer.zero_grad()

            avg_train_loss = epoch_loss / len(train_loader)
            dev_metrics = evaluate_boundary(model, dev_loader, device=device)
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

        print(f"Training completed in {time.time()-t_start:.1f}s. Best Epoch: {best_epoch} with Macro F1: {best_macro_f1:.4f}")

        # Canonical checkpoint is best epoch
        print(f"\nSelecting best epoch {best_epoch} as final Judge A v0.2 checkpoint...")
        best_dir = BOUNDARY_OUT / f"epoch-{best_epoch}"
        import shutil
        if CKPT_DIR.exists():
            shutil.rmtree(CKPT_DIR)
        shutil.copytree(best_dir, CKPT_DIR)

        final_dev_metrics = history[best_epoch - 1]["dev_metrics"]
        result_payload = {
            "judge": "Judge A v0.2 — Boundary",
            "task": "NEW vs CONTINUE",
            "selected_epoch": best_epoch,
            "base_checkpoint_sha256": BASE_CHECKPOINT_SHA256,
            "train_cases": {
                "existing_continue": 822,
                "existing_true_new": 123,
                "multi_community_continue": 889,
                "multi_community_true_new": 376,
                "total_train_cases": len(train_ds),
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

        print("Saved boundary/dev_metrics.json successfully.")


if __name__ == "__main__":
    main()
