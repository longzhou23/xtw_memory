"""Zero-Trust Independent Scorer.

Strictly adheres to Spec v0.1 Section 21 & 22:
- Does NOT import any benchmark evaluator or pipeline module.
- Reads ONLY predictions.jsonl and the frozen reference cases.jsonl.
- Calculates exact canonical routing metrics: Accuracy, Macro Precision/Recall/F1,
  per-class metrics, confusion matrix, False Continue, False New.
- Includes a rigorous self-test suite verified against hand-calculated matrices.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple


def compute_routing_metrics(predictions: List[Dict[str, Any]], ground_truths: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pure mathematical scorer for Episode Routing evaluation."""
    assert len(predictions) == len(ground_truths), f"Length mismatch: {len(predictions)} != {len(ground_truths)}"
    total = len(predictions)
    if total == 0:
        return {"error": "Empty set"}

    pred_map = {p["case_id"]: p["prediction"] for p in predictions}
    
    correct = 0
    by_cat_total = Counter()
    by_cat_correct = Counter()
    confusion_matrix = Counter()
    pred_cat_counts = Counter()

    false_continue = 0  # Actual NEW/UNKNOWN -> Pred CONTINUE
    false_new = 0       # Actual CONTINUE -> Pred NEW
    unknown_misuse = 0

    all_pairs = []

    for gt_item in ground_truths:
        cid = gt_item["case_id"]
        assert cid in pred_map, f"Missing prediction for case {cid}"
        raw_pred = pred_map[cid]

        # Extract ground truth label
        gt_label = gt_item.get("ground_truth", {}).get("label") or gt_item.get("label")
        assert gt_label is not None, f"Missing label in GT for case {cid}"

        # Standardize categories:
        # If candidate key: e.g. "cand_1", "cand_2" or "CONTINUE:cand_1"
        gt_key = gt_label.split(":", 1)[1] if gt_label.startswith("CONTINUE:") else gt_label
        pred_key = raw_pred.split(":", 1)[1] if raw_pred.startswith("CONTINUE:") else raw_pred

        gt_cat = "CONTINUE" if gt_key.startswith("cand_") else gt_key
        pred_cat = "CONTINUE" if pred_key.startswith("cand_") else pred_key

        all_pairs.append((gt_cat, gt_key, pred_cat, pred_key))
        by_cat_total[gt_cat] += 1
        pred_cat_counts[pred_cat] += 1
        confusion_matrix[(gt_cat, pred_cat)] += 1

        # Exact match check: for CONTINUE, exact candidate key must match!
        if pred_key == gt_key:
            correct += 1
            by_cat_correct[gt_cat] += 1

        if gt_cat != "CONTINUE" and pred_cat == "CONTINUE":
            false_continue += 1
        if gt_cat == "CONTINUE" and pred_cat == "NEW":
            false_new += 1
        if gt_cat != "UNKNOWN" and pred_cat == "UNKNOWN":
            unknown_misuse += 1

    accuracy = correct / total

    # Per-class P / R / F1 across (CONTINUE, NEW, UNKNOWN)
    f1_list = []
    prec_list = []
    rec_list = []
    category_metrics = {}

    for cat in ("CONTINUE", "NEW", "UNKNOWN"):
        c_gt = by_cat_total[cat]
        tp = by_cat_correct[cat]
        # FP: predicted this cat, but did not match target
        fp = sum(1 for g_cat, g_k, p_cat, p_k in all_pairs if p_cat == cat and p_k != g_k)
        # FN: actual this cat, but did not match target
        fn = sum(1 for g_cat, g_k, p_cat, p_k in all_pairs if g_cat == cat and p_k != g_k)

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0

        f1_list.append(f1)
        prec_list.append(prec)
        rec_list.append(rec)

        category_metrics[cat] = {
            "total": c_gt,
            "correct": tp,
            "accuracy": round(tp / c_gt, 4) if c_gt > 0 else 0.0,
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
        }

    macro_f1 = sum(f1_list) / len(f1_list)
    macro_precision = sum(prec_list) / len(prec_list)
    macro_recall = sum(rec_list) / len(rec_list)

    cont_gt = by_cat_total["CONTINUE"]
    non_cont_gt = by_cat_total["NEW"] + by_cat_total["UNKNOWN"]

    return {
        "total_cases": total,
        "correct": correct,
        "accuracy": round(accuracy, 4),
        "macro_precision": round(macro_precision, 4),
        "macro_recall": round(macro_recall, 4),
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
    }


def run_self_test():
    """Spec Section 22: Self-test with hand-calculated synthetic arrays."""
    print("[SCORER SELF-TEST] Running hand-calculated verification...", end=" ")
    
    # Test 1: All correct (3 cases: 1 CONTINUE:cand_1, 1 NEW, 1 UNKNOWN)
    gt_all_correct = [
        {"case_id": "c1", "label": "CONTINUE:cand_1"},
        {"case_id": "c2", "label": "NEW"},
        {"case_id": "c3", "label": "UNKNOWN"},
    ]
    pred_all_correct = [
        {"case_id": "c1", "prediction": "cand_1"},
        {"case_id": "c2", "prediction": "NEW"},
        {"case_id": "c3", "prediction": "UNKNOWN"},
    ]
    res1 = compute_routing_metrics(pred_all_correct, gt_all_correct)
    assert res1["accuracy"] == 1.0
    assert res1["macro_f1"] == 1.0
    assert res1["critical_errors"]["false_continue_count"] == 0
    assert res1["critical_errors"]["false_new_count"] == 0

    # Test 2: All NEW prediction on 4 cases (2 CONTINUE, 1 NEW, 1 UNKNOWN)
    # Hand calculation:
    # TP: NEW=1, CONTINUE=0, UNKNOWN=0
    # Acc = 1/4 = 0.25
    # NEW: P = 1/4 = 0.25, R = 1/1 = 1.0, F1 = 2*0.25*1 / 1.25 = 0.40
    # CONTINUE: F1 = 0
    # UNKNOWN: F1 = 0
    # Macro F1 = (0.40 + 0 + 0) / 3 = 0.1333
    # False continue = 0
    # False new = 2/2 = 1.0
    gt_mix = [
        {"case_id": "c1", "label": "CONTINUE:cand_1"},
        {"case_id": "c2", "label": "CONTINUE:cand_2"},
        {"case_id": "c3", "label": "NEW"},
        {"case_id": "c4", "label": "UNKNOWN"},
    ]
    pred_all_new = [
        {"case_id": "c1", "prediction": "NEW"},
        {"case_id": "c2", "prediction": "NEW"},
        {"case_id": "c3", "prediction": "NEW"},
        {"case_id": "c4", "prediction": "NEW"},
    ]
    res2 = compute_routing_metrics(pred_all_new, gt_mix)
    assert res2["accuracy"] == 0.25
    assert abs(res2["macro_f1"] - 0.1333) < 0.001
    assert res2["critical_errors"]["false_new_rate"] == 1.0
    assert res2["critical_errors"]["false_continue_rate"] == 0.0

    print("PASS (All synthetic assertions strictly match hand calculations!)")


def main():
    if "--self-test" in sys.argv:
        run_self_test()
        return

    parser = argparse.ArgumentParser(description="Zero-Trust Independent Scorer")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args()

    run_self_test()

    with open(args.predictions) as f:
        preds = [json.loads(line) for line in f if line.strip()]

    with open(args.ground_truth) as f:
        gts = [json.loads(line) for line in f if line.strip()]

    metrics = compute_routing_metrics(preds, gts)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output_json, "w") as f:
            json.dump(metrics, f, indent=2)

    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
