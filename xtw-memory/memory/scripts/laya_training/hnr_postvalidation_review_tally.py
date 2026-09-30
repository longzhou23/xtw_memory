"""Recount the six frozen double-blind merged Episode reviews against replay.

Conservative confirmed lower bounds only: unreviewed/unresolved != coherent.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    folder = args.evaluation
    sizes = {}
    input_hashes = {}
    for arm in ("baseline", "hnr-055"):
        path = folder / f"post-validation-replay-{arm}-events.jsonl"
        rows = [json.loads(line) for line in path.open()]
        assert len(rows) == len({row["message_id"] for row in rows}) == 2000
        sizes[arm] = Counter(row["assigned_episode_id"] for row in rows)
        input_hashes[path.name] = digest(path)

    decisions = defaultdict(list)
    for batch in range(1, 7):
        path = folder / f"post-validation-blind-review-merged-{batch:03d}.json"
        input_hashes[path.name] = digest(path)
        for item in json.loads(path.read_text())["decisions"]:
            arm, episode = item["arm"], item["episode_id"]
            assert arm in sizes and sizes[arm][episode] >= 2
            decisions[arm].append(item)

    result = {"scope": "135 reviewed of 540 multi-event Episodes, all >=10-event Episodes included",
              "whole_population_mixing_rate_estimated": False,
              "input_sha256": input_hashes, "arms": {}}
    assert sum(len(rows) for rows in decisions.values()) == 135
    for arm in ("baseline", "hnr-055"):
        records = decisions[arm]
        assert len({x["episode_id"] for x in records}) == len(records)
        labels = Counter(x["merged_label"] for x in records)
        mixed = [x for x in records if x["merged_label"] == "OVER_MERGE"]
        assert all(x["review_a"]["label"] == x["review_b"]["label"] == "OVER_MERGE"
                   and x["review_a"]["confidence"] == x["review_b"]["confidence"] == "HIGH"
                   for x in mixed)
        long = [x for x in records if sizes[arm][x["episode_id"]] >= 10]
        long_labels = Counter(x["merged_label"] for x in long)
        assert len(long) == sum(size >= 10 for size in sizes[arm].values())
        result["arms"][arm] = {
            "total_episodes": len(sizes[arm]),
            "multi_event_episodes": sum(size >= 2 for size in sizes[arm].values()),
            "reviewed_episodes": len(records), "reviewed_labels": dict(labels),
            "confirmed_mixed_episode_count_lower_bound": len(mixed),
            "events_contained_in_confirmed_mixed_episodes": sum(sizes[arm][x["episode_id"]]
                                                             for x in mixed),
            "confirmed_mixed_episode_fraction_lower_bound": len(mixed) / len(sizes[arm]),
            "contained_event_fraction_lower_bound": sum(sizes[arm][x["episode_id"]] for x in mixed) / 2000,
            "fully_enumerated_long_stratum": {"episode_count": len(long),
                                             "labels": dict(long_labels)},
        }
    by_id = {row["message_id"]: row for row in
             (json.loads(line) for line in (folder / "post-validation-replay-hnr-055-events.jsonl").open())}
    reply_decisions = []
    for batch in range(1, 4):
        path = folder / f"post-validation-blind-reply-split-merged-{batch:03d}.json"
        input_hashes[path.name] = digest(path)
        reply_decisions.extend(json.loads(path.read_text())["decisions"])
    assert len(reply_decisions) == 61
    reply_labels = Counter(x["label"] for x in reply_decisions)
    confirmed = [x for x in reply_decisions if x["label"] == "TRUE_CONTINUE"]
    involved = set()
    for verdict in confirmed:
        child = by_id[verdict["review_id"]]
        anchor = by_id[child["reply_to_message_id"]]
        assert child["assigned_episode_id"] != anchor["assigned_episode_id"]
        assert verdict["review_a"]["label"] == verdict["review_b"]["label"] == "TRUE_CONTINUE"
        assert verdict["review_a"]["confidence"] == verdict["review_b"]["confidence"] == "HIGH"
        involved.update((child["assigned_episode_id"], anchor["assigned_episode_id"]))
    result["targeted_reply_split_review"] = {
        "reviewed_links": len(reply_decisions), "labels": dict(reply_labels),
        "confirmed_split_links": len(confirmed),
        "distinct_hnr_episodes_touching_confirmed_split_links": len(involved),
        "scope_note": "Priority-selected direct reply links; shared semantic threads may overlap. "
                      "Do not infer a population over-split rate or independent thread count."}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["arms"], indent=2))


if __name__ == "__main__":
    main()
