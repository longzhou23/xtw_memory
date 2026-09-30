"""Validate two blinded passes over reply-edge split candidates."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


def records(path: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in path.open()]
    assert len(rows) == len({r["review_id"] for r in rows})
    return {r["review_id"]: r for r in rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("packets", "pass-a", "pass-b", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected", type=int, default=20)
    args = vars(parser.parse_args())
    assert not args["output"].exists()
    packets, a, b = (records(args[name]) for name in ("packets", "pass_a", "pass_b"))
    assert len(packets) == args["expected"] and packets.keys() == a.keys() == b.keys()
    merged, tally = [], Counter()
    for key, p in packets.items():
        for row in (a[key], b[key]):
            assert row["label"] in ("TRUE_CONTINUE", "TRUE_NEW", "UNCERTAIN")
            assert row["confidence"] in ("HIGH", "LOW")
            assert row["rationale"].strip()
            assert set(row["evidence_message_ids"]) <= {p["target"]["message_id"], p["anchor"]["message_id"]}
        label = a[key]["label"] if a[key]["label"] == b[key]["label"] and all(
            r["confidence"] == "HIGH" for r in (a[key], b[key])) else "DISAGREED_OR_LOW_CONFIDENCE"
        merged.append({"review_id": key, "label": label, "review_a": a[key], "review_b": b[key]})
        tally[label] += 1
    args["output"].write_text(json.dumps({"scope": "BLINDED_DIRECT_REPLY_REVIEW",
                                            "counts": tally, "decisions": merged}, ensure_ascii=False, indent=2) + "\n")
    print(dict(tally))


if __name__ == "__main__":
    main()
