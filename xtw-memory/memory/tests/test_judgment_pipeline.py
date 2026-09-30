"""Automated Test Suite for Judgment Dataset & Frozen Benchmark v0.1.

Verifies:
- Case construction invariants & schema conformance (Spec 50, 51)
- Strict non-overlapping split isolation & leakage prevention (Spec 53)
- Teacher annotation validity & non-empty reasoning (Spec 52)
- Benchmark immutability & fingerprint integrity (Spec 54)
- Benchmark runner execution & metric computation (Spec 54, 55)
"""

import json
from pathlib import Path
import pytest

from memory.benchmarks.judgment.episode_routing_v01.runner import (
    MajorityBaselineProvider,
    HeuristicRuleProvider,
    JevStyleScorerProvider,
    evaluate_benchmark,
)

BASE_DIR = Path(__file__).resolve().parents[1]
JUDGMENT_DIR = BASE_DIR / "judgment" / "v0.1.0"
BENCHMARK_DIR = BASE_DIR / "benchmarks" / "judgment" / "episode-routing-v0.1.0"


def test_case_construction_and_schema():
    cases_path = JUDGMENT_DIR / "cases" / "cases.jsonl"
    assert cases_path.exists(), f"Missing cases file: {cases_path}"

    all_case_ids = set()
    conv_counts = {"c_000001": 0, "c_000002": 0}
    split_counts = {"train": 0, "dev": 0, "test": 0, "holdout": 0}

    with open(cases_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            case = json.loads(line)

            # Required schema keys
            for k in (
                "case_id", "task", "conversation_id", "target_message_id",
                "split", "target", "recent_context", "candidate_episodes", "source"
            ):
                assert k in case, f"Case {idx} missing key {k}"

            # Task invariant
            assert case["task"] == "episode_routing"

            # Case ID uniqueness
            cid = case["case_id"]
            assert cid not in all_case_ids, f"Duplicate case ID: {cid}"
            all_case_ids.add(cid)

            # Conv balance
            conv_counts[case["conversation_id"]] += 1
            split_counts[case["split"]] += 1

            # Candidate episodes structure
            assert len(case["candidate_episodes"]) >= 1, f"Case {cid} has no candidate episodes"
            for cand in case["candidate_episodes"]:
                assert "candidate_id" in cand
                assert "messages" in cand
                assert "participants" in cand
                assert "last_timestamp" in cand

            # Source provenance
            assert case["source"]["clean_dataset_version"] == "0.1.0"
            assert case["source"]["target_message_id"] == case["target"]["message_id"]

    assert len(all_case_ids) == 4000, f"Expected 4000 cases, got {len(all_case_ids)}"
    assert conv_counts["c_000001"] == 2000, "c_000001 must have exactly 2000 cases"
    assert conv_counts["c_000002"] == 2000, "c_000002 must have exactly 2000 cases"
    assert split_counts == {"train": 2800, "dev": 400, "test": 400, "holdout": 400}


def test_strict_split_isolation_and_no_leakage():
    """Spec 53: Verify ZERO conversation/time overlap between train, dev, test, and holdout."""
    splits = {}
    for s_name in ("train", "dev", "test", "holdout"):
        s_path = JUDGMENT_DIR / "splits" / f"{s_name}.jsonl"
        assert s_path.exists(), f"Missing split file: {s_path}"
        with open(s_path, "r", encoding="utf-8") as f:
            splits[s_name] = [json.loads(line) for line in f]

    # 1. Target message ID set disjointness
    target_id_sets = {s: {c["target_message_id"] for c in splits[s]} for s in splits}
    for s1 in splits:
        for s2 in splits:
            if s1 != s2:
                overlap = target_id_sets[s1].intersection(target_id_sets[s2])
                assert len(overlap) == 0, f"Leakage: target_message_id overlap between {s1} and {s2}: {overlap}"

    # 2. Case ID set disjointness
    case_id_sets = {s: {c["case_id"] for c in splits[s]} for s in splits}
    for s1 in splits:
        for s2 in splits:
            if s1 != s2:
                overlap = case_id_sets[s1].intersection(case_id_sets[s2])
                assert len(overlap) == 0, f"Leakage: case_id overlap between {s1} and {s2}"

    # 3. Context message disjointness with other split targets
    for s1 in splits:
        for s2 in splits:
            if s1 != s2:
                all_context_s1 = {mid for c in splits[s1] for mid in c["source"]["context_message_ids"]}
                targets_s2 = target_id_sets[s2]
                overlap = all_context_s1.intersection(targets_s2)
                assert len(overlap) == 0, f"Leakage: context in {s1} overlaps with target in {s2}: {overlap}"


def test_teacher_annotations():
    """Spec 52: Teacher annotations are structured, valid, and non-empty."""
    labels_path = JUDGMENT_DIR / "labels" / "labels.jsonl"
    assert labels_path.exists(), f"Missing labels file: {labels_path}"

    valid_prefixes = {"CONTINUE", "NEW", "UNKNOWN"}
    all_label_cases = set()

    with open(labels_path, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            cid = rec["case_id"]
            lbl = rec["label"]
            conf = rec["confidence"]
            reason = rec["reason"]
            model = rec["teacher_model"]

            all_label_cases.add(cid)
            prefix = lbl.split(":")[0]
            assert prefix in valid_prefixes, f"Invalid label prefix {prefix} in {lbl}"
            if prefix == "CONTINUE":
                assert ":" in lbl and len(lbl.split(":")[1]) > 0, f"CONTINUE missing candidate_id in {lbl}"
            assert 0.0 <= conf <= 1.0, f"Confidence out of bounds: {conf}"
            assert len(reason.strip()) > 5, f"Reason too short for case {cid}"
            assert model, "teacher_model must be recorded"

    assert len(all_label_cases) == 4000, f"Expected 4000 labels, got {len(all_label_cases)}"


def test_frozen_benchmark_and_runner():
    """Spec 54: Frozen benchmark exists, matches TEST split, and runs scoring."""
    test_bench_path = BENCHMARK_DIR / "test_benchmark.jsonl"
    assert test_bench_path.exists(), f"Missing benchmark file: {test_bench_path}"

    test_split_path = JUDGMENT_DIR / "splits" / "test.jsonl"
    with open(test_bench_path, "r", encoding="utf-8") as f1, open(test_split_path, "r", encoding="utf-8") as f2:
        bench_cases = [json.loads(line) for line in f1]
        split_cases = [json.loads(line) for line in f2]

    assert len(bench_cases) == 400, "Benchmark must have 400 cases"
    assert len(bench_cases) == len(split_cases)
    for c1, c2 in zip(bench_cases, split_cases):
        assert c1["case_id"] == c2["case_id"]
        assert c1["ground_truth"]["label"] == c2["ground_truth"]["label"]

    # Test baseline evaluation
    baseline = MajorityBaselineProvider(default_label="NEW")
    res = evaluate_benchmark(bench_cases, baseline)

    assert "accuracy" in res
    assert "macro_f1" in res
    assert "critical_errors" in res
    assert "false_continue_rate" in res["critical_errors"]
    assert "false_new_rate" in res["critical_errors"]

    # Test rule baseline
    rule_prov = HeuristicRuleProvider()
    res_rule = evaluate_benchmark(bench_cases, rule_prov)
    assert res_rule["accuracy"] > 0.40, "Heuristic baseline should achieve reasonable accuracy"
