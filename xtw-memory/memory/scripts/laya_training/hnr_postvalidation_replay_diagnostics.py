"""Descriptive structural diagnostics for two immutable 2000-event replays.

Reply edges are direct structural evidence, not a complete semantic gold set.
Neither within-episode replies nor episode counts prove absence of over-merge.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open()]


def diagnostics(events: list[dict]) -> dict:
    by_id = {row["message_id"]: row for row in events}
    assert len(events) == len(by_id) == 2000
    episodes: dict[str, list[dict]] = defaultdict(list)
    for row in events:
        episodes[row["assigned_episode_id"]].append(row)
    replies = [row for row in events if row["reply_to_message_id"] in by_id]
    cross = [row for row in replies if by_id[row["reply_to_message_id"]]["assigned_episode_id"] != row["assigned_episode_id"]]
    # Gap buckets are descriptive only: the protocol has no established semantic
    # long-gap gold labels for these events.
    intervals = []
    for row in replies:
        anchor = by_id[row["reply_to_message_id"]]
        gap = (datetime.fromisoformat(row["timestamp"]) - datetime.fromisoformat(anchor["timestamp"])).total_seconds()
        assert gap >= 0
        intervals.append((row, gap))
    over_30 = [(r, gap) for r, gap in intervals if gap >= 1800]
    return {"episode_count": len(episodes), "multi_event_episodes": sum(len(v) > 1 for v in episodes.values()),
            "long_episodes_ge_10": sum(len(v) >= 10 for v in episodes.values()),
            "events_in_long_episodes_ge_10": sum(len(v) for v in episodes.values() if len(v) >= 10),
            "same_window_reply_edges": len(replies), "reply_cross_episode": len(cross),
            "reply_cross_episode_rate": len(cross)/len(replies) if replies else None,
            "long_gap_reply_edges_ge_30min": len(over_30),
            "long_gap_reply_cross_episode": sum(r in cross for r, _ in over_30),
            "decision_distribution": dict(Counter(r["decision"] for r in events)),
            "reply_cross_episode_examples": [{"message_id": r["message_id"], "reply_to": r["reply_to_message_id"],
                                               "text": r["text"][:180], "anchor_text": by_id[r["reply_to_message_id"]]["text"][:180]}
                                              for r in cross[:20]],
            "large_episode_preview": [{"episode_id": ep, "count": len(rows),
                                       "messages": [{"id": r["message_id"], "text": r["text"][:130]}
                                                    for r in rows[:12]]}
                                      for ep, rows in sorted(episodes.items(), key=lambda item: -len(item[1]))[:10]]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--hnr", type=Path, required=True)
    parser.add_argument("--baseline-summary", type=Path, required=True)
    parser.add_argument("--hnr-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    summaries = [json.loads(p.read_text()) for p in (args.baseline_summary, args.hnr_summary)]
    assert summaries[0]["input_sha256"] == summaries[1]["input_sha256"]
    a, b = load(args.baseline), load(args.hnr)
    assert [x["message_id"] for x in a] == [x["message_id"] for x in b]
    out = {"input_sha256": summaries[0]["input_sha256"], "baseline": diagnostics(a), "hnr_055": diagnostics(b),
           "interpretation_limit": "Reply links are a partial structural proxy, NOT exhaustive semantic thread gold; over-merge and over-split rates remain unestablished until blinded semantic review."}
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print({name: {k: value for k, value in out[name].items() if k not in ("reply_cross_episode_examples", "large_episode_preview")}
           for name in ("baseline", "hnr_055")})


if __name__ == "__main__":
    main()
