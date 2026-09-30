"""One Laya encoder and context stack, with separate task-specific option scorers.

The existing frozen inputs are option-marker sequences. Each boundary option
(CONTINUE, NEW) and each ranking candidate gets one scalar from its own head;
the backbone and contextual layers are *the same objects* for both tasks.
"""

from pathlib import Path

import torch
from torch import nn
from safetensors import safe_open
from safetensors.torch import load_file, save_file


class SharedBackboneDualHead(nn.Module):
    def __init__(self, encoder, context_head, type_emb, boundary_head, ranking_head):
        super().__init__()
        self.encoder = encoder
        self.context_head = context_head
        self.type_emb = type_emb
        self.boundary_head = boundary_head
        self.ranking_head = ranking_head
        self.head_checkpointing = False

    def forward(self, input_ids, attention_mask, marker_pos, marker_mask, qtype, *, task):
        if task not in ("boundary", "ranking"):
            raise ValueError(f"Unsupported task {task!r}")
        hidden = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        hidden = hidden + self.type_emb(qtype)[:, None, :]
        if self.context_head is not None:
            padding = ~attention_mask.bool()
            for layer in self.context_head.layers:
                if self.head_checkpointing and self.training and torch.is_grad_enabled():
                    from torch.utils.checkpoint import checkpoint
                    hidden = checkpoint(layer, hidden, src_key_padding_mask=padding, use_reentrant=False)
                else:
                    hidden = layer(hidden, src_key_padding_mask=padding)
        index = marker_pos.clamp(min=0)[:, :, None].expand(-1, -1, hidden.size(-1))
        options = torch.gather(hidden, 1, index)
        scorer = self.boundary_head if task == "boundary" else self.ranking_head
        return scorer(options).squeeze(-1).float().masked_fill(~marker_mask, -1e4)


def from_boundary_checkpoint(boundary_model, ranking_checkpoint: Path):
    """Start with Judge A's trained trunk, copy only Judge B's scorer tensors.

    The encoder/context stack begins at Judge A, so Judge B's task head will
    initially see a different representation. Joint training must address
    this; initial parity is not assumed and checkpoint selection uses both DEV
    tasks. No second encoder is loaded or kept in the shared model.
    """
    import copy

    boundary_scorer = boundary_model.scorer
    ranking_scorer = copy.deepcopy(boundary_scorer)
    with safe_open(str(ranking_checkpoint), framework="pt", device="cpu") as reader:
        weights = {key[len("scorer."):]: reader.get_tensor(key)
                   for key in reader.keys() if key.startswith("scorer.")}
    ranking_scorer.load_state_dict(weights, strict=True)
    return SharedBackboneDualHead(
        boundary_model.encoder,
        boundary_model.head,
        boundary_model.type_emb,
        boundary_scorer,
        ranking_scorer,
    )


def parameter_audit(model):
    parts = {
        "encoder": model.encoder,
        "context_head": model.context_head,
        "type_embedding": model.type_emb,
        "boundary_head": model.boundary_head,
        "ranking_head": model.ranking_head,
    }
    seen = set()
    counts = {}
    for name, part in parts.items():
        params = list(part.parameters()) if part is not None else []
        ids = {id(p) for p in params}
        if seen.intersection(ids):
            raise AssertionError(f"Parameters aliased across architecture parts: {name}")
        seen.update(ids)
        counts[name] = sum(p.numel() for p in params)
    unique = {id(p) for p in model.parameters()}
    assert unique == seen, "Unaccounted or duplicated trainable parameters"
    counts["shared_backbone"] = counts["encoder"] + counts["context_head"] + counts["type_embedding"]
    counts["total_unique"] = sum(p.numel() for p in model.parameters())
    assert counts["total_unique"] == counts["shared_backbone"] + counts["boundary_head"] + counts["ranking_head"]
    counts["same_backbone_parameter_ids_for_both_tasks"] = True
    return counts


def save_parts(model, directory: Path):
    directory.mkdir(parents=True, exist_ok=False)
    sections = {
        "shared-backbone": ("encoder", "context_head", "type_emb"),
        "boundary-head": ("boundary_head",),
        "ranking-head": ("ranking_head",),
    }
    for section, prefixes in sections.items():
        path = directory / section
        path.mkdir()
        state = {key: value.detach().cpu().contiguous()
                 for key, value in model.state_dict().items()
                 if any(key.startswith(prefix + ".") for prefix in prefixes)}
        save_file(state, str(path / "model.safetensors"))


def load_parts(model, directory: Path):
    state = {}
    for section in ("shared-backbone", "boundary-head", "ranking-head"):
        state.update(load_file(str(directory / section / "model.safetensors"), device="cpu"))
    model.load_state_dict(state, strict=True)
    return model
