"""Blinded semantic-review packets for structural replay auditing.

Packets omit checkpoint, Router score, and pre-judged topic labels. Selection
covers every multi-event episode; short episodes carry a reproducible seeded
sample marker for prioritizing independent blinded review when volume is high.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random


def build(path: Path, *, salt: str) -> list[dict]:
    episodes = defaultdict(list)
    rows = [json.loads(line) for line in path.open()]
    for row in rows:
        episodes[row["assigned_episode_id"]].append(row)
    long_ids = {key for key, events in episodes.items() if len(events) >= 10}
    shorter = sorted(key for key, events in episodes.items() if 1 < len(events) < 10)
    rng = random.Random(20260929)
    sampled = rng.sample(shorter, min(30, len(shorter)))
    picked = sorted(key for key, events in episodes.items() if len(events) > 1)
    packets = []
    for ep in picked:
        events = episodes[ep]
        key = hashlib.sha256(f"{salt}/{ep}".encode()).hexdigest()[:20]
        packets.append({"review_id": key, "event_count": len(events),
                        "selection_bucket": "ALL_LONG_GE_10" if ep in long_ids else
                        ("SEEDED_SHORT_MULTI_SAMPLE" if ep in sampled else "SHORT_MULTI_PENDING_REVIEW"),
                        "events": [{"message_id": row["message_id"], "timestamp": row["timestamp"],
                                    "participant_id": row["participant_id"], "text": row["text"],
                                    "reply_to_message_id": row["reply_to_message_id"]} for row in events]})
    return packets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--hnr", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    packets = build(args.baseline, salt="baseline") + build(args.hnr, salt="hnr")
    random.Random(20260930).shuffle(packets)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as out:
        for packet in packets:
            out.write(json.dumps(packet, ensure_ascii=False) + "\n")
    args.output.chmod(0o600)
    print({"packets": len(packets), "all_long": sum(p["selection_bucket"] == "ALL_LONG_GE_10" for p in packets),
           "sampled_short_multi": sum(p["selection_bucket"] == "SEEDED_SHORT_MULTI_SAMPLE" for p in packets)})


if __name__ == "__main__":
    main()
