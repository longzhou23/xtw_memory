"""Fixed-input paired DEV diagnostics; never tune weights or read HOLDOUT."""
from __future__ import annotations

from collections import Counter
import argparse
import hashlib
import json
from math import comb
from pathlib import Path


def route(row: dict, high: float) -> str:
    scores = sorted(row["scores"], reverse=True)
    if not scores:
        return "NEW"
    if scores[0] >= high:
        return "HIGH"
    if len(scores) >= 2 and scores[0] >= 0.25 and scores[0] - scores[1] >= 0.15 - 1e-12:
        return "MARGIN"
    return "NEW"


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    folder = args.evaluation
    main_path = folder / "post-validation-hnr-dev-predictions.jsonl"
    zero_path = folder / "true-new-controlled-ablation/zero/epoch-3-dev-predictions.jsonl"
    all_path = folder / "true-new-controlled-ablation/all-123/epoch-3-dev-predictions.jsonl"
    paths = (main_path, zero_path, all_path)
    original, zero, all_new = (load(path) for path in paths)
    assert len(original) == len(zero) == len(all_new) == 301
    for triplet in zip(original, zero, all_new):
        assert len({item["case_id"] for item in triplet}) == 1
        assert len({item["semantic_label"] for item in triplet}) == 1
        assert all(item["candidate_ids"] == triplet[0]["candidate_ids"] and
                   item["semantic_positive_ids"] == triplet[0]["semantic_positive_ids"] for item in triplet)
    assert len({row["case_id"] for row in original}) == 301
    counts = Counter(row["semantic_label"] for row in original)
    assert counts == {"TRUE_NEW": 27, "TRUE_CONTINUE": 274}
    threshold_mechanisms = {}
    for threshold in (0.4, 0.55, 0.8):
        c = Counter(route(row, threshold) for row in original if row["semantic_label"] == "TRUE_NEW")
        threshold_mechanisms[str(threshold)] = {label: c[label] for label in ("HIGH", "MARGIN", "NEW")}
        assert c["NEW"] == 5

    transitions = {"TRUE_NEW": Counter(), "TRUE_CONTINUE": Counter()}
    for a, b in zip(zero, all_new):
        transitions[a["semantic_label"]][(route(a, 0.55) == "NEW", route(b, 0.55) == "NEW")] += 1
    new = transitions["TRUE_NEW"]
    improved = new[(False, True)]
    regressed = new[(True, False)]
    discordant = improved + regressed
    assert improved == 6 and regressed == 1 and discordant == 7
    two_sided_sign_p = min(1.0, 2 * sum(comb(discordant, k) for k in range(improved, discordant + 1))
                           / (2 ** discordant))
    assert two_sided_sign_p == 0.125
    output = {
        "scope": "Fixed semantic DEV predictions only; original frozen HNR and final epoch-3 two-arm control",
        "prediction_sha256": {path.name if path == main_path else f"{path.parent.name}/{path.name}":
                              hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
        "case_counts": dict(counts),
        "main_true_new_decision_mechanism_by_high_threshold": threshold_mechanisms,
        "controlled_arm_true_new_paired_predictions_zero_to_all123": {
            "both_NEW": new[(True, True)], "zero_NEW_to_all_CONTINUE_regressed": regressed,
            "zero_CONTINUE_to_all_NEW_improved": improved, "both_CONTINUE": new[(False, False)]},
        "controlled_arm_continue_paired_predictions_zero_to_all123": {
            "both_NEW": transitions["TRUE_CONTINUE"][(True, True)],
            "zero_NEW_to_all_CONTINUE": transitions["TRUE_CONTINUE"][(True, False)],
            "zero_CONTINUE_to_all_NEW": transitions["TRUE_CONTINUE"][(False, True)],
            "both_CONTINUE": transitions["TRUE_CONTINUE"][(False, False)]},
        "true_new_discordant_n": discordant,
        "true_new_two_sided_exact_sign_test_p_descriptive": two_sided_sign_p,
        "interpretation": "At the fixed boundary, 6 NEW cases improve and 1 regresses: directional single-seed "
                          "DEV protection, with 19/27 still missed in the 123 arm. A descriptive two-sided "
                          "paired sign test gives p=0.125 (not conventional 0.05-level evidence). Original "
                          "HNR misses 22/27 NEW cases at every tested high threshold; at 0.8, 20 are already "
                          "above the high cutoff and 2 pass the frozen margin branch. Neither the controlled "
                          "checkpoint nor this post-hoc test is a replacement or threshold selection."
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"mechanism": threshold_mechanisms,
                      "controlled_new_transitions": output["controlled_arm_true_new_paired_predictions_zero_to_all123"],
                      "exact_p": two_sided_sign_p}, indent=2))


if __name__ == "__main__":
    main()
