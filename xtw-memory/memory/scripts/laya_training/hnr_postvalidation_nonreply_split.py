"""Enumerate a reply-free, same-speaker split proxy in frozen replay audits.

This is a structural screen, not semantic ground truth or a threshold selector.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--hnr", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    original = [json.loads(line) for line in args.baseline.open()]
    ranked = [json.loads(line) for line in args.hnr.open()]
    assert len(original) == len(ranked) == 2000
    assert len({row["message_id"] for row in original}) == len(original)
    assert all(a["message_id"] == b["message_id"] and a["text"] == b["text"]
               and a["timestamp"] == b["timestamp"] for a, b in zip(original, ranked))

    latest_by_speaker: dict[str, int] = {}
    screened = []
    split = []
    for index, (base, hnr) in enumerate(zip(original, ranked)):
        speaker = base["participant_id"]
        earlier = latest_by_speaker.get(speaker)
        latest_by_speaker[speaker] = index
        if earlier is None or speaker == "p_system":
            continue
        old_base, old_hnr = original[earlier], ranked[earlier]
        gap = (datetime.fromisoformat(base["timestamp"])
               - datetime.fromisoformat(old_base["timestamp"])).total_seconds()
        if not (0 <= gap <= 120) or base["reply_to_message_id"] or old_base["reply_to_message_id"]:
            continue
        if old_base["assigned_episode_id"] != base["assigned_episode_id"]:
            continue
        pair = {"earlier_message_id": old_base["message_id"], "later_message_id": base["message_id"],
                "gap_seconds": gap, "earlier_text": old_base["text"], "later_text": base["text"],
                "hnr_decision": hnr["decision"],
                "hnr_same_episode": old_hnr["assigned_episode_id"] == hnr["assigned_episode_id"]}
        screened.append(pair)
        if not pair["hnr_same_episode"]:
            split.append(pair)

    result = {"scope": "All 2,000 replay events; consecutive messages by the same speaker within 120 seconds, "
                       "both without explicit reply IDs, baseline co-assigned; system speaker excluded",
              "semantic_gold": False,
              "baseline_audit_sha256": hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
              "hnr_audit_sha256": hashlib.sha256(args.hnr.read_bytes()).hexdigest(),
              "baseline_coassigned_eligible_pairs": len(screened),
              "hnr_separated_pairs": len(split),
              "hnr_separated_by_decision": {label: sum(p["hnr_decision"] == label for p in split)
                                             for label in ("NEW", "CONTINUE", "UNKNOWN")},
              "separated_pairs": split,
              "interpretation": "Only a deterministic suspected-split screen. Same speaker and temporal proximity "
                                "do not establish a shared semantic thread; baseline co-assignment may also be wrong."}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    args.output.chmod(0o600)
    print(json.dumps({k: result[k] for k in ("baseline_coassigned_eligible_pairs",
                                            "hnr_separated_pairs", "hnr_separated_by_decision")}, indent=2))


if __name__ == "__main__":
    main()
