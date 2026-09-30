"""Independent, fixed-recipe TRUE_NEW causal control; never selects HNR.

Run exactly once for each arm (`zero`, `all-123`), in separate processes.
Original baseline, semantic TRAIN/DEV, and main HNR checkpoints are read-only.
The two arms differ ONLY in inclusion of the 123 TRUE_NEW TRAIN examples.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/home/longzhooou/.cache/uv-laya-alt/archive-v0/FX854Ga3GurRg6vZ")

import laya
import torch
from torch import nn
from torch.optim import AdamW
from memory.scripts.gpu_gate import GpuLock
from memory.scripts.laya_training import hnr_train_once as recipe
from memory.scripts.laya_training.data_loader import create_dataloader
from memory.scripts.laya_training.hnr_objective import weak_pointwise_loss
from memory.scripts.laya_training.trainer import (
    evaluate_laya, get_cosine_schedule_with_warmup, save_laya_checkpoint,
)
from memory.scripts.laya_training.hnr_source_preflight import file_sha256

OUT = recipe.RUN_ROOT / "evaluation/true-new-controlled-ablation"
HNR_HASH = "81f048e6186334253094ffdbcd73d30a7861387030ea60d59fcb508683ca504c"


def run(arm: str) -> None:
    assert arm in ("zero", "all-123")
    train_info, dev_info = recipe.verify_data()
    assert file_sha256(recipe.RUN_ROOT / "training/one-run/best-dev-ranking/model.safetensors") == HNR_HASH
    assert train_info["label_distribution"]["TRUE_CONTINUE"] == 822
    assert train_info["label_distribution"]["TRUE_NEW"] == 123
    output = OUT / arm
    assert not output.exists(), f"No overwrite / second lineage for {arm}"
    output.mkdir(parents=True, mode=0o700)
    with GpuLock(job_name=f"laya_true_new_ablation_{arm}"):
        # Seed BEFORE agent/optimizer creation and before each epoch. Both arms
        # start from exactly the same frozen base with the same weak stream.
        torch.manual_seed(1229)
        agent = laya.load(str(recipe.BASE), device="cpu")
        model, tok = agent.model.to("cuda"), agent.tok
        train = recipe.SemanticDataset(recipe.SILVER / "train.jsonl", tok, train=True)
        if arm == "zero":
            train.rows = [r for r in train.rows if r["mapped"]["semantic_label"] != "TRUE_NEW"]
        counts = Counter(r["mapped"]["semantic_label"] for r in train.rows)
        continuation_ids = [r["mapped"]["case_id"] for r in train.rows
                            if r["mapped"]["semantic_label"] == "TRUE_CONTINUE"]
        continue_fingerprint = hashlib.sha256(json.dumps(continuation_ids).encode()).hexdigest()
        effective_fingerprint = hashlib.sha256(json.dumps(
            [(r["mapped"]["case_id"], r["mapped"]["semantic_label"]) for r in train.rows]
        ).encode()).hexdigest()
        assert counts == ({"TRUE_CONTINUE": 822} if arm == "zero" else
                          {"TRUE_CONTINUE": 822, "TRUE_NEW": 123})
        dev = recipe.SemanticDataset(recipe.SILVER / "dev.jsonl", tok, train=False)
        dev_loader = recipe.sem_loader(dev, tok, shuffle=False, seed=46)
        weak = create_dataloader(str(recipe.WEAK_TRAIN), tok, batch_size=recipe.BATCH_SIZE, shuffle=True)
        total_batches = math.ceil(len(weak) * 1.5) * recipe.EPOCHS
        total_steps = math.ceil(total_batches / recipe.GRAD_ACCUM)
        no_decay = ("bias", "LayerNorm.weight", "final_norm.weight")
        grouped = [
            {"params": [p for n, p in model.named_parameters() if not any(k in n for k in no_decay)], "weight_decay": 0.01},
            {"params": [p for n, p in model.named_parameters() if any(k in n for k in no_decay)], "weight_decay": 0.0},
        ]
        opt = AdamW(grouped, lr=recipe.LR)
        scheduler = get_cosine_schedule_with_warmup(opt, max(5, int(.10 * total_steps)), total_steps)
        for epoch in range(1, recipe.EPOCHS + 1):
            model.train()
            torch.manual_seed(1229 + epoch)
            sem_iter = iter(recipe.sem_loader(train, tok, shuffle=True, seed=1229 + epoch))
            weak_count = sem_count = exposure = accum = 0
            opt.zero_grad()
            for weak_batch in weak:
                # Same weak:semantic 2:1 cycle and identical total steps.
                batches = [(weak_batch, False)]
                if (weak_count + 1) % 2 == 0:
                    try:
                        semantic_batch = next(sem_iter)
                    except StopIteration:
                        sem_iter = iter(recipe.sem_loader(train, tok, shuffle=True,
                                                          seed=1229 + epoch + sem_count + 1))
                        semantic_batch = next(sem_iter)
                    batches.append((semantic_batch, True))
                    sem_count += 1
                for batch, semantic in batches:
                    with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                        logits = recipe.model_forward(model, batch, "cuda")
                        if semantic:
                            loss, _, _ = recipe.semantic_batch_losses(logits, batch)
                            exposure += len(batch["meta"])
                        else:
                            loss = weak_pointwise_loss(logits, batch["label"].to("cuda"))
                    assert torch.isfinite(loss), "Nonfinite ablation loss"
                    (loss / recipe.GRAD_ACCUM).backward()
                    accum += 1
                    if accum % recipe.GRAD_ACCUM == 0:
                        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                        opt.step()
                        scheduler.step()
                        opt.zero_grad()
                weak_count += 1
            if accum % recipe.GRAD_ACCUM:
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                scheduler.step()
                opt.zero_grad()
            checkpoint = output / f"epoch-{epoch}"
            save_laya_checkpoint(model, tok, str(recipe.BASE), checkpoint, temperature=1.7958)
            record = {"arm": arm, "epoch": epoch, "train_counts": dict(counts),
                      "weak_batches": weak_count, "semantic_batches": sem_count,
                      "semantic_exposure": exposure, "optimizer_steps": math.ceil(accum / recipe.GRAD_ACCUM),
                      "checkpoint_sha256": file_sha256(checkpoint / "model.safetensors"),
                      "weak_dev_macro_f1": evaluate_laya(model, tok, str(recipe.WEAK_DEV), device="cuda", temperature=1.7958)["macro_f1"],
                      "semantic_dev": recipe.semantic_dev_metrics(model, dev_loader, "cuda", temperature=1.7958),
                      "frozen_base_sha256": recipe.BASE_SHA, "semantic_train_sha256": train_info["silver_sha256"],
                      "effective_train_case_fingerprint": effective_fingerprint,
                      "continuation_case_fingerprint": continue_fingerprint,
                      "semantic_dev_sha256": dev_info["silver_sha256"],
                      "weak_train_sha256": file_sha256(recipe.WEAK_TRAIN),
                      "policy": "3 epochs; AdamW LR=1.5e-5; rank lambda=1; 2 weak:1 semantic; batch=8; grad accum=2; deterministic epoch seed=1229+epoch; no checkpoint selection"}
            with (output / "training-log.jsonl").open("a") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(json.dumps(record, ensure_ascii=False), flush=True)
        assert file_sha256(recipe.RUN_ROOT / "training/one-run/best-dev-ranking/model.safetensors") == HNR_HASH


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=("zero", "all-123"), required=True)
    run(parser.parse_args().arm)
