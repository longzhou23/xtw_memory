"""Run deterministic candidate-ranking predictions with a Laya checkpoint.

Outputs prediction JSONL format required by hnr_independent_ranking_score.py.
Uses GpuLock for GPU inference.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, "/home/longzhooou/.cache/uv-laya-alt/archive-v0/FX854Ga3GurRg6vZ")

import laya
from laya.common import collate_items
import torch
from torch.utils.data import DataLoader, Dataset

from memory.scripts.gpu_gate import GpuLock
from memory.scripts.laya_training.hnr_semantic_loader import to_laya_semantic_item


class InferenceDataset(Dataset):
    def __init__(self, silver_path: Path, tok, *, is_holdout: bool) -> None:
        with silver_path.open() as stream:
            self.rows = [json.loads(line) for line in stream]
        self.tok = tok
        self.is_holdout = is_holdout

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, i: int) -> dict:
        row = self.rows[i]
        item = to_laya_semantic_item(
            row["packet"], row["mapped"], self.tok,
            allow_missing=True, allow_holdout=self.is_holdout
        )
        item["row_index"] = i
        return item


def predict(checkpoint_dir: Path, silver_path: Path, output_path: Path, *, device: str = "cuda") -> None:
    assert not output_path.exists(), f"Output already exists: {output_path}"
    with silver_path.open() as f:
        source_rows = [json.loads(line) for line in f]
    is_holdout = source_rows[0]["mapped"]["window"] == "HOLDOUT"

    with GpuLock(job_name=f"laya_hnr_predict_{output_path.stem}"):
        agent = laya.load(str(checkpoint_dir), device="cpu")
        model, tok = agent.model.to(device), agent.tok
        model.eval()

        dataset = InferenceDataset(silver_path, tok, is_holdout=is_holdout)
        loader = DataLoader(
            dataset, batch_size=16, shuffle=False,
            collate_fn=lambda items: collate_items([items], pad_id=tok.pad_token_id)
        )

        temperature = 1.7958  # standard Laya choice temperature
        predictions = []

        with torch.no_grad():
            for batch in loader:
                with torch.autocast(device_type="cuda" if "cuda" in device else "cpu", dtype=torch.bfloat16):
                    logits, _ = model(*(batch[k].to(device) for k in
                                        ("input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype")))

                for i, meta in enumerate(batch["meta"]):
                    idx = meta["row_index"]
                    src = source_rows[idx]["mapped"]
                    width = len(meta["ordered_keys"])
                    keys = meta["ordered_keys"]
                    raw_vals = logits[i, :width].float().cpu().tolist()
                    probs = torch.softmax(logits[i, :width] / temperature, dim=-1).float().cpu().tolist()

                    # Extract candidate options (exclude NEW and UNKNOWN)
                    cand_ids, cand_scores, cand_logits = [], [], []
                    for j, key in enumerate(keys):
                        if key not in ("NEW", "UNKNOWN"):
                            cand_ids.append(key)
                            cand_scores.append(probs[j])
                            cand_logits.append(raw_vals[j])

                    record = {
                        "case_id": src["case_id"],
                        "target_message_id": src["target_message_id"],
                        "candidate_ids": cand_ids,
                        "scores": cand_scores,
                        "raw_logits": cand_logits,
                        "semantic_label": src["semantic_label"],
                        "semantic_positive_ids": src.get("semantic_positive_candidate_ids", []),
                        "hard_negative_present": src.get("hard_negative_present", False),
                        "long_gap_bucket": src.get("long_gap_bucket"),
                        "positive_same_speaker": src.get("positive_same_speaker"),
                    }
                    predictions.append(record)

    output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with output_path.open("w") as out:
        for rec in predictions:
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    output_path.chmod(0o600)
    print(f"Wrote {len(predictions)} predictions to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--silver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    predict(args.checkpoint, args.silver, args.output, device=args.device)


if __name__ == "__main__":
    main()
