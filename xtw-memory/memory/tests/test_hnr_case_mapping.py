import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/laya_training"))
from hnr_case_mapping import map_case


def test_multiple_semantic_positives_never_mined_as_negatives():
    review = {"case_id": "c1", "target_message_id": "target", "review_confidence": "HIGH",
              "semantic_label": "TRUE_CONTINUE", "semantic_thread": "thread",
              "valid_anchor_message_ids": ["a_old", "a_recent"]}
    trace = {"target_message_id": "target", "candidate_count": 4, "candidates": [
        {"runtime_episode_id": "ep_1", "all_episode_message_ids": ["a_old"], "score": 0.1},
        {"runtime_episode_id": "ep_2", "all_episode_message_ids": [], "score": 0.8},
        {"runtime_episode_id": "ep_3", "all_episode_message_ids": ["a_recent"], "score": 0.5},
        {"runtime_episode_id": "ep_4", "all_episode_message_ids": [], "score": 0.2},
    ]}
    indices = {"a_old": 1, "a_recent": 5}
    train = map_case(review, trace, indices, window="TRAIN")
    assert train["primary_positive_candidate_id"] == "ep_3"
    assert train["semantic_positive_candidate_ids"] == ["ep_1", "ep_3"]
    assert {c["runtime_episode_id"] for c in train["candidates"] if c["semantic_relation"] == "NEGATIVE"} == {"ep_2", "ep_4"}
    dev = map_case(review, trace, indices, window="DEV")
    assert len(dev["candidates"]) == 4


def test_true_new_has_only_negatives():
    review = {"case_id": "c2", "target_message_id": "target", "review_confidence": "HIGH",
              "semantic_label": "TRUE_NEW", "semantic_thread": None, "valid_anchor_message_ids": []}
    trace = {"target_message_id": "target", "candidate_count": 3, "candidates": [
        {"runtime_episode_id": f"ep_{i}", "all_episode_message_ids": [], "score": float(i) / 10}
        for i in range(3)]}
    train = map_case(review, trace, {}, window="TRAIN")
    assert train["primary_positive_candidate_id"] is None
    assert not train["semantic_positive_candidate_ids"]
    assert len(train["candidates"]) == 3


def test_missing_anchor_is_not_assigned_to_wrong_episode():
    review = {"case_id": "c3", "target_message_id": "target", "review_confidence": "HIGH",
              "semantic_label": "TRUE_CONTINUE", "semantic_thread": "thread",
              "valid_anchor_message_ids": ["a_old"]}
    trace = {"target_message_id": "target", "candidate_count": 1,
             "candidates": [{"runtime_episode_id": "wrong", "all_episode_message_ids": [], "score": 0.9}]}
    result = map_case(review, trace, {"a_old": 1}, window="HOLDOUT")
    assert result["positive_available"] is False
    assert result["primary_positive_candidate_id"] is None
