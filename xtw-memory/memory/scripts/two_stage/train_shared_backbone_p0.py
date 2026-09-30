#!/usr/bin/env python3
"""One frozen-recipe 2-epoch, single-seed shared Laya backbone P0.

Run only once. The manifest and input fingerprints are written before any
training; this command refuses to replace existing checkpoints/results.
"""

import hashlib
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from memory.scripts.two_stage.common import (  # sets the existing Laya environment
    BASE_CHECKPOINT_DIR, DEV_DATA_PATH, TRAIN_DATA_PATH,
)
from memory.scripts.gpu_gate import GpuLock
from memory.scripts.two_stage.shared_backbone_p0 import (
    from_boundary_checkpoint, parameter_audit, save_parts,
)
from memory.scripts.two_stage.train_boundary_v02 import (
    BoundaryDevDataset, BoundaryExpandedTrainDataset, evaluate_boundary,
)
from memory.scripts.two_stage.train_ranking_v02 import (
    RankingDevDataset, RankingRefinedTrainDataset, evaluate_ranking,
)

import torch
import torch.nn.functional as F
from torch import nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data import DataLoader
import laya
from laya.common import collate_items

OUT = ROOT / "memory/benchmark-results/router-v0.2-shared-backbone-p0"
REF = ROOT / "memory/benchmark-results/router-v0.2-small-scale-refinement-v0.1"
A_CKPT = REF / "boundary/checkpoint/model.safetensors"
B_CKPT = REF / "ranking/checkpoint/model.safetensors"
MULTI = REF / "multi-community-semantic/multi_community_semantic_cases.jsonl"
BANK = REF / "runtime-hard-negative-bank/runtime_hard_negatives.jsonl"
WEAK = ROOT / "memory/benchmark-results/laya-episode-routing-weak-silver-scaling-v0.2/data/train-5k.jsonl"
WINDOW = Path("/home/longzhooou/Documents/Programs/小天文设计素材/memory-demo/benchmark-results/real-episode-temporary-fabric-laya-20k-p0/raw-window.jsonl")
SEED = 42
EPOCHS = 2
BATCH_SIZE = 8
GRAD_ACCUM = 2  # one boundary + one ranking batch; final unmatched batches stay at fixed ratio
LR = 1.5e-5
WEIGHT_DECAY = 0.01
LAMBDA_BOUNDARY = 1.0
LAMBDA_RANKING = 1.0
CLASS_WEIGHTS = (1.0, 3.43)
BASELINE_MACRO = 0.6704723177979356
BASELINE_NEW_F1 = 0.391304347826087
BASELINE_TOP1 = 0.7218045112781954
BASELINE_MRR = 0.8246374865735767


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def loss_boundary(logits, meta, weights):
    rows = [torch.stack((logits[i, item["ordered_keys"].index("CONTINUE")],
                         logits[i, item["ordered_keys"].index("NEW")]))
            for i, item in enumerate(meta)]
    target = torch.tensor([int(item["target_name"] == "NEW") for item in meta], device=logits.device)
    return F.cross_entropy(torch.stack(rows), target, weight=weights)


def loss_ranking(logits, meta):
    losses = []
    for i, item in enumerate(meta):
        row = logits[i, :len(item["ordered_keys"])]
        positive = item["label"]
        ce = F.cross_entropy(row.unsqueeze(0), torch.tensor([positive], device=logits.device))
        negative = item.get("negative_indices", [])
        if negative:
            # Identical CE + 1.0 * log(1 + exp(neg - pos)) recipe to Judge B v0.2.
            ce = ce + F.softplus(row[negative] - row[positive]).mean()
        losses.append(ce)
    return torch.stack(losses).mean()


class TaskView(nn.Module):
    """Keep the original DEV evaluators and their option-order/threshold logic."""

    def __init__(self, model, task):
        super().__init__()
        self.model = model
        self.task = task

    def forward(self, input_ids, attention_mask, marker_pos, marker_mask, qtype):
        return self.model(input_ids, attention_mask, marker_pos, marker_mask, qtype, task=self.task), None


def metric_gate(b, r):
    checks = {
        "boundary_macro_f1": b["macro_f1"] >= BASELINE_MACRO - 0.03,
        "true_new_f1_noncatastrophic": b["true_new"]["f1"] >= BASELINE_NEW_F1 - 0.10,
        "ranking_top1": r["top1"] >= BASELINE_TOP1 - 0.03,
        "ranking_mrr": r["mrr"] >= BASELINE_MRR - 0.03,
    }
    return {"checks": checks, "all_pass": all(checks.values())}


def select_epoch(history):
    """Choose jointly, never maximize just one task or tune a threshold."""
    def balanced(entry):
        b, r = entry["boundary_dev"], entry["ranking_dev"]
        return min((b["macro_f1"] - BASELINE_MACRO) / 0.03,
                   (b["true_new"]["f1"] - BASELINE_NEW_F1) / 0.10,
                   (r["top1"] - BASELINE_TOP1) / 0.03,
                   (r["mrr"] - BASELINE_MRR) / 0.03)
    return max(history, key=lambda e: (e["gate"]["all_pass"], balanced(e)))["epoch"]


def manifest():
    inputs = {name: {"path": str(path), "sha256": sha(path)} for name, path in {
        "semantic_train": TRAIN_DATA_PATH, "semantic_dev": DEV_DATA_PATH,
        "multi_community": MULTI, "weak_train_5k": WEAK,
        "runtime_hard_negative_bank": BANK, "replay_150": WINDOW,
        "independent_boundary_checkpoint": A_CKPT,
        "independent_ranking_checkpoint": B_CKPT,
    }.items()}
    return {
        "goal_id": "router_v0_2_shared_backbone_p0",
        "status": "PREFLIGHT_FROZEN",
        "architecture": "one encoder and one shared contextual stack; separate boundary/ranking scalar option heads",
        "initialization": "Judge A refined trunk+boundary scorer; Judge B refined scorer only",
        "seed": SEED, "epochs": EPOCHS, "batch_size": BATCH_SIZE,
        "task_schedule": "alternate boundary/ranking until one loader exhausted, then finish remaining loader; no repeats",
        "task_ratio": "277 boundary batches : 254 ranking batches per epoch (actual counts verified at load)",
        "gradient_accumulation": GRAD_ACCUM,
        "lambda_boundary": LAMBDA_BOUNDARY, "lambda_ranking": LAMBDA_RANKING,
        "boundary_class_weights": CLASS_WEIGHTS,
        "ranking_pairwise_lambda": 1.0,
        "learning_rate": LR, "weight_decay": WEIGHT_DECAY,
        "gate": {"macro_f1_max_drop": 0.03, "new_f1_max_drop": 0.10,
                 "top1_max_drop": 0.03, "mrr_max_drop": 0.03},
        "data_warning": "Historical multi-community HIGH labels and 7 hard negatives have not been independently blind-adjudicated; this is architectural parity against the same limited data, not validated semantic gold.",
        "inputs": inputs,
    }


def main():
    if OUT.exists():
        raise SystemExit(f"Refusing to overwrite existing P0 experiment: {OUT}")
    # Freeze all choices/fingerprints *before* loading models or inspecting DEV.
    frozen = manifest()
    OUT.mkdir(parents=True)
    (OUT / "training").mkdir()
    (OUT / "evaluation").mkdir()
    (OUT / "efficiency").mkdir()
    (OUT / "manifest.json").write_text(json.dumps(frozen, indent=2, ensure_ascii=False))

    torch.manual_seed(SEED)
    random.seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    with GpuLock(job_name="router_shared_backbone_p0"):
        agent = laya.load(str(A_CKPT.parent), device="cuda")
        tokenizer = agent.tok
        model = from_boundary_checkpoint(agent.model, B_CKPT)
        del agent
        model.head_checkpointing = True  # same activation-saving mechanism as Laya; no change to model semantics
        counts = parameter_audit(model)
        (OUT / "efficiency/parameter-audit.json").write_text(json.dumps(counts, indent=2))
        b_train = BoundaryExpandedTrainDataset(TRAIN_DATA_PATH, MULTI, tokenizer)
        r_train = RankingRefinedTrainDataset(TRAIN_DATA_PATH, WEAK, BANK, tokenizer)
        b_dev = BoundaryDevDataset(DEV_DATA_PATH, tokenizer)
        r_dev = RankingDevDataset(DEV_DATA_PATH, tokenizer)
        assert len(b_train) == 2210 and len(r_train) == 2028
        assert len(b_dev) == 301 and len(r_dev) == 266
        collate = lambda items: collate_items([items], pad_id=tokenizer.pad_token_id)
        b_loader = DataLoader(b_train, batch_size=BATCH_SIZE, shuffle=True, collate_fn=collate)
        r_loader = DataLoader(r_train, batch_size=BATCH_SIZE, shuffle=True, collate_fn=collate)
        b_eval = DataLoader(b_dev, batch_size=16, shuffle=False, collate_fn=collate)
        r_eval = DataLoader(r_dev, batch_size=16, shuffle=False, collate_fn=collate)
        assert len(b_loader) == 277 and len(r_loader) == 254
        steps = math.ceil((len(b_loader) + len(r_loader)) / GRAD_ACCUM) * EPOCHS
        warmup = max(5, int(0.10 * steps))
        def rate(step):
            if step < warmup:
                return float(step) / float(max(1, warmup))
            progress = (step - warmup) / max(1, steps - warmup)
            return max(0.05, 0.5 * (1.0 + math.cos(math.pi * progress)))
        optimizer = AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
        scheduler = LambdaLR(optimizer, rate)
        weights = torch.tensor(CLASS_WEIGHTS, dtype=torch.float32, device="cuda")
        history = []
        with (OUT / "training/metrics.jsonl").open("w") as metrics:
            for epoch in range(1, EPOCHS + 1):
                model.train()
                b_iter, r_iter = iter(b_loader), iter(r_loader)
                totals = {"boundary": [], "ranking": []}
                optimizer.zero_grad(set_to_none=True)
                batch_index = 0
                # Fixed task schedule: B, R, ..., then whichever loader remains.
                for offset in range(max(len(b_loader), len(r_loader))):
                    for task, iterator, limit in (("boundary", b_iter, len(b_loader)),
                                                  ("ranking", r_iter, len(r_loader))):
                        if offset >= limit:
                            continue
                        batch = next(iterator)
                        args = [batch[key].to("cuda") for key in
                                ("input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype")]
                        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                            logits = model(*args, task=task)
                            loss = (loss_boundary(logits, batch["meta"], weights) if task == "boundary"
                                    else loss_ranking(logits, batch["meta"]))
                            coefficient = LAMBDA_BOUNDARY if task == "boundary" else LAMBDA_RANKING
                        (coefficient * loss / GRAD_ACCUM).backward()
                        totals[task].append(float(loss.detach()))
                        batch_index += 1
                        if batch_index % GRAD_ACCUM == 0 or batch_index == len(b_loader) + len(r_loader):
                            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                            optimizer.step()
                            scheduler.step()
                            optimizer.zero_grad(set_to_none=True)
                assert batch_index == len(b_loader) + len(r_loader)
                b_metrics = evaluate_boundary(TaskView(model, "boundary"), b_eval)
                r_metrics = evaluate_ranking(TaskView(model, "ranking"), r_eval)
                gate = metric_gate(b_metrics, r_metrics)
                record = {"epoch": epoch, "boundary_loss": sum(totals["boundary"]) / len(totals["boundary"]),
                          "ranking_loss": sum(totals["ranking"]) / len(totals["ranking"]),
                          "boundary_dev": b_metrics, "ranking_dev": r_metrics, "gate": gate}
                history.append(record)
                metrics.write(json.dumps(record, ensure_ascii=False) + "\n")
                metrics.flush()
                save_parts(model, OUT / "training" / f"epoch-{epoch}")
                print(f"Epoch {epoch}: B macro {b_metrics['macro_f1']:.4f}, NEW F1 {b_metrics['true_new']['f1']:.4f}; R top1 {r_metrics['top1']:.4f}, MRR {r_metrics['mrr']:.4f}; parity={gate['all_pass']}", flush=True)
        selected = select_epoch(history)
        selected_record = history[selected - 1]
        # Final model is the jointly selected epoch, not the best single-head epoch.
        from memory.scripts.two_stage.shared_backbone_p0 import load_parts
        load_parts(model, OUT / "training" / f"epoch-{selected}")
        save_parts(model, OUT / "model")
        (OUT / "evaluation/boundary.json").write_text(json.dumps(selected_record["boundary_dev"], indent=2))
        (OUT / "evaluation/ranking.json").write_text(json.dumps(selected_record["ranking_dev"], indent=2))
        frozen["status"] = "OFFLINE_EVALUATED"
        frozen["selected_epoch"] = selected
        frozen["offline_gate"] = selected_record["gate"]
        (OUT / "manifest.json").write_text(json.dumps(frozen, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
