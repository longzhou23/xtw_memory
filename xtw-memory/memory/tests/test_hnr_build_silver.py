import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/laya_training"))
from hnr_build_silver import select_natural, select_train


def test_training_minimum_and_natural_order():
    cont = [
        {"mapped": {"semantic_label": "TRUE_CONTINUE", "positive_available": True,
                    "case_id": f"c_{i:04d}", "candidate_count_unmined": 2,
                    "semantic_positive_candidate_ids": ["good"],
                    "candidates": [{"runtime_episode_id": "good", "score": 0.3},
                                   {"runtime_episode_id": "wrong", "score": 0.8}]}}
        for i in range(800)
    ]
    new = [
        {"mapped": {"semantic_label": "TRUE_NEW", "positive_available": False,
                    "case_id": f"n_{i:04d}", "candidate_count_unmined": 1,
                    "semantic_positive_candidate_ids": [],
                    "candidates": [{"runtime_episode_id": "wrong", "score": 0.7}]}}
        for i in range(50)
    ]
    train = select_train(cont + new)
    assert len(train) == 850
    assert sum(row["mapped"]["semantic_label"] == "TRUE_NEW" for row in train) == 50
    assert select_natural(new, count=40, minimum=30) == new[:40]


def test_training_missing_positives_cannot_fill_quota():
    missing = [{"mapped": {"semantic_label": "TRUE_CONTINUE", "positive_available": False}}
               for _ in range(800)]
    try:
        select_train(missing)
    except RuntimeError as exc:
        assert "DATASET_TOO_SMALL" in str(exc)
    else:
        raise AssertionError("Missing candidates silently counted as trainable positives")
