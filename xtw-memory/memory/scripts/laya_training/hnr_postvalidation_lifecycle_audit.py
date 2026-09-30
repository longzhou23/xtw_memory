"""Read-only reconstruction of frozen Episode lifecycle and scored candidate sets.

Structural invariants and direct-reply association diagnostics are not semantic gold.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
import argparse
import hashlib
import json
from pathlib import Path
import statistics

EXPECTED_RUNTIME_SHA256 = "c394e2e37daee853451deb8636b19672d5631a2d3c06b69fee230b196fd226db"


def audit(path: Path) -> tuple[dict, dict[str, dict]]:
    rows = [json.loads(line) for line in path.open()]
    assert len(rows) == len({row["message_id"] for row in rows}) == 2000
    episodes: dict[str, list] = {}  # id -> [last_event_at, open]
    event_to_episode: dict[str, str] = {}
    events: dict[str, dict] = {}
    ttl_closures = 0
    empty_score_events = 0
    for index, row in enumerate(rows):
        timestamp = datetime.fromisoformat(row["timestamp"])
        for state in episodes.values():
            if state[1] and state[0] + timedelta(days=3) <= timestamp:
                state[1] = False
                ttl_closures += 1
        open_ids = [key for key, state in episodes.items() if state[1]]
        anchor = event_to_episode.get(row["reply_to_message_id"])
        expected = [anchor] if anchor in open_ids else []
        for episode_id in sorted(open_ids, key=lambda key: episodes[key][0], reverse=True):
            if episode_id not in expected:
                expected.append(episode_id)
            if len(expected) >= 8:
                break
        expected = expected[:8]
        scored = list(row["candidate_scores"])
        if not scored:
            empty_score_events += 1
            assert not expected, (path.name, index, "nonempty candidate list had no usable scores")
        else:
            assert scored == expected, (path.name, index, "scored candidates differ from frozen reply-first/top-8 builder")
        decision = row["decision"]
        episode_id = row["assigned_episode_id"]
        if decision == "NEW":
            assert episode_id not in episodes and row["episode_id"] is None
            assert episode_id == f"runtime_ep_{len(episodes) + 1}"
            episodes[episode_id] = [timestamp, True]
        else:
            assert decision == "CONTINUE" and episode_id in episodes and episodes[episode_id][1]
            assert row["episode_id"] == episode_id and episode_id in scored
            episodes[episode_id][0] = timestamp
        event_to_episode[row["message_id"]] = episode_id
        events[row["message_id"]] = row

    reply = Counter()
    split_continue_basis = Counter()
    wrong_best = []
    anchor_scores = []
    for row in rows:
        target = events.get(row["reply_to_message_id"])
        if target is None:
            continue
        anchor_id = target["assigned_episode_id"]
        assert anchor_id in row["candidate_scores"]
        joined = row["assigned_episode_id"] == anchor_id
        reply[("joined" if joined else "split", row["decision"])] += 1
        if not joined:
            anchor_scores.append(row["candidate_scores"][anchor_id])
            if row["decision"] == "CONTINUE":
                split_continue_basis[row["decision_basis"]] += 1
                wrong_best.append(row["best_score"])
    assert sum(reply.values()) == 184
    return ({"audit_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
             "episode_count": len(episodes), "ttl_closures_reconstructed": ttl_closures,
             "empty_score_events": empty_score_events,
             "candidate_builder_mismatches": 0, "selected_closed_episode_violations": 0,
             "creation_or_assignment_violations": 0,
             "reply_edges": 184, "reply_anchor_missing_from_scored_candidates": 0,
             "reply_joined_continue": reply[("joined", "CONTINUE")],
             "reply_split_continue_to_wrong_episode": reply[("split", "CONTINUE")],
             "reply_split_continue_basis": dict(split_continue_basis),
             "reply_split_new": reply[("split", "NEW")],
             "wrong_episode_continue_best_score_median": statistics.median(wrong_best),
             "split_reply_anchor_score_median": statistics.median(anchor_scores)}, events)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    runtime_source = Path(__file__).resolve().parents[3] / "xtw-playground/xtw_core/episode_router/p0.py"
    assert hashlib.sha256(runtime_source.read_bytes()).hexdigest() == EXPECTED_RUNTIME_SHA256
    folder = args.evaluation
    arms = {}
    for arm in ("baseline", "hnr-055"):
        arms[arm], events = audit(folder / f"post-validation-replay-{arm}-events.jsonl")
        if arm == "hnr-055":
            hnr_events = events
    verdicts = Counter()
    hashes = {}
    for batch in range(1, 4):
        path = folder / f"post-validation-blind-reply-split-merged-{batch:03d}.json"
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        for verdict in json.loads(path.read_text())["decisions"]:
            if verdict["label"] != "TRUE_CONTINUE":
                continue
            row = hnr_events[verdict["review_id"]]
            anchor = hnr_events[row["reply_to_message_id"]]["assigned_episode_id"]
            assert row["assigned_episode_id"] != anchor and anchor in row["candidate_scores"]
            verdicts[row["decision"]] += 1
    assert verdicts == {"CONTINUE": 33, "NEW": 6}
    output = {
        "scope": "Frozen default TTL 3 days, reply-first and most-recent top-8 builder reconstructed "
                 "from existing audit logs; no model inference or source modification",
        "runtime_source_sha256": EXPECTED_RUNTIME_SHA256,
        "replay_arms": arms, "reply_verdict_sha256": hashes,
        "independently_confirmed_true_continue_split_links": {
            "count": sum(verdicts.values()), "wrong_episode_continue": verdicts["CONTINUE"],
            "new_despite_anchor_candidate": verdicts["NEW"]},
        "interpretation": "Reply anchors remain eligible and scored for all 184 links; scoring/ranking "
                          "of on-policy candidates and routing boundary must be treated separately. "
                          "TTL closure is not a memory spill; memory-spill events were not instrumented. "
                          "Direct replies are not complete semantic gold."
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"arms": arms, "confirmed_split_breakdown": output[
        "independently_confirmed_true_continue_split_links"]}, indent=2))


if __name__ == "__main__":
    main()
