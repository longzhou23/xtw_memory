"""Read-only exact decision and direct-reply transition audit for two frozen replays.

Counts are structural observations, never gold semantic quality estimates.
"""
from __future__ import annotations

from collections import Counter
import argparse
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
    baseline = [json.loads(line) for line in args.baseline.open()]
    hnr = [json.loads(line) for line in args.hnr.open()]
    assert len(baseline) == len(hnr) == 2000
    assert len({x["message_id"] for x in baseline}) == 2000
    assert len({x["message_id"] for x in hnr}) == 2000
    assert all(tuple(a[k] for k in ("message_id", "timestamp", "text", "participant_id", "reply_to_message_id"))
               == tuple(b[k] for k in ("message_id", "timestamp", "text", "participant_id", "reply_to_message_id"))
               for a, b in zip(baseline, hnr))
    old = {x["message_id"]: x for x in baseline}
    new = {x["message_id"]: x for x in hnr}
    decisions = Counter((a["decision"], b["decision"]) for a, b in zip(baseline, hnr))
    states = Counter()
    routing = Counter()
    reply_edges = 0
    for a, b in zip(baseline, hnr):
        reply_to = a["reply_to_message_id"]
        if reply_to not in old:
            continue
        reply_edges += 1
        baseline_joined = a["assigned_episode_id"] == old[reply_to]["assigned_episode_id"]
        hnr_joined = b["assigned_episode_id"] == new[reply_to]["assigned_episode_id"]
        states[(baseline_joined, hnr_joined)] += 1
        routing[(baseline_joined, hnr_joined, b["decision"])] += 1
    assert reply_edges == 184
    assert sum(decisions.values()) == 2000
    assert sum(states.values()) == sum(routing.values()) == reply_edges
    assert sum(count for (before, after), count in decisions.items() if after == "NEW") - sum(
        count for (before, after), count in decisions.items() if before == "NEW") == 318 - 1161
    result = {
        "scope": "Exact paired event/decision and direct-reply co-assignment transitions; no semantic gold",
        "baseline_audit_sha256": hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
        "hnr_audit_sha256": hashlib.sha256(args.hnr.read_bytes()).hexdigest(),
        "event_count": 2000,
        "decision_transitions": {f"{a}->{b}": decisions[(a, b)] for a in ("NEW", "CONTINUE", "UNKNOWN")
                                 for b in ("NEW", "CONTINUE", "UNKNOWN")},
        "new_difference_hnr_minus_baseline": 318 - 1161,
        "direct_reply_edges": reply_edges,
        "reply_coassignment_transitions": {
            f"baseline_{'joined' if a else 'split'}__hnr_{'joined' if b else 'split'}": states[(a, b)]
            for a in (True, False) for b in (True, False)},
        "hnr_split_reply_decision": {decision: sum(count for (a, joined, d), count in routing.items()
                                                 if not joined and d == decision)
                                     for decision in ("NEW", "CONTINUE", "UNKNOWN")},
        "interpretation": "881 baseline NEW events became HNR CONTINUE, versus 38 the other way: net 843 fewer "
                          "NEW decisions. Among 184 direct reply edges HNR loses 61 baseline joins and gains "
                          "10 baseline splits; 67 of HNR's 75 reply separations are CONTINUE to another "
                          "Episode. Neither mapping proves a semantic thread should join or split."}
    assert result["decision_transitions"]["NEW->CONTINUE"] == 881
    assert result["decision_transitions"]["CONTINUE->NEW"] == 38
    assert result["hnr_split_reply_decision"] == {"NEW": 8, "CONTINUE": 67, "UNKNOWN": 0}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["reply_coassignment_transitions"], indent=2))


if __name__ == "__main__":
    main()
