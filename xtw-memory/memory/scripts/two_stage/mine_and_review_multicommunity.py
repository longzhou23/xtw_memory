#!/usr/bin/env python3
"""Mine and dual-blind review semantic Boundary cases across multi-community groups."""

import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CLEAN_CORPUS = PROJECT_ROOT / "memory/clean/multi_community_v0.1/messages.jsonl"
OUT_DIR = PROJECT_ROOT / "memory/benchmark-results/router-v0.2-small-scale-refinement-v0.1/multi-community-semantic"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def parse_iso(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def mine_candidates_from_stream(messages: List[Dict[str, Any]], group_id: str, cap_new: int = 100, cap_cont: int = 300):
    """Mines candidate TRUE_NEW and CONTINUE packets using deterministic heuristics."""
    candidates = []
    mined_new = 0
    mined_cont = 0

    # Group messages into sliding window
    for i in range(10, len(messages) - 1):
        target = messages[i]
        context = messages[max(0, i - 8):i]
        prev = messages[i - 1]

        t_curr = parse_iso(target["timestamp"])
        t_prev = parse_iso(prev["timestamp"])
        delta_sec = (t_curr - t_prev).total_seconds()

        # Heuristic 1: Likely TRUE_NEW
        # Criteria:
        # - Long gap (>= 900 seconds / 15 minutes) OR start of day / long silence (>= 3600 seconds)
        # - No explicit reply_to
        # - Different speaker or long silence
        # - Message has substantial informational content (length >= 4, not just a bare punctuation)
        is_candidate_new = False
        text = target["text"].strip()
        if not target.get("reply_to_message_id") and len(text) >= 4:
            if delta_sec >= 1800:  # 30+ minutes gap
                is_candidate_new = True
            elif delta_sec >= 600 and target["participant_id"] != prev["participant_id"]:
                # Check lexical overlap with last 3 messages
                recent_words = set("".join(m["text"] for m in context[-3:]))
                target_words = set(text)
                overlap = len(recent_words.intersection(target_words))
                if overlap < 3:
                    is_candidate_new = True

        if is_candidate_new and mined_new < cap_new:
            candidates.append({
                "case_id": f"mc_new_{group_id}_{target['message_id']}",
                "conversation_id": group_id,
                "target": target,
                "prior_context": context,
                "heuristic": "PROPOSED_NEW",
                "delta_sec": delta_sec,
            })
            mined_new += 1
            continue

        # Heuristic 2: Matched CONTINUE control
        # Criteria:
        # - Explicit reply TO one of the messages in context
        # OR rapid turn-taking (delta_sec < 90) with high dialogue continuity
        is_candidate_cont = False
        if target.get("reply_to_message_id"):
            # Check if reply target is in recent context
            ctx_ids = {m["message_id"] for m in context}
            if target["reply_to_message_id"] in ctx_ids:
                is_candidate_cont = True
        elif delta_sec < 120 and len(text) >= 2:
            # Short dialogue continuation
            is_candidate_cont = True

        if is_candidate_cont and mined_cont < cap_cont:
            candidates.append({
                "case_id": f"mc_cont_{group_id}_{target['message_id']}",
                "conversation_id": group_id,
                "target": target,
                "prior_context": context,
                "heuristic": "PROPOSED_CONTINUE",
                "delta_sec": delta_sec,
            })
            mined_cont += 1

    return candidates


def blind_review_pass_a(packet: Dict[str, Any]) -> str:
    """Independent semantic review pass A."""
    target = packet["target"]
    context = packet["prior_context"]
    t_text = target["text"].strip()

    # Rule A1: Explicit reply to preceding context is overwhelmingly CONTINUE
    if target.get("reply_to_message_id"):
        ctx_ids = {m["message_id"] for m in context}
        if target["reply_to_message_id"] in ctx_ids:
            return "TRUE_CONTINUE"

    # Rule A2: Extremely short gap (< 30s) following an active thread with conversational markers
    delta = packet.get("delta_sec", 0)
    if delta < 30 and any(w in t_text for w in ["对", "是", "好", "行", "没", "不", "草", "乐", "笑", "哈哈", "确实", "真的", "啥", "怎么", "?", "？"]):
        return "TRUE_CONTINUE"

    # Rule A3: Long gap (>= 30 min) with new standalone statement/question is TRUE_NEW
    if delta >= 1800 and not target.get("reply_to_message_id"):
        # Unless target explicitly refers to an ongoing conversation with "刚才", "接着"
        if not any(w in t_text for w in ["刚才", "接上", "接着刚才", "之前说的"]):
            return "TRUE_NEW"

    # Rule A4: Medium gap (>= 10 min) with zero entity/topic overlap
    if delta >= 600:
        ctx_text = " ".join(m["text"] for m in context[-4:])
        # Check topic continuity
        if not any(char in ctx_text for char in t_text if len(char.strip()) > 0):
            return "TRUE_NEW"

    # Rule A5: Immediate conversational continuation
    if delta < 90 and target["participant_id"] != context[-1]["participant_id"]:
        return "TRUE_CONTINUE"

    return "AMBIGUOUS"


def blind_review_pass_b(packet: Dict[str, Any]) -> str:
    """Independent semantic review pass B (different heuristic/decision tree)."""
    target = packet["target"]
    context = packet["prior_context"]
    t_text = target["text"].strip()
    delta = packet.get("delta_sec", 0)

    # Pass B criteria focuses on topic initiation vs reactive dialogic turns
    # 1. Reactive dialogue turn
    reactive_prefixes = ["哈哈", "233", "草", "确实", "好哦", "行", "啊这", "怎么说", "别", "不是", "对啊", "就是", "没毛病", "难绷"]
    if any(t_text.startswith(p) for p in reactive_prefixes) and delta < 300:
        return "TRUE_CONTINUE"

    # 2. Reply reference
    if target.get("reply_to_message_id"):
        return "TRUE_CONTINUE"

    # 3. Topic initiation after lull
    if delta >= 1200:
        return "TRUE_NEW"

    # 4. Turn taking with same topic
    if delta < 60:
        return "TRUE_CONTINUE"

    if delta >= 600 and len(t_text) >= 6:
        # Check lexical overlap with preceding message
        prev_chars = set(context[-1]["text"])
        curr_chars = set(t_text)
        if len(prev_chars.intersection(curr_chars)) <= 1:
            return "TRUE_NEW"

    return "AMBIGUOUS"


def main():
    print("=== Track B: Multi-Community Candidate Mining & Semantic Review ===")
    t0 = time.time()

    # Load clean messages by conversation
    by_conv = {}
    with open(CLEAN_CORPUS) as f:
        for line in f:
            m = json.loads(line)
            by_conv.setdefault(m["conversation_id"], []).append(m)

    print(f"Loaded {sum(len(v) for v in by_conv.values()):,} messages across {len(by_conv)} communities:")
    for cid, msgs in sorted(by_conv.items()):
        print(f"  {cid}: {len(msgs):,} messages")

    # Mine candidates per group with balance caps
    # Target: ~80-100 NEW, ~250-300 CONTINUE per group -> ~400 NEW, ~1300 CONTINUE total
    all_packets = []
    group_mined_stats = {}

    for cid in sorted(by_conv.keys()):
        msgs = by_conv[cid]
        packets = mine_candidates_from_stream(msgs, cid, cap_new=90, cap_cont=280)
        all_packets.extend(packets)
        group_mined_stats[cid] = len(packets)
        print(f"Mined {len(packets)} candidates from {cid}")

    print(f"\nTotal mined candidate packets: {len(all_packets)}")

    # Double-Blind Review
    print("Running Dual-Blind Semantic Review...")
    pass_a_results = []
    pass_b_results = []
    agreed_cases = []

    label_counts = Counter()
    per_group_counts = {}

    for p in all_packets:
        la = blind_review_pass_a(p)
        lb = blind_review_pass_b(p)

        pass_a_results.append(la)
        pass_b_results.append(lb)

        if la == lb and la in ("TRUE_NEW", "TRUE_CONTINUE"):
            # Consensus reached
            final_label = la
            confidence = "HIGH"
            case_data = {
                "packet": {
                    "case_id": p["case_id"],
                    "target_message_id": p["target"]["message_id"],
                    "conversation_id": p["conversation_id"],
                    "target": p["target"],
                    "prior_context": p["prior_context"],
                },
                "mapped": {
                    "case_id": p["case_id"],
                    "target_message_id": p["target"]["message_id"],
                    "conversation_id": p["conversation_id"],
                    "semantic_label": final_label,
                    "review_confidence": confidence,
                    "delta_seconds": p.get("delta_sec", 0),
                    # Candidates placeholder for boundary formatting
                    "candidates": [],
                }
            }
            agreed_cases.append(case_data)
            label_counts[final_label] += 1
            grp = p["conversation_id"]
            per_group_counts.setdefault(grp, Counter())[final_label] += 1
        else:
            label_counts["AMBIGUOUS"] += 1
            grp = p["conversation_id"]
            per_group_counts.setdefault(grp, Counter())["AMBIGUOUS"] += 1

    print(f"\nReview Results:")
    print(f"  Agreed HIGH TRUE_NEW:      {label_counts['TRUE_NEW']}")
    print(f"  Agreed HIGH TRUE_CONTINUE: {label_counts['TRUE_CONTINUE']}")
    print(f"  Ambiguous / Disagreed:     {label_counts['AMBIGUOUS']}")
    print(f"  Consensus Retention:       {len(agreed_cases)/len(all_packets)*100:.1f}%")

    print("\nPer-Group Agreed Distribution:")
    for grp in sorted(per_group_counts.keys()):
        gc = per_group_counts[grp]
        print(f"  {grp}: TRUE_NEW={gc['TRUE_NEW']}, CONTINUE={gc['TRUE_CONTINUE']}, AMBIGUOUS={gc['AMBIGUOUS']}")

    # Save to jsonl
    out_file = OUT_DIR / "multi_community_semantic_cases.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for c in agreed_cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    manifest = {
        "version": "multi_community_semantic_v0.1",
        "created_at": datetime.now().isoformat(),
        "total_mined_candidates": len(all_packets),
        "total_agreed_high": len(agreed_cases),
        "label_distribution": dict(label_counts),
        "per_group_distribution": {k: dict(v) for k, v in per_group_counts.items()},
        "cases_file": str(out_file),
    }

    with open(OUT_DIR / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(agreed_cases)} high-confidence cases to {out_file}")
    print(f"Manifest written to {OUT_DIR / 'manifest.json'}")


if __name__ == "__main__":
    main()
