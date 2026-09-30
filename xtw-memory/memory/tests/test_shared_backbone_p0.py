"""Architecture invariants for the shared-backbone P0 (no GPU required)."""

import sys
from pathlib import Path
from types import SimpleNamespace

import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from memory.scripts.two_stage.shared_backbone_p0 import (
    SharedBackboneDualHead,
    load_parts,
    parameter_audit,
    save_parts,
)


class DummyEncoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.embed = nn.Embedding(16, 4)

    def forward(self, input_ids, attention_mask):
        return SimpleNamespace(last_hidden_state=self.embed(input_ids))


def make_model():
    return SharedBackboneDualHead(
        DummyEncoder(), None, nn.Embedding(3, 4),
        nn.Linear(4, 1), nn.Linear(4, 1),
    )


def test_one_backbone_two_heads_and_gradient_flow(tmp_path):
    model = make_model()
    counts = parameter_audit(model)
    assert counts["total_unique"] == sum(p.numel() for p in model.parameters())
    assert counts["same_backbone_parameter_ids_for_both_tasks"] is True

    args = (torch.tensor([[1, 2, 3]]), torch.ones(1, 3, dtype=torch.long),
            torch.tensor([[0, 2]]), torch.tensor([[True, True]]), torch.zeros(1, dtype=torch.long))
    b = model(*args, task="boundary")
    r = model(*args, task="ranking")
    assert b.shape == r.shape == (1, 2)
    (b.sum() + r.sum()).backward()
    assert model.encoder.embed.weight.grad is not None
    assert model.boundary_head.weight.grad is not None
    assert model.ranking_head.weight.grad is not None

    model.zero_grad(set_to_none=True)
    model(*args, task="boundary").sum().backward()
    assert model.encoder.embed.weight.grad is not None
    assert model.boundary_head.weight.grad is not None
    assert model.ranking_head.weight.grad is None
    model.zero_grad(set_to_none=True)
    model(*args, task="ranking").sum().backward()
    assert model.encoder.embed.weight.grad is not None
    assert model.boundary_head.weight.grad is None
    assert model.ranking_head.weight.grad is not None

    masked = (args[0], args[1], args[2], torch.tensor([[True, False]]), args[4])
    assert model(*masked, task="ranking")[0, 1] == -1e4

    save_parts(model, tmp_path / "checkpoint")
    restored = load_parts(make_model(), tmp_path / "checkpoint")
    torch.testing.assert_close(restored(*args, task="boundary"), b)
    torch.testing.assert_close(restored(*args, task="ranking"), r)


def test_joint_epoch_gate_cannot_hide_one_task_regression():
    # Import via the established Laya environment; this is a CPU-only gate test.
    from memory.scripts.two_stage import common  # noqa: F401
    from memory.scripts.two_stage.train_shared_backbone_p0 import metric_gate, select_epoch

    def row(epoch, macro, new, top1, mrr):
        boundary = {"macro_f1": macro, "true_new": {"f1": new}}
        ranking = {"top1": top1, "mrr": mrr}
        return {"epoch": epoch, "boundary_dev": boundary,
                "ranking_dev": ranking, "gate": metric_gate(boundary, ranking)}

    # A larger Boundary gain does not justify selecting an epoch failing Ranking.
    history = [row(1, .70, .42, .67, .78), row(2, .66, .36, .71, .82)]
    assert history[0]["gate"]["all_pass"] is False
    assert history[1]["gate"]["all_pass"] is True
    assert select_epoch(history) == 2


def test_runtime_views_have_one_shared_model_and_legacy_output_shape():
    from memory.scripts.two_stage import common  # noqa: F401
    from memory.scripts.two_stage.replay_shared_backbone_p0 import ModelView

    shared = make_model()
    boundary, ranking = ModelView(shared, "boundary"), ModelView(shared, "ranking")
    assert boundary.shared is ranking.shared
    args = (torch.tensor([[1, 2, 3]]), torch.ones(1, 3, dtype=torch.long),
            torch.tensor([[0, 2]]), torch.tensor([[True, True]]), torch.zeros(1, dtype=torch.long))
    for view in (boundary, ranking):
        scores, unused_action_logits = view(*args)
        assert scores.shape == (1, 2)
        assert unused_action_logits is None
