"""CPU-only loss/gradient checks; not a model-performance smoke test."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/laya_training"))

import torch
import torch.nn.functional as F

from hnr_objective import semantic_case_loss, weak_pointwise_loss


def test_hard_negative_gradient_directions():
    scores = torch.tensor([0.2, 1.1, -0.4, 0.0], requires_grad=True)
    _, _, rank = semantic_case_loss(
        scores, label="TRUE_CONTINUE", primary_positive=0,
        negative_indices=(1, 2), new_index=3,
    )
    rank.backward()
    assert torch.isfinite(rank)
    assert scores.grad[0] < 0  # gradient descent increases positive logit
    assert scores.grad[1] > 0 and scores.grad[2] > 0  # lowers negatives


def test_other_semantic_positive_is_ignored():
    scores = torch.tensor([0.2, 5.0, 1.1, 0.0], requires_grad=True)
    total, pointwise, rank = semantic_case_loss(
        scores, label="TRUE_CONTINUE", primary_positive=0,
        other_positives=(1,), negative_indices=(2,), new_index=3,
    )
    total.backward()
    assert torch.isfinite(total) and torch.isfinite(rank)
    assert scores.grad[1] == 0
    assert rank == F.softplus(scores.detach()[2] - scores.detach()[0])


def test_true_new_has_no_ranking_loss():
    scores = torch.tensor([0.1, 2.0, -1.0], requires_grad=True)
    total, pointwise, rank = semantic_case_loss(
        scores, label="TRUE_NEW", primary_positive=None,
        negative_indices=(0, 1), new_index=2,
    )
    assert rank == 0 and total == pointwise
    total.backward()
    assert scores.grad[0] > 0 and scores.grad[1] > 0


def test_weak_loss_is_original_cross_entropy():
    logits = torch.tensor([[0.2, 0.8], [0.3, -0.5]])
    labels = torch.tensor([1, 0])
    assert torch.equal(weak_pointwise_loss(logits, labels), F.cross_entropy(logits, labels))
