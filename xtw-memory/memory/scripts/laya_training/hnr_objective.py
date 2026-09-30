"""HNR choice-logit objective without modifying the frozen Laya architecture.

The 20K baseline already uses native choice logits and cross-entropy (not a
per-candidate sigmoid head). Preserve its original weak loss exactly. For
semantic cases use the same native pointwise choice loss, excluding additional
semantic-positive candidates from the CE denominator, and add pairwise
softplus(negative_logit - primary_positive_logit) for CONTINUE only.
"""
from __future__ import annotations

import torch
import torch.nn.functional as F


def semantic_case_loss(
    logits: torch.Tensor,
    *,
    label: str,
    primary_positive: int | None,
    other_positives: tuple[int, ...] = (),
    negative_indices: tuple[int, ...],
    new_index: int,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Return total, pointwise CE, and mean pairwise ranking loss for one case.

    The ``negative_indices`` must contain only reviewed semantic negatives.
    Non-candidate options (e.g. NEW, UNKNOWN) remain in the original choice
    denominator, but are not hard-negative pairs.
    """
    assert logits.ndim == 1 and logits.numel() >= 2
    assert label in ("TRUE_CONTINUE", "TRUE_NEW")
    n = len(logits)
    assert 0 <= new_index < n
    assert len(set(negative_indices)) == len(negative_indices)
    assert all(0 <= idx < n and idx != new_index for idx in negative_indices)
    if label == "TRUE_NEW":
        assert primary_positive is None and not other_positives
        pointwise = F.cross_entropy(logits.unsqueeze(0), torch.tensor([new_index], device=logits.device))
        rank = logits.new_zeros(())
    else:
        assert primary_positive is not None and 0 <= primary_positive < n
        positives = (primary_positive, *other_positives)
        assert len(set(positives)) == len(positives)
        assert new_index not in positives
        assert not set(positives).intersection(negative_indices)
        # Cross-entropy on the primary and actual alternatives; other valid
        # semantic positives are ignored rather than inadvertently penalized.
        masked = logits.clone()
        if other_positives:
            masked[list(other_positives)] = -torch.inf
        target = torch.tensor([primary_positive], device=logits.device)
        pointwise = F.cross_entropy(masked.unsqueeze(0), target)
        rank = (F.softplus(logits[list(negative_indices)] - logits[primary_positive]).mean()
                if negative_indices else logits.new_zeros(()))
    return pointwise + rank, pointwise, rank


def weak_pointwise_loss(logits: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    """The original weak-silver trainer's loss, unchanged."""
    return F.cross_entropy(logits, labels)
