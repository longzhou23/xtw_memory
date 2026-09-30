"""Map semantic *message anchors* to runtime candidate positives.

This module does not create semantic truth. It only joins independently
reviewed HIGH-confidence anchors with a frozen baseline candidate trace.
Hard-negative selection is permitted for TRAIN only; DEV/HOLDOUT keep every
naturally occurring candidate without baseline-error sampling.
"""
from __future__ import annotations

from hashlib import sha256
import random


def negative_provenance(candidate: dict, *, top_wrong_id: str | None) -> str:
    if candidate["runtime_episode_id"] == top_wrong_id:
        return "MODEL_TOP_WRONG"
    if candidate.get("same_speaker"):
        return "SAME_SPEAKER"
    if candidate.get("lexical_overlap_count", 0) > 0:
        return "LEXICAL_SIMILAR"
    seconds = candidate.get("temporal_distance_seconds")
    if seconds is not None and seconds <= 180:
        return "TEMPORAL_NEAR"
    if seconds is not None and seconds >= 1800:
        return "LONG_GAP_DISTRACTOR"
    return "OTHER"


def map_case(review: dict, trace: dict, sequence_indices: dict[str, int], *, window: str) -> dict:
    assert window in ("TRAIN", "DEV", "HOLDOUT")
    assert review["review_confidence"] == "HIGH"
    assert review["semantic_label"] in ("TRUE_NEW", "TRUE_CONTINUE")
    assert review["target_message_id"] == trace["target_message_id"]
    candidates = trace["candidates"]
    assert len(candidates) == trace["candidate_count"]
    assert len({c["runtime_episode_id"] for c in candidates}) == len(candidates)
    anchors = set(review["valid_anchor_message_ids"])
    assert (review["semantic_label"] == "TRUE_CONTINUE") == bool(anchors)
    matched: dict[str, list[str]] = {}
    for candidate in candidates:
        hits = sorted(anchors.intersection(candidate["all_episode_message_ids"]),
                      key=lambda mid: sequence_indices[mid])
        if hits:
            matched[candidate["runtime_episode_id"]] = hits
    assert len(set(mid for hits in matched.values() for mid in hits)) == sum(map(len, matched.values()))
    positives = set(matched)
    # Most recent legitimate anchor wins; other positives must be ignored.
    primary_id = (max(matched, key=lambda cid: max(sequence_indices[mid] for mid in matched[cid]))
                  if matched else None)
    negatives = [c for c in candidates if c["runtime_episode_id"] not in positives]
    # Do not mine DEV/HOLDOUT. TRAIN keeps up to two scored distractors, plus
    # one optional easier candidate from a stable case-specific shuffle.
    scored = sorted(negatives, key=lambda c: (-float(c["score"]), c["runtime_episode_id"]))
    best_positive_score = max((float(c["score"]) for c in candidates
                               if c["runtime_episode_id"] in positives), default=float("-inf"))
    top_wrong = (scored[0]["runtime_episode_id"]
                 if scored and (review["semantic_label"] == "TRUE_NEW" or positives)
                 and float(scored[0]["score"]) > best_positive_score else None)
    if window == "TRAIN":
        chosen = scored[:2]
        if len(scored) > 2:
            rest = scored[2:]
            seed = int(sha256(review["case_id"].encode()).hexdigest()[:16], 16)
            chosen.append(random.Random(seed).choice(rest))
    else:
        chosen = candidates  # full natural candidate set, no error mining
    selected_ids = {c["runtime_episode_id"] for c in chosen}
    # TRAIN positives are always retained; explicit NEW has no positive.
    if window == "TRAIN":
        selected_ids.update(positives)
    out_candidates = [
        {**c,
         "semantic_relation": "POSITIVE" if c["runtime_episode_id"] in positives else "NEGATIVE",
         "negative_provenance": (None if c["runtime_episode_id"] in positives else
                                 negative_provenance(c, top_wrong_id=top_wrong))}
        for c in candidates if c["runtime_episode_id"] in selected_ids
    ]
    assert {c["runtime_episode_id"] for c in out_candidates if c["semantic_relation"] == "POSITIVE"} == positives
    natural_hard_negative = any(
        c["runtime_episode_id"] not in positives
        and (c.get("same_speaker") or c.get("lexical_overlap_count", 0) > 0
             or (c.get("temporal_distance_seconds") is not None
                 and c["temporal_distance_seconds"] <= 180))
        for c in candidates
    )
    return {
        "case_id": review["case_id"],
        "target_message_id": review["target_message_id"],
        "window": window,
        "semantic_label": review["semantic_label"],
        "semantic_thread": review["semantic_thread"],
        "valid_anchor_message_ids": sorted(anchors, key=lambda mid: sequence_indices[mid]),
        "semantic_positive_candidate_ids": sorted(positives),
        "primary_positive_candidate_id": primary_id,
        "positive_available": bool(primary_id),
        # Fixed from semantic positives + natural attributes, not selected by
        # either checkpoint's correctness on DEV/HOLDOUT.
        "hard_negative_present": bool(primary_id and natural_hard_negative and len(candidates) >= 2),
        "candidate_count_unmined": len(candidates),
        "candidates": out_candidates,
    }
