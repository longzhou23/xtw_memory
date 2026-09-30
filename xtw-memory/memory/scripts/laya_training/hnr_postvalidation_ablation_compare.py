"""Compare precommitted final-epoch 0/123 controlled runs on DEV only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from memory.scripts.laya_training.hnr_postvalidation_calibrate import evaluate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    plan = json.loads((args.root / "plan.json").read_text())
    assert plan["arms"] == ["zero", "all-123"] and plan["final_evaluation_epoch"] == 3
    arms = {}
    dev_cases = None
    for arm in ("zero", "all-123"):
        folder = args.root / arm
        validated = folder / "training-log-validated.jsonl"
        if validated.exists():
            audit = json.loads((folder / "training-log-lineage-audit.json").read_text())
            original = (folder / "training-log.jsonl").read_bytes()
            assert hashlib.sha256(original).hexdigest() == audit["original_log_sha256"]
            assert hashlib.sha256(validated.read_bytes()).hexdigest() == audit["validated_log_sha256"]
            original_rows = [json.loads(x) for x in original.splitlines()]
            assert [x["epoch"] for x in original_rows] == audit["original_epoch_sequence"] == [3, 1, 2, 3]
            assert original_rows[0]["checkpoint_sha256"] == audit["orphan_line_checkpoint_sha256"]
            assert original_rows[0]["checkpoint_sha256"] != original_rows[-1]["checkpoint_sha256"]
        log = [json.loads(x) for x in (validated if validated.exists() else folder / "training-log.jsonl").open()]
        assert [x["epoch"] for x in log] == [1, 2, 3]
        if validated.exists():
            assert log == original_rows[1:]
            assert [{"epoch": x["epoch"], "checkpoint_sha256": x["checkpoint_sha256"]}
                    for x in log] == audit["validated_lineage"]
        assert len({x["frozen_base_sha256"] for x in log}) == 1
        assert all(x["weak_batches"] == 2500 and x["semantic_batches"] == 1250 for x in log)
        assert all(x["train_counts"].get("TRUE_CONTINUE") == 822 for x in log)
        assert all(x["train_counts"].get("TRUE_NEW", 0) == (0 if arm == "zero" else 123) for x in log)
        assert all(x["optimizer_steps"] == 1875 for x in log)
        assert len({x["policy"] for x in log}) == 1
        for entry in log:
            checkpoint = folder / f"epoch-{entry['epoch']}" / "model.safetensors"
            assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == entry["checkpoint_sha256"]
            if "effective_train_case_fingerprint" in entry:
                assert entry["effective_train_case_fingerprint"] == plan["effective_case_fingerprints"][arm]["sha256"]
            if "continuation_case_fingerprint" in entry:
                assert entry["continuation_case_fingerprint"] == plan["continuation_case_ids_sha256"]
        pred = [json.loads(x) for x in (folder / "epoch-3-dev-predictions.jsonl").open()]
        assert len(pred) == 301 and len({x["case_id"] for x in pred}) == 301
        assert all(x["case_id"].startswith("hnr_dev_") for x in pred)
        cases = {x["case_id"]: (x["target_message_id"], x["semantic_label"],
                                tuple(x["candidate_ids"]), tuple(x["semantic_positive_ids"]))
                 for x in pred}
        if dev_cases is None:
            dev_cases = cases
        else:
            assert cases == dev_cases, "DEV targets, labels, positives and candidates must match across arms"
        arms[arm] = {"checkpoint_sha256": log[-1]["checkpoint_sha256"],
                     "weak_dev_macro_f1": log[-1]["weak_dev_macro_f1"],
                     "ranking_top1": log[-1]["semantic_dev"]["top1"],
                     "boundary_055": evaluate(pred, .55), "train_counts": log[-1]["train_counts"],
                     "epoch_logs": log}
    a, b = arms["zero"], arms["all-123"]
    for field in ("frozen_base_sha256", "weak_train_sha256", "semantic_train_sha256", "semantic_dev_sha256"):
        assert len({entry[field] for arm in (a, b) for entry in arm["epoch_logs"]}) == 1
    assert a["epoch_logs"][-1]["policy"] == b["epoch_logs"][-1]["policy"]
    assert a["epoch_logs"][-1]["frozen_base_sha256"] == plan["baseline_sha256"]
    assert a["epoch_logs"][-1]["semantic_train_sha256"] == plan["semantic_train_sha256"]
    assert a["epoch_logs"][-1]["semantic_dev_sha256"] == plan["semantic_dev_sha256"]
    assert a["epoch_logs"][-1]["weak_train_sha256"] == b["epoch_logs"][-1]["weak_train_sha256"]
    assert a["checkpoint_sha256"] != b["checkpoint_sha256"]
    output = {"comparison": "fixed final epoch 3, original 0.55 boundary policy, no checkpoint selection",
              "arms": arms,
              "deltas_all_minus_zero": {
                  "weak_dev_macro_f1": b["weak_dev_macro_f1"] - a["weak_dev_macro_f1"],
                  "ranking_top1": b["ranking_top1"] - a["ranking_top1"],
                  "true_new_recall": b["boundary_055"]["TRUE_NEW"]["recall"] - a["boundary_055"]["TRUE_NEW"]["recall"],
                  "false_continue_rate": b["boundary_055"]["false_continue_rate"] - a["boundary_055"]["false_continue_rate"],
                  "false_new_rate": b["boundary_055"]["false_new_rate"] - a["boundary_055"]["false_new_rate"],
              }}
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(output["deltas_all_minus_zero"], indent=2))


if __name__ == "__main__":
    main()
