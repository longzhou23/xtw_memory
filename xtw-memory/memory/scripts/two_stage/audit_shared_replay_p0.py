#!/usr/bin/env python3
"""Produce evidence packets, not automatic gold labels, for the paired 150 replay."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "memory/benchmark-results/router-v0.2-shared-backbone-p0"


def main():
    data = json.loads((OUT / "replay-150/results.json").read_text())
    target = OUT / "replay-150/semantic-review.md"
    if target.exists():
        raise SystemExit(f"Existing semantic review must not be overwritten: {target}")
    control = {r["eventId"]: r for r in data["control"]["records"]}
    shared = {r["eventId"]: r for r in data["experiment"]["records"]}
    control_i = {r["rawIndex"]: r for r in control.values()}
    shared_i = {r["rawIndex"]: r for r in shared.values()}
    replies = [r for r in control.values() if r.get("replyTo") in control]
    assert len(replies) == 17
    lines = [
        "# Paired 150-message regression: audit packets (NOT semantic gold)",
        "",
        "This is the consumed regression set, not fresh evidence. Identical input/order, threshold 0.50. "
        "`same` means literal join to the quoted message's *runtime episode*, not semantic correctness. "
        "An already mixed anchor episode can make this statistic look good. Candidate scores "
        "are only recorded for CONTINUE; do not call an absent score on NEW a missing candidate.",
        "",
        "| Reply rawIndex | Anchor rawIndex | Gap | Control decision/ep | Shared decision/ep | Control same? | Shared same? |",
        "| ---: | ---: | ---: | --- | --- | :---: | :---: |",
    ]
    for r in replies:
        s = shared[r["eventId"]]
        c_target, s_target = control[r["replyTo"]], shared[r["replyTo"]]
        gap = r["rawIndex"] - c_target["rawIndex"]
        lines.append(f"| {r['rawIndex']} | {c_target['rawIndex']} | {gap} | "
                     f"{r['decision']}/{r['episodeId']} | {s['decision']}/{s['episodeId']} | "
                     f"{r['episodeId'] == c_target['episodeId']} | "
                     f"{s['episodeId'] == s_target['episodeId']} |")
    c_join = sum(r["episodeId"] == control[r["replyTo"]]["episodeId"] for r in replies)
    s_join = sum(shared[r["eventId"]]["episodeId"] == shared[r["replyTo"]]["episodeId"] for r in replies)
    lines.extend(["", f"Observed literal anchor join: control {c_join}/17; shared {s_join}/17.",
                  "", "## Known targeted mixing / over-merge check", "",
                  "Review messages 10047 (‘够我吃六七顿火锅鸡了’) and 10049 (‘我用privazer’) in context. "
                  "The historical control assigns both to the same episode; its old ‘zero mixing’ report is contradicted by the text. "
                  "A shared model must not be called safe merely because its episode count matches the control.", "",
                  "| rawIndex | Control episode | Shared episode | Same pair? |", "| ---: | --- | --- | :---: |"])
    for i in (10047, 10049):
        lines.append(f"| {i} | {control_i[i]['episodeId']} | {shared_i[i]['episodeId']} | — |")
    pair_same = shared_i[10047]["episodeId"] == shared_i[10049]["episodeId"]
    lines.append(f"\nShared pair is in the same Episode: **{pair_same}**. "
                 "This is a localized warning, not a whole-replay mixing rate.")
    lines.extend(["", "## Known long-span quote anchors (diagnostic only)", "",
                  "Raw indices 10026→10003, 10087→10057, 10097→10085, and 10120→10097 "
                  "are explicit quote relationships separated by ≥12 records. Their observed episode joins "
                  "are shown above; semantic correctness has not been independently adjudicated.", "",
                  "## Outstanding human review", "",
                  "- Inspect any changed episode memberships for confirmed topic mixing, over-merge, and over-split; assign evidence and confidence. "
                  "No zero-error labels have been auto-generated.",
                  "- For failed literal joins, first determine whether the message actually continues the quoted text or a different semantic thread. "
                  "Only then classify candidate missing, Boundary error, Ranking error, or mapping error.",
                  "- Check 10128's A20pro text against the purported solid-waste episode before treating its reply anchor as ground truth.",
                  "- The reference uses the P0 EpisodeRuntime/simple summarizer, not a demonstrated Memory Fabric integration; "
                  "the strict Memory Fabric equivalence claim remains unverified.", ""])
    target.write_text("\n".join(lines))
    print(f"Wrote descriptive review packets to {target}")


if __name__ == "__main__":
    main()
