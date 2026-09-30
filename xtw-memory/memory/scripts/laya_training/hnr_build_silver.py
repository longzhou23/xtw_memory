"""Build immutable HNR silver datasets from independent review + baseline traces.

No annotations are invented by this script. TRAIN alone is mined from baseline
scores; DEV and HOLDOUT keep the natural chronological order. The HOLDOUT
dataset is written only to the isolated sealed subtree.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import hnr_source_preflight as source
from hnr_case_mapping import map_case
from hnr_review_gate import clean_history


def load_unique(path: Path, key: str) -> dict[str, dict]:
    with path.open() as stream:
        rows = [json.loads(line) for line in stream]
    result = {row[key]: row for row in rows}
    assert len(result) == len(rows), f"Duplicate {key} in {path}"
    return result


def validated_join(window: str, packet_path: Path, review_path: Path, trace_path: Path,
                   sequence: dict[str, int]) -> list[dict]:
    packets = load_unique(packet_path, "case_id")
    reviews = load_unique(review_path, "case_id")
    traces = load_unique(trace_path, "target_message_id")
    assert set(reviews).issubset(set(packets)), "Review contains cases not in source packet"
    mapped = []
    for case_id, review in reviews.items():
        packet = packets[case_id]
        if review["review_confidence"] != "HIGH":
            continue
        assert review["target_message_id"] == packet["target_message_id"]
        assert packet["target_message_id"] in traces, "Missing frozen Router candidate trace"
        mapped.append({"packet": packet,
                       "mapped": map_case(review, traces[packet["target_message_id"]], sequence, window=window)})
    return mapped


def select_train(cases: list[dict]) -> list[dict]:
    continuations = [row for row in cases if row["mapped"]["semantic_label"] == "TRUE_CONTINUE"
                     and row["mapped"]["positive_available"]]
    fresh = [row for row in cases if row["mapped"]["semantic_label"] == "TRUE_NEW"
             and row["mapped"]["candidates"]]
    # User decision: original 500 TRUE_NEW minimum formally declared structurally invalid
    # (natural multi-month chat prevalence ~1%). TRUE_NEW hard minimum removed; all verified
    # high-confidence TRUE_NEW are used, and sufficiency will be evaluated via post-training ablation.
    if len(continuations) < 800:
        raise RuntimeError(f"DATASET_TOO_SMALL: TRAIN reviewed CONTINUE with candidate={len(continuations)} < 800")
    # TRAIN-only baseline-error mining: rank-wrong, crowded/close competition,
    # then natural fallback, all deterministic by frozen target case ID.
    def continue_priority(row: dict) -> tuple:
        m = row["mapped"]
        cs = m["candidates"]
        sorted_cs = sorted(cs, key=lambda c: (-c["score"], c["runtime_episode_id"]))
        wrong = int(bool(sorted_cs) and sorted_cs[0]["runtime_episode_id"] not in m["semantic_positive_candidate_ids"])
        close = int(len(sorted_cs) >= 2 and sorted_cs[0]["score"] - sorted_cs[1]["score"] <= 0.10)
        crowded = int(m["candidate_count_unmined"] >= 2)
        return (-wrong, -close, -crowded, m["case_id"])
    continuations.sort(key=continue_priority)
    fresh.sort(key=lambda row: (
        -max((c["score"] for c in row["mapped"]["candidates"]), default=0.0),
        row["mapped"]["case_id"],
    ))
    # Hard cases prioritized; all high-confidence TRUE_NEW included.
    selected = continuations[: min(1200, len(continuations))] + fresh
    return selected


def select_natural(cases: list[dict], count: int, minimum: int) -> list[dict]:
    # The caller must pass reviews in the precommitted natural chronological
    # packet order. No baseline score or error is consulted in this selection.
    if len(cases) < minimum:
        raise RuntimeError(f"DATASET_TOO_SMALL: natural reviewed HIGH={len(cases)} < {minimum}")
    return cases[:count]


def write_once(path: Path, rows: list[dict]) -> str:
    assert not path.exists(), f"Frozen silver already exists: {path}"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("x") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    path.chmod(0o600)
    return source.file_sha256(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", choices=("TRAIN", "DEV", "HOLDOUT"), required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    args = parser.parse_args()
    root = source.OUTPUT.resolve()
    sealed = (root / "sealed-fresh-holdout").resolve()
    for path in (args.packet, args.review, args.trace):
        assert path.resolve().is_relative_to(sealed) == (args.window == "HOLDOUT"), "HOLDOUT path isolation violated"
        assert path.resolve().is_relative_to(root), "All inputs must be frozen HNR artifacts"
    data = validated_join(args.window, args.packet, args.review, args.trace, clean_history())
    if args.window == "TRAIN":
        selected = select_train(data)
    elif args.window == "DEV":
        selected = select_natural(data, count=500, minimum=300)
    else:
        selected = select_natural(data, count=600, minimum=400)
    if args.window == "HOLDOUT":
        out = sealed / "semantic-hard-negative-silver-v0.1/holdout.jsonl"
    else:
        out = root / "dataset/semantic-hard-negative-silver-v0.1" / f"{args.window.lower()}.jsonl"
    digest = write_once(out, selected)
    labels = Counter(row["mapped"]["semantic_label"] for row in selected)
    summary = {"window": args.window, "reviewed_high_count": len(data),
               "selected": len(selected), "label_distribution": dict(labels),
               "silver_sha256": digest, "holdout_passed_to_trainer": False}
    summary_path = out.with_suffix(".manifest.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
