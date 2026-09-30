#!/usr/bin/env python3
"""Train Judge B (Ranking Judge) for Router v0.2 Two-Stage Architecture.

Task:
  Given that an event continues an existing episode, select the correct Episode
  from active candidate Episodes.
  "Judge B 完全不负责 NEW 判断。"

Dataset:
  ~2k CONTINUE cases:
    - 822 high-confidence semantic CONTINUE cases (with mined hard negatives)
    - 1,178 weak CONTINUE cases from train-5k.jsonl
    Total: 2,000 cases.
  DEV:
    - 274 CONTINUE cases from dev.jsonl (266 rankable, 258 with hard negatives)

Metrics:
  - Top-1
  - MRR
  - Hard-negative Top-1

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

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from memory.scripts.two_stage.common import (
    BASE_CHECKPOINT_DIR,
    BASE_CHECKPOINT_SHA256,
    RESULTS_DIR,
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

WEAK_TRAIN_PATH = "/home/longzhooou/Documents/Programs/小天文设计素材/bot/projects/memory/benchmark-results/laya-episode-routing-weak-silver-scaling-v0.2/data/train-5k.jsonl"


def format_ranking_item_semantic(packet, mapped, tok, permute: bool = True):
    assert mapped["semantic_label"] == "TRUE_CONTINUE"
    pos_key = mapped.get("primary_positive_candidate_id")
    if not pos_key or not mapped.get("positive_available"):
        return None  # Unrankable

    ctx_lines = [
        f"{m['participant_id']}: {m['text']}"
        for m in packet.get("prior_context", [])[-8:]
    ]
    t = packet["target"]
    reply_tag = f" (回复: {t['reply_to_message_id']})" if t.get("reply_to_message_id") else ""
    target_str = f"{t['participant_id']}: {t['text']}{reply_tag}"
    state = f"[近期上下文]\n" + "\n".join(ctx_lines) + f"\n[当前消息] {target_str}"

    criteria = {}
    for c in mapped["candidates"]:
        recent = c.get("recent_messages", [])
        snip = " ; ".join(m["text"][:28] for m in recent[-2:]) if recent else c.get("summary", "")[:28]
        criteria[c["runtime_episode_id"]] = f"延续话题: {snip}"

    keys = list(criteria.keys())
    if pos_key not in keys:
        return None

    case_id = packet["case_id"]
    if permute:
        seed = int(hashlib.md5(case_id.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        order = list(range(len(keys)))
        rng.shuffle(order)
    else:
        order = list(range(len(keys)))

    ordered_keys = [keys[i] for i in order]
    target_idx = ordered_keys.index(pos_key)
    target_vec = [1.0 if i == target_idx else 0.0 for i in range(len(keys))]

    negatives = {c["runtime_episode_id"] for c in mapped["candidates"] if c.get("semantic_relation") == "NEGATIVE"}
    neg_indices = [i for i, k in enumerate(ordered_keys) if k in negatives]

    q = {
        "t": "choice",
        "ins": "当前目标消息延续哪个候选话题？",
        "crit": criteria,
    }

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
        "primary_positive": pos_key,
        "negative_indices": neg_indices,
        "hard_negative_present": mapped.get("hard_negative_present", False),
        "source": "semantic",
    }


def format_ranking_item_weak(r, tok, permute: bool = True):
    label = r.get("ground_truth", {}).get("label", "")
    if not label.startswith("CONTINUE:"):
        return None
    pos_key = label.split(":", 1)[1]

    cands = r.get("candidate_episodes", [])
    criteria = {}
    for c in cands:
        recent = c.get("messages", [])
        snip = " ; ".join(m["text"][:28] for m in recent[-2:]) if recent else ""
        criteria[c["candidate_id"]] = f"延续话题: {snip}"

    keys = list(criteria.keys())
    if pos_key not in keys:
        return None

    case_id = r["case_id"]
    if permute:
        seed = int(hashlib.md5(case_id.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        order = list(range(len(keys)))
        rng.shuffle(order)
    else:
        order = list(range(len(keys)))

    ordered_keys = [keys[i] for i in order]
    target_idx = ordered_keys.index(pos_key)
    target_vec = [1.0 if i == target_idx else 0.0 for i in range(len(keys))]

    ctx_lines = [
        f"{m['participant_id']}: {m['text']}"
        for m in r.get("recent_context", [])[-8:]
    ]
    t = r["target"]
    reply_tag = f" (回复: {t['reply_to_message_id']})" if t.get("reply_to_message_id") else ""
    target_str = f"{t['participant_id']}: {t['text']}{reply_tag}"
    state = f"[近期上下文]\n" + "\n".join(ctx_lines) + f"\n[当前消息] {target_str}"

    q = {
        "t": "choice",
        "ins": "当前目标消息延续哪个候选话题？",
        "crit": criteria,
    }

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
        "primary_positive": pos_key,
        "negative_indices": [],
        "hard_negative_present": False,
        "source": "weak",
    }


class RankingTrainDataset(Dataset):
    def __init__(self, semantic_path, weak_path, tok, target_total: int = 2000):
        self.items = []
        # 1. All semantic CONTINUE
        sem_count = 0
        with open(semantic_path) as f:
            for line in f:
                r = json.loads(line)
                if r["mapped"]["semantic_label"] == "TRUE_CONTINUE" and r["mapped"].get("positive_available"):
                    item = format_ranking_item_semantic(r["packet"], r["mapped"], tok, permute=True)
                    if item:
                        self.items.append(item)
                        sem_count += 1

        print(f"Loaded {sem_count} semantic CONTINUE cases with hard negatives")

        # 2. Add weak CONTINUE cases to reach target_total
        needed_weak = target_total - len(self.items)
        weak_count = 0
        with open(weak_path) as f:
            for line in f:
                if weak_count >= needed_weak:
                    break
                r = json.loads(line)
                item = format_ranking_item_weak(r, tok, permute=True)
                if item:
                    self.items.append(item)
                    weak_count += 1

        print(f"Loaded {weak_count} weak CONTINUE cases. Total training set: {len(self.items)}")

        # Deterministic shuffle
        rng = random.Random(42)
        rng.shuffle(self.items)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        return self.items[idx]


class RankingDevDataset(Dataset):
    def __init__(self, dev_path, tok):
        self.items = []
        self.total_continue = 0
        with open(dev_path) as f:
            for line in f:
                r = json.loads(line)
                if r["mapped"]["semantic_label"] == "TRUE_CONTINUE":
                    self.total_continue += 1
                    if r["mapped"].get("positive_available"):
                        item = format_ranking_item_semantic(r["packet"], r["mapped"], tok, permute=True)
                        if item:
                            self.items.append(item)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        return self.items[idx]


def evaluate_ranking(model, dataloader, device="cuda"):
    model.eval()
    top1_correct = 0
    top2_correct = 0
    mrr_sum = 0.0
    total_evaluated = 0

    hard_total = 0
    hard_top1_correct = 0

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
                k = len(meta["ordered_keys"])
                item_logits = logits[i, :k].float().cpu().tolist()
                target_idx = meta["label"]

                # Rank indices by logit descending
                ranked_indices = sorted(range(k), key=lambda idx: item_logits[idx], reverse=True)
                rank = ranked_indices.index(target_idx) + 1  # 1-based rank

                if rank == 1:
                    top1_correct += 1
                if rank <= 2:
                    top2_correct += 1
                mrr_sum += 1.0 / rank
                total_evaluated += 1

                if meta.get("hard_negative_present"):
                    hard_total += 1
                    if rank == 1:
                        hard_top1_correct += 1

    top1 = top1_correct / total_evaluated if total_evaluated > 0 else 0.0
    top2 = top2_correct / total_evaluated if total_evaluated > 0 else 0.0
    mrr = mrr_sum / total_evaluated if total_evaluated > 0 else 0.0
    hard_top1 = hard_top1_correct / hard_total if hard_total > 0 else 0.0

    return {
        "rankable_cases": total_evaluated,
        "top1": top1,
        "top2": top2,
        "mrr": mrr,
        "hard_negatives": {
            "total": hard_total,
            "top1": hard_top1,
        }
    }


def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    assert device == "cuda", "CUDA is required for Laya training."

    print("=== Training Router v0.2 Judge B (Ranking) ===")
    print(f"Base Checkpoint: {BASE_CHECKPOINT_DIR}")

    out_dir = Path(RESULTS_DIR) / "ranking"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir = out_dir / "checkpoint"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    with GpuLock(job_name="judge_b_ranking_train"):
        print("[GPU] Acquired exclusive GPU Lock.")
        # 1. Load agent and tokenizer
        agent = laya.load(BASE_CHECKPOINT_DIR, device=device)
        tok = agent.tok
        model = agent.model

        # 2. Datasets
        train_ds = RankingTrainDataset(TRAIN_DATA_PATH, WEAK_TRAIN_PATH, tok, target_total=2000)
        dev_ds = RankingDevDataset(DEV_DATA_PATH, tok)

        print(f"DEV dataset: {len(dev_ds)} rankable items (out of {dev_ds.total_continue} natural DEV CONTINUE)")

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

        # Baseline evaluation before training
        print("\nEvaluating base model on DEV before ranking training...")
        base_metrics = evaluate_ranking(model, dev_loader, device=device)
        print(f"Base DEV Top-1: {base_metrics['top1']*100:.2f}% | MRR: {base_metrics['mrr']:.4f} | Hard-Negative Top-1: {base_metrics['hard_negatives']['top1']*100:.2f}%")

        # 3. Training setup
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

        history = []
        global_step = 0
        best_epoch = None
        best_top1 = -1.0

        print(f"\nStarting training: {epochs} epochs, LR={lr}, steps={total_steps}...")
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

                batch_losses = []

                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    logits, _ = model(input_ids, attention_mask, marker_pos, marker_mask, qtype)

                    for i, meta in enumerate(batch["meta"]):
                        k = len(meta["ordered_keys"])
                        item_logits = logits[i, :k]
                        target_idx = meta["label"]

                        # Pointwise cross-entropy
                        ce = F.cross_entropy(item_logits.unsqueeze(0), torch.tensor([target_idx], device=device))

                        # Hard negative ranking loss if available
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
                accum_loss += scaled_loss.item()
                epoch_loss += loss.item()

                if (step + 1) % grad_accum_steps == 0 or (step + 1) == len(train_loader):
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    optimizer.step()
                    scheduler.step()
                    optimizer.zero_grad()
                    global_step += 1

            avg_train_loss = epoch_loss / len(train_loader)

            # Evaluate at epoch end
            dev_metrics = evaluate_ranking(model, dev_loader, device=device)
            print(f"Epoch {epoch}/{epochs} | Train Loss: {avg_train_loss:.4f} | DEV Top-1: {dev_metrics['top1']*100:.2f}% | MRR: {dev_metrics['mrr']:.4f} | Hard-Neg Top-1: {dev_metrics['hard_negatives']['top1']*100:.2f}%")

            epoch_dir = out_dir / f"epoch-{epoch}"
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

        print(f"Training completed in {time.time()-t_start:.1f}s. Best Epoch: {best_epoch} with Top-1: {best_top1*100:.2f}%")

        # Copy best epoch to checkpoint (canonical)
        print(f"\nSelecting best epoch {best_epoch} as final Judge B checkpoint...")
        best_dir = out_dir / f"epoch-{best_epoch}"
        import shutil
        if ckpt_dir.exists():
            shutil.rmtree(ckpt_dir)
        shutil.copytree(best_dir, ckpt_dir)

        # Save metrics
        final_dev_metrics = history[best_epoch - 1]["dev_metrics"]
        result_payload = {
            "judge": "Judge B — Ranking",
            "task": "Candidate Ranking (given CONTINUE)",
            "selected_epoch": best_epoch,
            "base_checkpoint_sha256": BASE_CHECKPOINT_SHA256,
            "train_cases": {
                "semantic_continue_hard_neg": 822,
                "weak_continue": 1178,
                "total": len(train_ds),
            },
            "dev_cases": {
                "natural_continue_total": dev_ds.total_continue,
                "rankable": len(dev_ds),
                "hard_negative_cases": dev_metrics["hard_negatives"]["total"],
            },
            "base_dev_metrics": base_metrics,
            "final_dev_metrics": final_dev_metrics,
            "training_history": history,
        }

        with open(out_dir / "dev_metrics.json", "w") as f:
            json.dump(result_payload, f, indent=2, ensure_ascii=False)

        print("\nJudge B dev_metrics.json saved successfully!")


if __name__ == "__main__":
    main()
