import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/laya_training"))
from hnr_independent_ranking_score import compare


def test_metrics_and_fixed_denominators():
    cont = {"case_id": "c1", "candidate_ids": ["a", "b"], "semantic_positive_ids": ["b"],
            "semantic_label": "TRUE_CONTINUE", "hard_negative_present": True}
    new = {"case_id": "c2", "candidate_ids": ["x"], "semantic_positive_ids": [],
           "semantic_label": "TRUE_NEW", "hard_negative_present": False}
    missing = {"case_id": "c3", "candidate_ids": ["z"], "semantic_positive_ids": [],
               "semantic_label": "TRUE_CONTINUE", "hard_negative_present": False}
    old = [dict(cont, scores=[0.9, 0.5], raw_logits=[2.0, 0.0]),
           dict(new, scores=[0.7], raw_logits=[1.0]),
           dict(missing, scores=[0.9], raw_logits=[2.0])]
    hnr = [dict(cont, scores=[0.4, 0.8], raw_logits=[0.0, 2.0]),
           dict(new, scores=[0.2], raw_logits=[0.0]),
           dict(missing, scores=[0.1], raw_logits=[-2.0])]
    result = compare(old, hnr)
    assert result["baseline"]["candidate_coverage"] == 0.5
    assert result["baseline"]["top1"] == 0
    assert result["hnr"]["top1"] == result["hnr"]["mrr"] == 1
    assert result["delta"]["top1"] == 1
    assert result["hnr"]["failure_taxonomy"]["CANDIDATE_MISSING"] == 1


def test_candidate_drift_is_rejected():
    old = [{"case_id": "x", "candidate_ids": ["a"], "scores": [0.1], "raw_logits": [-1.0],
            "semantic_positive_ids": ["a"], "semantic_label": "TRUE_CONTINUE"}]
    new = [dict(old[0], candidate_ids=["b"])]
    try:
        compare(old, new)
    except AssertionError:
        return
    raise AssertionError("Candidate drift accepted")
