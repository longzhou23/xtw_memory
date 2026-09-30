"""Validate independent blinded review records before unblinding arms."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

LABELS = {"COHERENT", "OVER_MERGE", "UNCERTAIN"}


def load(path: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in path.open()]
    assert len({r["review_id"] for r in rows}) == len(rows)
    return {r["review_id"]: r for r in rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("packets", "pass-a", "pass-b", "mapping", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected", type=int, default=24)
    args = vars(parser.parse_args())
    assert not args["output"].exists()
    packets, a, b, mapping = (load(args["packets"]), load(args["pass_a"]),
                              load(args["pass_b"]), json.loads(args["mapping"].read_text()))
    assert len(packets) == args["expected"]
    assert packets.keys() == a.keys() == b.keys() == mapping.keys(), "Missing/extra/duplicate review IDs"
    counts = Counter()
    decisions = []
    for key, packet in packets.items():
        allowed_ids = {e["message_id"] for e in packet["events"]}
        invalid_evidence = []
        for reviewer in (a[key], b[key]):
            assert reviewer["label"] in LABELS and reviewer["confidence"] in ("HIGH", "LOW")
            assert isinstance(reviewer["rationale"], str) and reviewer["rationale"].strip()
            if not set(reviewer["evidence_message_ids"]) <= allowed_ids or (
                reviewer["label"] == "OVER_MERGE" and len(set(reviewer["evidence_message_ids"])) < 2
            ):
                invalid_evidence.append(reviewer["evidence_message_ids"])
        agreed = (not invalid_evidence and a[key]["label"] == b[key]["label"] and a[key]["confidence"] == "HIGH"
                  and b[key]["confidence"] == "HIGH")
        label = ("INVALID_EVIDENCE_EXCLUDED" if invalid_evidence else
                 a[key]["label"] if agreed else "REVIEW_DISAGREEMENT_OR_LOW_CONFIDENCE")
        counts[(mapping[key]["arm"], label)] += 1
        decisions.append({"review_id": key, "arm": mapping[key]["arm"], "episode_id": mapping[key]["episode_id"],
                          "merged_label": label, "invalid_evidence": invalid_evidence,
                          "review_a": a[key], "review_b": b[key]})
    result = {"scope": "FIRST_PRIORITY_SAMPLE_ONLY_NOT_POPULATION_RATE",
              "counts": [{"arm": arm, "label": label, "count": count} for (arm, label), count in sorted(counts.items())],
              "decisions": decisions}
    args["output"].write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
