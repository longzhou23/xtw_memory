"""Independent candidate-ranking scorer; no checkpoint or trainer imports.

Reads prediction artifacts only AFTER checkpoint selection. The same frozen
case IDs and candidate sets must be evaluated for baseline and HNR. TRUE_NEW
has no ranking-positive denominator; its score distribution is reported
separately rather than miscounted as a ranking error.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import statistics


def score(rows: list[dict]) -> dict:
    assert len(rows) == len({r["case_id"] for r in rows})
    for row in rows:
        ids, scores, raw_logits = row["candidate_ids"], row["scores"], row["raw_logits"]
        assert len(ids) == len(set(ids)) == len(scores) == len(raw_logits)
        assert all(isinstance(x, (float, int)) and 0 <= x <= 1 for x in scores)
        assert all(isinstance(x, (float, int)) and math.isfinite(x) for x in raw_logits)
        assert all((scores[i] - scores[j]) * (raw_logits[i] - raw_logits[j]) >= -1e-6
                   for i in range(len(ids)) for j in range(i)), "Score/logit rank mismatch"
    continue_cases = [r for r in rows if r["semantic_label"] == "TRUE_CONTINUE"]
    true_new = [r for r in rows if r["semantic_label"] == "TRUE_NEW"]
    rankable: list[dict] = []
    failures: Counter[str] = Counter()
    group: dict[str, list[int]] = {k: [] for k in ("1", "2", "3", "4+")}
    gap: dict[str, list[int]] = {k: [] for k in ("0-2", "3-5", "6+")}
    speaker: dict[str, list[int]] = {k: [] for k in ("same", "different")}
    hard: list[int] = []
    mrr: list[float] = []
    top1 = top2 = top3 = 0
    for row in continue_cases:
        ids = row["candidate_ids"]
        scores = row["scores"]
        pos = set(row["semantic_positive_ids"])
        assert pos and pos.issubset(ids) or not pos
        if not pos:
            failures["CANDIDATE_MISSING"] += 1
            continue
        # Match frozen Router's score/ID descending tie policy.
        ranked = sorted(range(len(ids)), key=lambda i: (scores[i], ids[i]), reverse=True)
        rank = next(j for j, i in enumerate(ranked, 1) if ids[i] in pos)
        r1 = int(rank == 1)
        top1 += r1
        top2 += rank <= 2
        top3 += rank <= 3
        mrr.append(1.0 / rank)
        bucket = str(len(ids)) if len(ids) <= 3 else "4+"
        group[bucket].append(r1)
        if row.get("long_gap_bucket") is not None:
            assert row["long_gap_bucket"] in gap
            gap[row["long_gap_bucket"]].append(r1)
        if row.get("positive_same_speaker") is not None:
            speaker["same" if row["positive_same_speaker"] else "different"].append(r1)
        if row.get("hard_negative_present"):
            hard.append(r1)
        best = scores[ranked[0]]
        second = scores[ranked[1]] if len(ranked) > 1 else None
        if rank != 1:
            failures["RANK_WRONG"] += 1
        elif best >= 0.55 or (second is not None and best >= 0.25 and best - second >= 0.15):
            failures["CORRECT"] += 1
        elif second is not None and best >= 0.25:
            failures["MARGIN_TOO_SMALL"] += 1
        else:
            failures["SCORE_TOO_LOW"] += 1
        rankable.append(row)
    n = len(rankable)
    new_max = [max(r["scores"]) if r["scores"] else 0.0 for r in true_new]
    return {
        "cases": len(rows), "true_continue": len(continue_cases), "true_new": len(true_new),
        "candidate_coverage": n / len(continue_cases) if continue_cases else None,
        "rankable_continue_count": n,
        "top1": top1 / n if n else None,
        "top2": top2 / n if n else None,
        "top3": top3 / n if n else None,
        "mrr": statistics.mean(mrr) if mrr else None,
        "hard_negative_top1": statistics.mean(hard) if hard else None,
        "hard_negative_count": len(hard),
        "by_candidate_count": {k: {"count": len(values), "top1": statistics.mean(values) if values else None}
                               for k, values in group.items()},
        "by_long_gap": {k: {"count": len(values), "top1": statistics.mean(values) if values else None}
                        for k, values in gap.items()},
        "by_positive_speaker": {k: {"count": len(values), "top1": statistics.mean(values) if values else None}
                                for k, values in speaker.items()},
        "true_new_max_score": {"count": len(new_max), "mean": statistics.mean(new_max) if new_max else None,
                               "eligible_high_threshold": sum(x >= 0.55 for x in new_max)},
        "failure_taxonomy": {k: failures[k] for k in
                             ("CANDIDATE_MISSING", "RANK_WRONG", "SCORE_TOO_LOW", "MARGIN_TOO_SMALL", "CORRECT")},
    }


def compare(baseline: list[dict], ranking: list[dict]) -> dict:
    a = {r["case_id"]: r for r in baseline}
    b = {r["case_id"]: r for r in ranking}
    assert len(a) == len(b) == len(baseline) == len(ranking), "Missing or duplicate cases"
    assert set(a) == set(b)
    for cid in a:
        left, right = a[cid], b[cid]
        for key in ("candidate_ids", "semantic_positive_ids", "semantic_label", "hard_negative_present",
                    "long_gap_bucket", "positive_same_speaker"):
            assert left.get(key) == right.get(key), f"Denominator or candidate drift: {cid} {key}"
    first, second = score(baseline), score(ranking)
    return {"baseline": first, "hnr": second,
            "delta": {k: (second[k] - first[k] if first[k] is not None and second[k] is not None else None)
                      for k in ("top1", "top2", "top3", "mrr", "hard_negative_top1")}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--ranking", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    def read(path: Path) -> list[dict]:
        with path.open() as stream:
            return [json.loads(line) for line in stream]
    result = compare(read(args.baseline), read(args.ranking))
    assert not args.output.exists(), "Independent metric result must not be overwritten"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
