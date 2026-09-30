"""Strict two-pass semantic review merge; never infer gold from a teacher.

Review A/B must be produced independently from the blind packets. This gate
does not generate either review pass and must not be called by the trainer on
the fresh HOLDOUT. Agreement requires identical semantic decision and, for
CONTINUE, at least one common valid anchor in prior clean conversation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import hnr_source_preflight as source
from hnr_blind_packets import EXPECTED_WINDOW_MANIFEST_SHA256, REVIEW_DIR, HOLDOUT_DIR


REVIEW_KEYS = {"case_id", "label", "confidence", "semantic_thread", "anchor_message_ids"}
LABELS = {"TRUE_NEW", "TRUE_CONTINUE", "UNCERTAIN"}


def read_jsonl(path: Path) -> list[dict]:
    with path.open() as stream:
        return [json.loads(line) for line in stream]


def validate_review(row: dict, packet: dict, history: dict[str, int]) -> None:
    assert set(row) == REVIEW_KEYS, f"Unexpected key (possible prediction leakage) for {packet['case_id']}"
    assert row["case_id"] == packet["case_id"]
    assert row["label"] in LABELS
    assert row["confidence"] in ("HIGH", "LOW")
    assert isinstance(row["semantic_thread"], str)
    assert isinstance(row["anchor_message_ids"], list)
    anchors = row["anchor_message_ids"]
    assert len(anchors) == len(set(anchors))
    assert all(isinstance(mid, str) and mid in history and history[mid] < history[packet["target_message_id"]]
               for mid in anchors), f"Invalid or future anchor in {packet['case_id']}"
    if row["label"] == "TRUE_CONTINUE":
        assert row["semantic_thread"].strip() and anchors, "CONTINUE needs thread and clean-history anchor"
    else:
        assert not anchors, "NEW/UNCERTAIN must not carry positive anchors"


def merge(packets: list[dict], pass_a: list[dict], pass_b: list[dict], history: dict[str, int]) -> tuple[list[dict], dict]:
    assert len(packets) == len(pass_a) == len(pass_b), "Both passes must independently review every packet"
    assert len({p["case_id"] for p in packets}) == len(packets)
    index_a = {r["case_id"]: r for r in pass_a}
    index_b = {r["case_id"]: r for r in pass_b}
    assert len(index_a) == len(pass_a) and len(index_b) == len(pass_b)
    assert set(index_a) == set(index_b) == {p["case_id"] for p in packets}
    merged: list[dict] = []
    counts: Counter[str] = Counter()
    for p in packets:
        a, b = index_a[p["case_id"]], index_b[p["case_id"]]
        validate_review(a, p, history)
        validate_review(b, p, history)
        agreed = a["label"] == b["label"] and a["confidence"] == b["confidence"] == "HIGH"
        common_anchors = sorted(set(a["anchor_message_ids"]) & set(b["anchor_message_ids"]))
        if agreed and a["label"] == "TRUE_CONTINUE" and not common_anchors:
            agreed = False
        label = a["label"] if agreed else "UNCERTAIN"
        counts[label] += 1
        if a["label"] != b["label"]:
            counts["label_disagreement"] += 1
        if a["label"] == b["label"] == "TRUE_CONTINUE" and not common_anchors:
            counts["anchor_disagreement"] += 1
        if (a["label"] == b["label"] == "TRUE_CONTINUE"
                and a["semantic_thread"].strip().casefold() != b["semantic_thread"].strip().casefold()):
            counts["thread_wording_differs"] += 1
        merged.append({
            "case_id": p["case_id"],
            "target_message_id": p["target_message_id"],
            "semantic_label": label,
            "semantic_thread": a["semantic_thread"] if label == "TRUE_CONTINUE" else None,
            "semantic_thread_review_b": b["semantic_thread"] if label == "TRUE_CONTINUE" else None,
            "valid_anchor_message_ids": common_anchors if label == "TRUE_CONTINUE" else [],
            "review_confidence": "HIGH" if agreed and label != "UNCERTAIN" else "UNCERTAIN",
        })
    return merged, dict(sorted(counts.items()))


def clean_history() -> dict[str, int]:
    result: dict[str, int] = {}
    with source.DATA.open() as stream:
        for line in stream:
            row = json.loads(line)
            if row["conversation_id"] == "c_000001":
                result[row["message_id"]] = row["sequence_index"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", choices=("TRAIN", "DEV", "HOLDOUT"), required=True)
    parser.add_argument("--pass-a", type=Path, required=True)
    parser.add_argument("--pass-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert source.file_sha256(source.OUTPUT / "window-manifest.json") == EXPECTED_WINDOW_MANIFEST_SHA256
    directory = HOLDOUT_DIR if args.window == "HOLDOUT" else REVIEW_DIR
    # Holdout review outputs must remain in the sealed holdout subtree.
    if args.window == "HOLDOUT":
        assert args.output.resolve().is_relative_to(HOLDOUT_DIR.resolve())
    else:
        assert not args.output.resolve().is_relative_to(HOLDOUT_DIR.resolve())
    assert args.pass_a.resolve() != args.pass_b.resolve()
    assert args.output.resolve() not in (args.pass_a.resolve(), args.pass_b.resolve())
    packets = read_jsonl(directory / f"{args.window.lower()}-blind.jsonl")
    reviewed, distribution = merge(packets, read_jsonl(args.pass_a), read_jsonl(args.pass_b), clean_history())
    assert not args.output.exists(), "Cannot overwrite a sealed review result"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        for item in reviewed:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(json.dumps({"window": args.window, "distribution": distribution,
                      "sha256": source.file_sha256(args.output)}, indent=2))


if __name__ == "__main__":
    main()
