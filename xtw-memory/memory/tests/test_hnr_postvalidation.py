"""Policy and structural-proxy regression tests; no GPU or HOLDOUT required."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from memory.scripts.laya_training.hnr_postvalidation_calibrate import clarify_coverage, evaluate
from memory.scripts.laya_training.hnr_postvalidation_replay_diagnostics import diagnostics


def test_margin_continue_below_high_threshold() -> None:
    rows = [
        {"scores": [.30, .10], "candidate_ids": ["a", "b"],
         "semantic_label": "TRUE_NEW", "semantic_positive_ids": []},
        {"scores": [.30, .10], "candidate_ids": ["a", "b"],
         "semantic_label": "TRUE_CONTINUE", "semantic_positive_ids": ["a"]},
    ]
    metrics = evaluate(rows, .8)
    assert metrics["false_continue"] == 1
    assert metrics["candidate_top1_accuracy"] == 1.0


def test_decision_coverage_is_not_continue_rate() -> None:
    rows = [
        {"scores": [.1, .08], "candidate_ids": ["a", "b"],
         "semantic_label": "TRUE_NEW", "semantic_positive_ids": []},
        {"scores": [.9, .2], "candidate_ids": ["a", "b"],
         "semantic_label": "TRUE_CONTINUE", "semantic_positive_ids": ["a"]},
    ]
    metrics = clarify_coverage(evaluate(rows, .55))
    assert metrics["decision_coverage"] == 1.0
    assert metrics["continue_candidate_coverage"] == 1.0
    assert metrics["predicted_continue_rate"] == metrics["routing_coverage"] == .5


def test_explicit_reply_cross_episode_is_only_a_proxy() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    events = [{"message_id": f"m_{i}", "assigned_episode_id": "a" if i == 0 else "b",
               "reply_to_message_id": "m_0" if i == 1 else None,
               "timestamp": (start + timedelta(seconds=i)).isoformat(),
               "decision": "NEW", "text": "test"} for i in range(2000)]
    result = diagnostics(events)
    assert result["same_window_reply_edges"] == 1
    assert result["reply_cross_episode"] == 1
    assert result["reply_cross_episode_rate"] == 1.0
