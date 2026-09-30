"""Assemble complete isolated Pass A/B shards and freeze semantic decisions.

This process is the *only* step allowed to see both reviewers' outputs. It
does not read any model, Teacher predictions or Judgment HOLDOUT. Incomplete
review ranges cannot be silently omitted to inflate confidence rates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import hnr_source_preflight as source
from hnr_blind_packets import REVIEW_DIR, HOLDOUT_DIR
from hnr_review_gate import read_jsonl, merge, clean_history


def shards(directory: Path, pass_name: str, window: str, n: int) -> list[dict]:
    pieces = []
    matcher = re.compile(rf"pass-{pass_name}-{window}-(\d{{4}})-(\d{{4}})\.jsonl$")
    for path in directory.glob(f"pass-{pass_name}-{window}-*.jsonl"):
        m = matcher.fullmatch(path.name)
        if not m:
            continue
        start, end = int(m[1]), int(m[2])
        if start >= n:
            continue
        assert end < n, "Unexpected overlap beyond selected quota"
        pieces.append((start, end, path))
    pieces.sort(key=lambda x: x[0])
    output = []
    expected = 0
    for start, end, path in pieces:
        assert start == expected, f"Missing or overlapping reviewed range before {start}"
        rows = read_jsonl(path)
        assert len(rows) == end - start + 1
        output.extend(rows)
        expected = end + 1
    assert expected == n, f"Incomplete {pass_name} {window}: {expected}/{n}"
    return output


def write_once(path: Path, rows: list[dict]) -> str:
    assert not path.exists(), f"Cannot overwrite review artifact: {path}"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("x") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    path.chmod(0o600)
    return source.file_sha256(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", choices=("TRAIN", "DEV", "HOLDOUT"), required=True)
    parser.add_argument("--count", type=int, default=None, help="Number of reviewed cases to assemble (defaults to total in packet)")
    args = parser.parse_args()
    window = args.window.lower()
    folder = HOLDOUT_DIR.parent if window == "holdout" else REVIEW_DIR.parent
    inputs = (REVIEW_DIR / "train-proposed-blind-3300.jsonl" if window == "train" else
              (HOLDOUT_DIR if window == "holdout" else REVIEW_DIR) /
              f"{window}-natural-{1200 if window == 'holdout' else 1000}.jsonl")
    all_packets = read_jsonl(inputs)
    n = args.count if args.count is not None else len(all_packets)
    packets = all_packets[:n]
    a = shards(folder / "review-a", "a", window, n)
    b = shards(folder / "review-b", "b", window, n)
    merged, audit = merge(packets, a, b, clean_history())
    decided_dir = folder / "review-decisions"
    data_file = decided_dir / f"{window}-two-pass.jsonl"
    digest = write_once(data_file, merged)
    manifest = {"window": args.window,
                "blind_packet_sha256": source.file_sha256(inputs),
                "reviewer_a_case_count": len(a), "reviewer_b_case_count": len(b),
                "decision_count": len(merged), "review_audit": audit,
                "decisions_sha256": digest,
                "judgment_holdout_read": False,
                "model_scores_or_teacher_labels_read": False}
    report = decided_dir / f"{window}-review-audit.json"
    assert not report.exists()
    report.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
