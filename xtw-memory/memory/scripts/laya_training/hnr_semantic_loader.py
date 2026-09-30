"""Adapt reviewed HNR cases to the frozen native Laya choice serialization.

Training is forbidden unless `hnr_review_gate.py` has created HIGH-confidence
labels. This adapter never reads HN HOLDOUT and never uses weak Teacher gold.
"""
from __future__ import annotations

from memory.scripts.laya_training.data_loader import format_case_to_laya_item


def to_laya_semantic_item(packet: dict, mapped: dict, tokenizer, *, allow_missing: bool = False, allow_holdout: bool = False) -> dict:
    assert mapped["semantic_label"] in ("TRUE_CONTINUE", "TRUE_NEW")
    assert packet["case_id"] == mapped["case_id"]
    assert packet["target_message_id"] == mapped["target_message_id"]
    if not allow_holdout:
        assert mapped["window"] in ("TRAIN", "DEV"), "Trainer must never open HOLDOUT"
    if mapped["semantic_label"] == "TRUE_CONTINUE":
        primary = mapped["primary_positive_candidate_id"]
        if primary:
            assert mapped["positive_available"] and primary in mapped["semantic_positive_candidate_ids"]
            target = "CONTINUE:" + primary
        else:
            assert allow_missing and not mapped["positive_available"], "Cannot train absent positive as negative"
            # DEV only: NEW is a serialization placeholder; no pointwise loss
            # is computed on this unrankable continuation case.
            target = "NEW"
    else:
        assert not mapped["semantic_positive_candidate_ids"]
        target = "NEW"
    candidates = [
        {"candidate_id": c["runtime_episode_id"],
         "messages": [{"text": msg["text"]} for msg in c["recent_messages"]]}
        for c in mapped["candidates"]
    ]
    case = {
        "case_id": packet["case_id"],
        "recent_context": packet["prior_context"][-8:],
        "target": packet["target"],
        "candidate_episodes": candidates,
        "ground_truth": {"label": target},
    }
    item = format_case_to_laya_item(case, tokenizer, permute_options=True)
    keys = item["ordered_keys"]
    positives = set(mapped["semantic_positive_candidate_ids"])
    negatives = {c["runtime_episode_id"] for c in mapped["candidates"]
                 if c["semantic_relation"] == "NEGATIVE"}
    assert not positives.intersection(negatives)
    assert positives.union(negatives) == {c["runtime_episode_id"] for c in mapped["candidates"]}
    item["semantic_label"] = mapped["semantic_label"]
    item["primary_positive_index"] = keys.index(mapped["primary_positive_candidate_id"]) if positives else None
    item["other_positive_indices"] = tuple(i for i, key in enumerate(keys)
                                           if key in positives and key != mapped["primary_positive_candidate_id"])
    item["negative_indices"] = tuple(i for i, key in enumerate(keys) if key in negatives)
    item["new_index"] = keys.index("NEW")
    # Non-input metadata is carried in `collate_items.meta`; input tokenization
    # above includes neither review fields nor hard-negative provenance.
    return item
