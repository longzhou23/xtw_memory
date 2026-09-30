"""Fixed-candidate semantic DEV-only boundary calibration; never reads HOLDOUT.

The replay uses dynamic candidates, so this offline calibration does not by
itself establish on-policy boundary quality. The policy reproduces p0.py's
high-threshold and margin branches for the available scored candidates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

THRESHOLDS = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)


def evaluate(rows: list[dict], threshold: float) -> dict:
    outcomes = []
    correct_rank = rankable = 0
    for row in rows:
        scores = row["scores"]
        ids = row["candidate_ids"]
        assert len(scores) == len(ids) and len(ids) == len(set(ids))
        assert row["semantic_label"] in ("TRUE_NEW", "TRUE_CONTINUE")
        ranked = sorted(zip(ids, scores), key=lambda item: (item[1], item[0]), reverse=True)
        best = ranked[0][1] if ranked else 0.0
        margin = best - ranked[1][1] if len(ranked) >= 2 else None
        continuation = bool(ranked) and (
            best >= threshold or
            (margin is not None and best >= 0.25 and margin >= 0.15 - 1e-12)
        )
        actual = "CONTINUE" if row["semantic_label"] == "TRUE_CONTINUE" else "NEW"
        predicted = "CONTINUE" if continuation else "NEW"
        outcomes.append((actual, predicted))
        if actual == "CONTINUE" and row["semantic_positive_ids"]:
            rankable += 1
            correct_rank += bool(ranked and ranked[0][0] in row["semantic_positive_ids"])
    cm = {actual: {pred: sum(a == actual and p == pred for a, p in outcomes)
                   for pred in ("NEW", "CONTINUE")}
          for actual in ("NEW", "CONTINUE")}

    def score(label: str) -> dict:
        tp = cm[label][label]
        fp = sum(cm[other][label] for other in cm if other != label)
        fn = sum(cm[label][other] for other in cm[label] if other != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        return {"precision": precision, "recall": recall,
                "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}

    new, cont = score("NEW"), score("CONTINUE")
    n = len(rows)
    return {"threshold": threshold, "confusion_matrix": cm, "TRUE_NEW": new,
            "CONTINUE": cont, "false_continue": cm["NEW"]["CONTINUE"],
            "false_continue_rate": cm["NEW"]["CONTINUE"] / sum(cm["NEW"].values()),
            "false_new": cm["CONTINUE"]["NEW"],
            "false_new_rate": cm["CONTINUE"]["NEW"] / sum(cm["CONTINUE"].values()),
            "macro_f1": (new["f1"] + cont["f1"]) / 2,
            "balanced_accuracy": (new["recall"] + cont["recall"]) / 2,
            # Historical field name retained for artifact compatibility. It
            # means CONTINUE decision frequency, not decision coverage.
            "routing_coverage": sum(p == "CONTINUE" for _, p in outcomes) / n,
            "candidate_top1_accuracy": correct_rank / rankable if rankable else None,
            "rankable_continue": rankable, "cases": n}


def clarify_coverage(metrics: dict) -> dict:
    """Add unambiguous coverage fields without changing legacy evaluate() output."""
    continue_count = sum(metrics["confusion_matrix"]["CONTINUE"].values())
    result = {}
    for key, value in metrics.items():
        if key == "candidate_top1_accuracy":
            result["predicted_continue_rate"] = metrics["routing_coverage"]
            result["decision_coverage"] = (sum(sum(row.values()) for row in metrics["confusion_matrix"].values())
                                           / metrics["cases"])
            result["continue_candidate_coverage"] = (metrics["rankable_continue"] / continue_count
                                                     if continue_count else None)
        result[key] = value
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), "Calibration artifact already exists"
    assert args.dev.name == "dev.jsonl" and "holdout" not in str(args.predictions).lower()
    dev = [json.loads(line) for line in args.dev.open()]
    rows = [json.loads(line) for line in args.predictions.open()]
    assert len(dev) == len(rows) == 301
    assert all(d["mapped"]["window"] == "DEV" and
               d["mapped"]["case_id"] == p["case_id"] and
               d["mapped"]["semantic_label"] == p["semantic_label"]
               for d, p in zip(dev, rows))
    results = [clarify_coverage(evaluate(rows, t)) for t in THRESHOLDS]
    # Report the unconstrained DEV optimum, but do not promote a threshold
    # that misses at least half of the genuinely new threads. This is an
    # explicit safety floor, not a post-hoc search over replay or HOLDOUT.
    best = max(results, key=lambda r: (r["macro_f1"], r["TRUE_NEW"]["recall"],
                                       -r["false_continue"], -r["threshold"]))
    selected = best if best["TRUE_NEW"]["recall"] >= 0.5 else None
    output = {"scope": "FIXED_CANDIDATE_SEMANTIC_DEV_ONLY",
              "dev_sha256": hashlib.sha256(args.dev.read_bytes()).hexdigest(),
              "predictions_sha256": hashlib.sha256(args.predictions.read_bytes()).hexdigest(),
              "policy": {"floor": 0.25, "margin": 0.15, "high_threshold_sweep": THRESHOLDS},
              "selection_metric": "maximize semantic DEV macro F1; require TRUE_NEW recall >= 0.5; ties: NEW recall, fewer false continues, lower threshold",
              "unconstrained_dev_optimum": best["threshold"],
              "selected_threshold": selected["threshold"] if selected else None,
              "selection_reason": "DEV-only fixed-candidate optimum; replay not consulted" if selected else "No safe threshold: the DEV macro-F1 optimum has catastrophic TRUE_NEW recall; do not freeze for runtime",
              "coverage_definitions": {"routing_coverage": "LEGACY MISNOMER: predicted CONTINUE rate",
                                       "predicted_continue_rate": "predicted CONTINUE / all cases",
                                       "decision_coverage": "cases routed NEW or CONTINUE / all cases",
                                       "continue_candidate_coverage": "CONTINUE cases with labeled positive candidate / all CONTINUE cases"},
              "results": results, "selected_metrics": selected}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"selected_threshold": output["selected_threshold"],
                      "unconstrained_dev_optimum": best["threshold"],
                      "selection_reason": output["selection_reason"]}, indent=2))


if __name__ == "__main__":
    main()
