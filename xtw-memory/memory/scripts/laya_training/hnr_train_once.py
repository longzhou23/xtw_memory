"""One-lineage HNR continuation from the frozen 20K checkpoint.

Guarded entry point: requires reviewed TRAIN/DEV silver and never accepts a
HOLDOUT path. Smoke is a separate engineering mode, not a performance run.
No hyperparameter overrides or retry-on-metric behavior.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/home/longzhooou/.cache/uv-laya-alt/archive-v0/FX854Ga3GurRg6vZ")

import laya
import torch
from torch import nn
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset
from laya.common import collate_items

from memory.scripts.gpu_gate import GpuLock
from memory.scripts.laya_training.data_loader import create_dataloader
from memory.scripts.laya_training.hnr_objective import semantic_case_loss, weak_pointwise_loss
from memory.scripts.laya_training.hnr_semantic_loader import to_laya_semantic_item
from memory.scripts.laya_training.trainer import (
    evaluate_laya, get_cosine_schedule_with_warmup, save_laya_checkpoint, verify_checkpoint_reload,
)
from memory.scripts.laya_training.hnr_source_preflight import file_sha256


BASE = ROOT / "memory/benchmark-results/laya-episode-routing-weak-silver-scaling-v0.2/runs/322m-20k/best-dev"
BASE_SHA = "05688142b1501bb193253f1bbd5947f8fa7e91d9db2cdcf4ea3215d73d53fcfc"
WEAK_TRAIN = ROOT / "memory/benchmark-results/laya-episode-routing-weak-silver-scaling-v0.2/data/train-20k.jsonl"
WEAK_DEV = ROOT / "memory/judgment/v0.1.0/splits/dev.jsonl"
RUN_ROOT = ROOT / "memory/benchmark-results/laya-episode-routing-hard-negative-ranking-v0.1"
SILVER = RUN_ROOT / "dataset/semantic-hard-negative-silver-v0.1"
RECIPE_SHA = "71775a153505972750873cb46eaf964c850733dab7a9910fd277c8e63636c231"
EPOCHS, BATCH_SIZE, GRAD_ACCUM, LR = 3, 8, 2, 1.5e-5
WEAK_DEV_F1_GUARD = 0.6467


class SemanticDataset(Dataset):
    def __init__(self, path: Path, tok, *, train: bool) -> None:
        with path.open() as stream:
            self.rows = [json.loads(line) for line in stream]
        self.tok, self.train = tok, train
        assert all(row["mapped"]["window"] in (("TRAIN",) if train else ("DEV",)) for row in self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, i: int) -> dict:
        row = self.rows[i]
        item = to_laya_semantic_item(row["packet"], row["mapped"], self.tok, allow_missing=not self.train)
        item["hard_negative_present"] = row["mapped"].get("hard_negative_present", False)
        item["candidate_count_unmined"] = row["mapped"]["candidate_count_unmined"]
        return item


def sem_loader(dataset: SemanticDataset, tok, *, shuffle: bool, seed: int) -> DataLoader:
    gen = torch.Generator().manual_seed(seed)
    return DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=shuffle, generator=gen,
                      collate_fn=lambda items: collate_items([items], pad_id=tok.pad_token_id))


def model_forward(model, batch: dict, device: str) -> torch.Tensor:
    logits, _ = model(*(batch[k].to(device) for k in
                        ("input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype")))
    return logits


def semantic_batch_losses(logits: torch.Tensor, batch: dict) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    totals, points, ranks = [], [], []
    for i, meta in enumerate(batch["meta"]):
        width = len(meta["ordered_keys"])
        total, point, rank = semantic_case_loss(
            logits[i, :width], label=meta["semantic_label"],
            primary_positive=meta["primary_positive_index"],
            other_positives=tuple(meta["other_positive_indices"]),
            negative_indices=tuple(meta["negative_indices"]), new_index=meta["new_index"],
        )
        totals.append(total)
        points.append(point)
        ranks.append(rank)
    return torch.stack(totals).mean(), torch.stack(points).mean(), torch.stack(ranks).mean()


@torch.no_grad()
def semantic_dev_metrics(model, loader: DataLoader, device: str, *, temperature: float) -> dict:
    model.eval()
    counts: Counter[str] = Counter()
    new_eligible = 0
    score_max = []
    reciprocal = 0.0
    hard_total = hard_correct = 0
    for batch in loader:
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            logits = model_forward(model, batch, device)
        for i, meta in enumerate(batch["meta"]):
            width = len(meta["ordered_keys"])
            keys = meta["ordered_keys"]
            probs = torch.softmax(logits[i, :width] / temperature, dim=-1).float().cpu().tolist()
            cands = [(key, probs[j]) for j, key in enumerate(keys) if key not in ("NEW", "UNKNOWN")]
            cands.sort(key=lambda x: (x[1], x[0]), reverse=True)
            positives = {keys[j] for j in (meta["primary_positive_index"], *meta["other_positive_indices"])
                         if j is not None}
            if meta["semantic_label"] == "TRUE_NEW":
                counts["true_new"] += 1
                mx = cands[0][1] if cands else 0.0
                score_max.append(mx)
                if cands and (mx >= 0.55 or (len(cands) >= 2 and mx >= 0.25
                                                and mx - cands[1][1] >= 0.15)):
                    new_eligible += 1
                continue
            counts["true_continue"] += 1
            if not positives:
                counts["candidate_missing"] += 1
                continue
            counts["rankable"] += 1
            rank = next(pos for pos, (key, _) in enumerate(cands, 1) if key in positives)
            for k in (1, 2, 3):
                counts[f"top{k}"] += rank <= k
            reciprocal += 1 / rank
            if meta["hard_negative_present"]:
                hard_total += 1
                hard_correct += rank == 1
    n = counts["rankable"]
    return {"candidate_coverage": n / counts["true_continue"] if counts["true_continue"] else 0.0,
            "rankable": n, "top1": counts["top1"] / n if n else 0.0,
            "top2": counts["top2"] / n if n else 0.0,
            "top3": counts["top3"] / n if n else 0.0, "mrr": reciprocal / n if n else 0.0,
            "hard_negative_top1": hard_correct / hard_total if hard_total else None,
            "hard_negative_count": hard_total,
            "true_new_count": counts["true_new"],
            "true_new_false_eligibility": new_eligible / counts["true_new"] if counts["true_new"] else 0.0,
            "true_new_mean_max_score": sum(score_max) / len(score_max) if score_max else None}


def verify_data() -> tuple[dict, dict]:
    assert file_sha256(BASE / "model.safetensors") == BASE_SHA, "Frozen baseline identity changed"
    assert file_sha256(RUN_ROOT / "training/recipe.json") == RECIPE_SHA, "Training recipe changed"
    paths = (SILVER / "train.jsonl", SILVER / "dev.jsonl")
    for path in paths:
        assert path.exists() and path.is_file(), f"No reviewed semantic silver: {path}"
        assert not path.resolve().is_relative_to((RUN_ROOT / "sealed-fresh-holdout").resolve())
    train_info = json.loads((SILVER / "train.manifest.json").read_text())
    dev_info = json.loads((SILVER / "dev.manifest.json").read_text())
    assert train_info["silver_sha256"] == file_sha256(paths[0])
    assert dev_info["silver_sha256"] == file_sha256(paths[1])
    counts = train_info["label_distribution"]
    # Gate policy: TRAIN >= 800 TRUE_CONTINUE. Original 500 TRUE_NEW minimum was formally
    # declared structurally invalid by user due to natural multi-month conversation sparsity;
    # all verified high-confidence TRUE_NEW are used, and ablation will test sufficiency.
    assert counts.get("TRUE_CONTINUE", 0) >= 800
    assert dev_info["selected"] >= 300
    return train_info, dev_info


def train(*, smoke: bool) -> None:
    train_info, dev_info = verify_data()  # Before lock/model/optimizer.
    out = RUN_ROOT / "training" / ("smoke-128" if smoke else "one-run")
    assert not out.exists(), "No overwrite and no second training lineage"
    out.mkdir(mode=0o700)
    started = time.time()
    with GpuLock(job_name="laya_hnr_smoke" if smoke else "laya_hnr_one_training_run"):
        agent = laya.load(str(BASE), device="cpu")
        model, tok = agent.model.to("cuda"), agent.tok
        sem_train = SemanticDataset(SILVER / "train.jsonl", tok, train=True)
        sem_dev = SemanticDataset(SILVER / "dev.jsonl", tok, train=False)
        if smoke:
            new_cases = [row for row in sem_train.rows if row["mapped"]["semantic_label"] == "TRUE_NEW"]
            take_new = min(16, len(new_cases))
            take_cont = 64 - take_new
            continuations = [row for row in sem_train.rows if row["mapped"]["semantic_label"] == "TRUE_CONTINUE"][:take_cont]
            sem_train.rows = continuations + new_cases[:take_new]
            assert len(sem_train.rows) == 64, "Smoke needs 64 cases"
        assert len(sem_train) >= (64 if smoke else 800)
        weak_batches = create_dataloader(str(WEAK_TRAIN), tok, batch_size=BATCH_SIZE, shuffle=True)
        sem_dev_loader = sem_loader(sem_dev, tok, shuffle=False, seed=46)
        baseline_new = semantic_dev_metrics(model, sem_dev_loader, "cuda", temperature=1.7958)["true_new_false_eligibility"] if not smoke else None
        no_decay = ("bias", "LayerNorm.weight", "final_norm.weight")
        grouped = [
            {"params": [p for name, p in model.named_parameters() if not any(x in name for x in no_decay)], "weight_decay": 0.01},
            {"params": [p for name, p in model.named_parameters() if any(x in name for x in no_decay)], "weight_decay": 0.0},
        ]
        opt = AdamW(grouped, lr=LR)
        weak_batch_count = 8 if smoke else len(weak_batches)
        total_batches = math.ceil(weak_batch_count * 1.5) * (1 if smoke else EPOCHS)
        total_steps = math.ceil(total_batches / GRAD_ACCUM)
        scheduler = get_cosine_schedule_with_warmup(opt, max(5, int(0.10 * total_steps)), total_steps)
        log_path = out / "training-log.jsonl"
        best_epoch, best_top1 = None, -1.0
        for epoch in range(1, (2 if smoke else EPOCHS + 1)):
            model.train()
            torch.manual_seed(1229 + epoch)
            sem_iter = iter(sem_loader(sem_train, tok, shuffle=True, seed=1229 + epoch))
            weak_count = sem_count = exposure = accum = 0
            sums: Counter[str] = Counter()
            opt.zero_grad()

            def backward(batch: dict, *, semantic: bool) -> None:
                nonlocal accum, exposure
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    logits = model_forward(model, batch, "cuda")
                    if semantic:
                        total, point, rank = semantic_batch_losses(logits, batch)
                        exposure += len(batch["meta"])
                    else:
                        total = point = weak_pointwise_loss(logits, batch["label"].to("cuda"))
                        rank = total.new_zeros(())
                if not torch.isfinite(total):
                    raise RuntimeError("Nonfinite HNR loss")
                (total / GRAD_ACCUM).backward()
                sums["total_loss"] += float(total.detach())
                sums["pointwise_loss"] += float(point.detach())
                sums["ranking_loss"] += float(rank.detach())
                sums["semantic_loss" if semantic else "weak_loss"] += float(total.detach())
                accum += 1
                if accum % GRAD_ACCUM == 0:
                    nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    opt.step()
                    scheduler.step()
                    opt.zero_grad()

            for weak_batch in weak_batches:
                backward(weak_batch, semantic=False)
                weak_count += 1
                if weak_count % 2 == 0:
                    try:
                        semantic_batch = next(sem_iter)
                    except StopIteration:
                        sem_iter = iter(sem_loader(sem_train, tok, shuffle=True, seed=1229 + epoch + sem_count + 1))
                        semantic_batch = next(sem_iter)
                    backward(semantic_batch, semantic=True)
                    sem_count += 1
                if smoke and weak_count == 8:
                    break
            if accum % GRAD_ACCUM:
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                scheduler.step()
                opt.zero_grad()
            record = {"epoch": epoch, "weak_batches": weak_count, "semantic_batches": sem_count,
                      "semantic_exposure_count": exposure, "steps": math.ceil(accum / GRAD_ACCUM),
                      "learning_rate": scheduler.get_last_lr()[0],
                      **{key: value / max(1, accum) for key, value in sums.items()}}
            ck = out / f"epoch-{epoch}"
            save_laya_checkpoint(model, tok, str(BASE), ck, temperature=1.7958)
            record["checkpoint_sha256"] = file_sha256(ck / "model.safetensors")
            assert record["checkpoint_sha256"] != BASE_SHA
            if smoke:
                reload_ok = verify_checkpoint_reload(ck, device="cpu")
                record["reload_verified"] = reload_ok
                assert reload_ok, "Smoke checkpoint reload failed"
            else:
                sem = semantic_dev_metrics(model, sem_dev_loader, "cuda", temperature=1.7958)
                weak = evaluate_laya(model, tok, str(WEAK_DEV), device="cuda", temperature=1.7958)
                record["semantic_dev"] = sem
                record["weak_dev_macro_f1"] = weak["macro_f1"]
                true_new_ok = sem["true_new_false_eligibility"] <= baseline_new + 0.10
                weak_ok = weak["macro_f1"] >= WEAK_DEV_F1_GUARD
                record["true_new_guard_pass"] = true_new_ok
                record["weak_dev_guard_pass"] = weak_ok
                if true_new_ok and weak_ok and sem["top1"] > best_top1 + 0.01:
                    best_epoch, best_top1 = epoch, sem["top1"]
            with log_path.open("a") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(json.dumps(record, ensure_ascii=False), flush=True)
        if not smoke:
            if best_epoch is None:
                (out / "TRAINING_REGRESSION").write_text("No epoch passed DEV guards\n")
                return
            selected = out / "best-dev-ranking"
            shutil.copytree(out / f"epoch-{best_epoch}", selected)
            assert file_sha256(selected / "model.safetensors") != BASE_SHA
            summary = {"selected_epoch": best_epoch, "semantic_dev_top1": best_top1,
                       "best_checkpoint_sha256": file_sha256(selected / "model.safetensors"),
                       "elapsed_seconds": time.time() - started, "baseline_true_new_false_eligibility": baseline_new,
                       "peak_vram_mb": torch.cuda.max_memory_allocated() / 2**20,
                       "weak_train_sha256": file_sha256(WEAK_TRAIN),
                       "semantic_train_sha256": train_info["silver_sha256"],
                       "semantic_dev_sha256": dev_info["silver_sha256"]}
            (out / "selection-summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if not args.smoke:
        assert (RUN_ROOT / "training/smoke-128/training-log.jsonl").exists(), "128-case smoke must pass first"
    train(smoke=args.smoke)


if __name__ == "__main__":
    main()
