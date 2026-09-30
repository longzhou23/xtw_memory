"""Dataset and DataLoader for Laya Episode Routing Training.

Formats Judgment Cases into Laya's native sequence and option marker representations.
Adheres strictly to Laya fine-tuning schema and Section 14 (Option Order Bias Prevention).
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any, Dict, List, Optional, Tuple

import torch
from torch.utils.data import Dataset, DataLoader

from laya.common import build_sequence, collate_items, QTYPES


def format_case_to_laya_item(
    case: Dict[str, Any],
    tok,
    max_len: int = 1024,
    head_max_len: int = 256,
    permute_options: bool = True,
) -> Dict[str, Any]:
    """Converts an Episode Routing case into a Laya input item."""
    # 1. State representation
    # Include the recent chronological messages leading up to target message
    ctx_lines = [
        f"{m['participant_id']}: {m['text']}"
        for m in case.get("recent_context", [])[-8:]
    ]
    t = case["target"]
    reply_tag = f" (回复: {t['reply_to_message_id']})" if t.get("reply_to_message_id") else ""
    target_str = f"{t['participant_id']}: {t['text']}{reply_tag}"
    state = f"[近期上下文]\n" + "\n".join(ctx_lines) + f"\n[当前消息] {target_str}"

    # 2. Options and Criteria
    criteria = {}
    for cand in case.get("candidate_episodes", []):
        cand_id = cand["candidate_id"]
        # Snippets of recent messages in this candidate thread
        c_snips = " ; ".join(m["text"][:28] for m in cand.get("messages", [])[-2:])
        criteria[cand_id] = f"延续话题: {c_snips}"

    criteria["NEW"] = "新话题: 开启完全独立的新讨论线程"
    criteria["UNKNOWN"] = "信息不足: 缺乏上下文、图片未展示或代词指代不明"

    keys = list(criteria.keys())

    # 3. Deterministic Option Permutation (Section 14: Option Order Shortcut Prevention)
    if permute_options:
        seed = int(hashlib.md5(case["case_id"].encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        order = list(range(len(keys)))
        rng.shuffle(order)
    else:
        order = list(range(len(keys)))

    ordered_keys = [keys[i] for i in order]

    # 4. Target Label Mapping
    gt_label = case.get("ground_truth", {}).get("label", "NEW")
    if gt_label.startswith("CONTINUE:"):
        target_key = gt_label.split(":", 1)[1]
    else:
        target_key = gt_label

    if target_key in ordered_keys:
        target_idx = ordered_keys.index(target_key)
    else:
        # Fallback to UNKNOWN if candidate key not found
        target_idx = ordered_keys.index("UNKNOWN") if "UNKNOWN" in ordered_keys else 0

    target_vec = [1.0 if i == target_idx else 0.0 for i in range(len(keys))]

    q = {
        "t": "choice",
        "ins": "当前目标消息属于哪个 Episode？",
        "crit": criteria,
    }

    ids, markers = build_sequence(
        tok,
        state,
        q,
        max_len=max_len,
        head_max_len=head_max_len,
        option_order=order,
        truncate_left=True,
    )

    return {
        "ids": ids,
        "markers": markers,
        "qtype": QTYPES["choice"],
        "target": target_vec,
        "label": target_idx,
        "case_id": case["case_id"],
        "ordered_keys": ordered_keys,
        "target_key": target_key,
    }


class LayaRoutingDataset(Dataset):
    def __init__(
        self,
        cases_path: str,
        tok,
        max_len: int = 1024,
        head_max_len: int = 256,
        permute_options: bool = True,
    ):
        self.cases = []
        with open(cases_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    self.cases.append(json.loads(line))
        self.tok = tok
        self.max_len = max_len
        self.head_max_len = head_max_len
        self.permute_options = permute_options

    def __len__(self) -> int:
        return len(self.cases)

    def __getitem__(self, idx: int) -> Dict[str, Any]:
        case = self.cases[idx]
        return format_case_to_laya_item(
            case,
            self.tok,
            max_len=self.max_len,
            head_max_len=self.head_max_len,
            permute_options=self.permute_options,
        )


def create_dataloader(
    cases_path: str,
    tok,
    batch_size: int = 8,
    shuffle: bool = True,
    max_len: int = 1024,
    head_max_len: int = 256,
    permute_options: bool = True,
) -> DataLoader:
    dataset = LayaRoutingDataset(
        cases_path,
        tok,
        max_len=max_len,
        head_max_len=head_max_len,
        permute_options=permute_options,
    )

    def custom_collate(batch_items):
        # collate_items expects list of groups
        return collate_items([batch_items], pad_id=tok.pad_token_id)

    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        collate_fn=custom_collate,
    )
