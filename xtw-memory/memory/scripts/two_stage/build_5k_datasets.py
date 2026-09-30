#!/usr/bin/env python3
"""Build Boundary 5K and Ranking 5K Datasets with Strict Nesting and Multi-Community Balance."""

import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CLEAN_CORPUS = PROJECT_ROOT / "memory/clean/multi_community_v0.1/messages.jsonl"
OUT_BASE = PROJECT_ROOT / "memory/benchmark-results/router-v0.2-dual-model-5k-scaling-v0.1"

# Baseline inputs
BASELINE_EXP = PROJECT_ROOT / "memory/benchmark-results/router-v0.2-small-scale-refinement-v0.1"
TRAIN_SEMANTIC_PATH = PROJECT_ROOT / "memory/benchmark-results/laya-episode-routing-hard-negative-ranking-v0.1/dataset/semantic-hard-negative-silver-v0.1/train.jsonl"
BASELINE_MC_PATH = BASELINE_EXP / "multi-community-semantic/multi_community_semantic_cases.jsonl"
WEAK_TRAIN_5K_PATH = PROJECT_ROOT / "memory/benchmark-results/laya-episode-routing-weak-silver-scaling-v0.2/data/train-5k.jsonl"
WEAK_TRAIN_20K_PATH = PROJECT_ROOT / "memory/benchmark-results/laya-episode-routing-weak-silver-scaling-v0.2/data/train-20k.jsonl"
RUNTIME_BANK_PATH = BASELINE_EXP / "runtime-hard-negative-bank/runtime_hard_negatives.jsonl"

BOUNDARY_OUT_DIR = OUT_BASE / "datasets/boundary-5k"
RANKING_OUT_DIR = OUT_BASE / "datasets/ranking-5k"
BOUNDARY_OUT_DIR.mkdir(parents=True, exist_ok=True)
RANKING_OUT_DIR.mkdir(parents=True, exist_ok=True)


def parse_iso(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def pass_a(packet: Dict[str, Any]) -> str:
    target = packet["target"]
    context = packet["prior_context"]
    t_text = target["text"].strip()
    if target.get("reply_to_message_id"):
        ctx_ids = {m["message_id"] for m in context}
        if target["reply_to_message_id"] in ctx_ids:
            return "TRUE_CONTINUE"
    delta = packet.get("delta_sec", 0)
    if delta < 45 and any(w in t_text for w in ["对", "是", "好", "行", "没", "不", "草", "乐", "笑", "哈哈", "确实", "真的", "啥", "怎么", "?", "？"]):
        return "TRUE_CONTINUE"
    if delta >= 1800 and not target.get("reply_to_message_id") and len(t_text) >= 4:
        return "TRUE_NEW"
    if delta >= 600 and not target.get("reply_to_message_id") and len(t_text) >= 6:
        recent_text = "".join(m["text"] for m in context[-3:])
        if len(set(recent_text).intersection(set(t_text))) < 2:
            return "TRUE_NEW"
    if delta < 120 and target.get("participant_id") in {m["participant_id"] for m in context[-2:]}:
        return "TRUE_CONTINUE"
    return "AMBIGUOUS"


def pass_b(packet: Dict[str, Any]) -> str:
    target = packet["target"]
    context = packet["prior_context"]
    t_text = target["text"].strip()
    delta = packet.get("delta_sec", 0)
    if delta >= 1200 and not target.get("reply_to_message_id") and len(t_text) >= 4:
        return "TRUE_NEW"
    if target.get("reply_to_message_id") and any(m["message_id"] == target["reply_to_message_id"] for m in context):
        return "TRUE_CONTINUE"
    if delta < 30 and len(t_text) >= 1:
        return "TRUE_CONTINUE"
    if delta < 90 and context and target.get("participant_id") == context[-1]["participant_id"]:
        return "TRUE_CONTINUE"
    if delta >= 600:
        recent_words = set(re.findall(r'[\u4e00-\u9fa5]{2,}', "".join(m["text"] for m in context[-4:])))
        target_words = set(re.findall(r'[\u4e00-\u9fa5]{2,}', t_text))
        if len(recent_words.intersection(target_words)) == 0 and len(t_text) >= 6:
            return "TRUE_NEW"
    return "AMBIGUOUS"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192 * 1024):
            h.update(chunk)
    return h.hexdigest()


def main():
    print("=== Step 1: Loading Existing Baseline Cases to Guarantee Strict Nesting ===")
    
    # 1. Baseline Boundary Cases (2,210 cases)
    baseline_boundary_cases = []
    baseline_boundary_ids = set()
    
    with open(TRAIN_SEMANTIC_PATH) as f:
        for line in f:
            r = json.loads(line)
            cid = r["packet"]["case_id"]
            baseline_boundary_ids.add(cid)
            baseline_boundary_cases.append(r)
            
    with open(BASELINE_MC_PATH) as f:
        for line in f:
            r = json.loads(line)
            cid = r["packet"]["case_id"]
            baseline_boundary_ids.add(cid)
            baseline_boundary_cases.append(r)
            
    assert len(baseline_boundary_cases) == 2210, f"Expected 2210 baseline boundary cases, got {len(baseline_boundary_cases)}"
    print(f"Loaded {len(baseline_boundary_cases)} baseline boundary cases.")

    # 2. Baseline Ranking Cases (2,007 cases)
    baseline_ranking_cases = []
    baseline_ranking_ids = set()

    with open(TRAIN_SEMANTIC_PATH) as f:
        for line in f:
            r = json.loads(line)
            if r["mapped"]["semantic_label"] == "TRUE_CONTINUE" and r["mapped"].get("positive_available"):
                cid = r["packet"]["case_id"]
                baseline_ranking_ids.add(cid)
                baseline_ranking_cases.append(r)
    print(f"Loaded {len(baseline_ranking_cases)} baseline semantic ranking cases (expected 822)")

    weak_count = 0
    with open(WEAK_TRAIN_5K_PATH) as f:
        for line in f:
            if weak_count >= 1178:
                break
            r = json.loads(line)
            if r.get("ground_truth", {}).get("label", "").startswith("CONTINUE:"):
                cid = r["case_id"]
                baseline_ranking_ids.add(cid)
                baseline_ranking_cases.append(r)
                weak_count += 1
    print(f"Loaded {weak_count} baseline weak ranking cases (expected 1178)")

    bank_count = 0
    with open(RUNTIME_BANK_PATH) as f:
        for line in f:
            r = json.loads(line)
            cid = r["case_id"]
            baseline_ranking_ids.add(cid)
            baseline_ranking_cases.append(r)
            bank_count += 1
    print(f"Loaded {bank_count} baseline runtime bank cases (expected 7)")
    assert len(baseline_ranking_cases) == 2007, f"Expected 2007 baseline ranking cases, got {len(baseline_ranking_cases)}"

    print("\n=== Step 2: Mining Multi-Community Semantic Cases ===")
    # Target: 560 new cases per community across c_000003..c_000007 (180 NEW + 380 CONT)
    # Total new = 2,800 cases -> 2,210 + 2,800 = 5,010 cases for Boundary!
    existing_target_msg_ids = set()
    for c in baseline_boundary_cases:
        existing_target_msg_ids.add(c["packet"]["target"]["message_id"])

    groups = {}
    with open(CLEAN_CORPUS) as f:
        for line in f:
            m = json.loads(line)
            groups.setdefault(m["conversation_id"], []).append(m)

    new_boundary_cases = []
    new_ranking_cases = []
    community_stats = Counter()

    CAP_NEW_PER_GROUP = 180
    CAP_CONT_PER_GROUP = 380

    for cid in sorted(groups.keys()):
        msgs = groups[cid]
        curr_new = 0
        curr_cont = 0
        
        # Build active window simulation to harvest hard negatives
        recent_threads = []  # list of (thread_id, recent_messages, participant_ids)

        for i in range(12, len(msgs) - 1):
            target = msgs[i]
            if target["message_id"] in existing_target_msg_ids:
                continue

            context = msgs[max(0, i - 8):i]
            prev = msgs[i - 1]
            delta_sec = (parse_iso(target["timestamp"]) - parse_iso(prev["timestamp"])).total_seconds()
            
            packet = {
                "case_id": f"mc5k_{cid}_{target['message_id']}",
                "target_message_id": target["message_id"],
                "conversation_id": cid,
                "target": target,
                "prior_context": context,
                "delta_sec": delta_sec,
            }

            ra = pass_a(packet)
            rb = pass_b(packet)

            if ra == rb and ra in ("TRUE_NEW", "TRUE_CONTINUE"):
                label = ra
                if label == "TRUE_NEW" and curr_new < CAP_NEW_PER_GROUP:
                    curr_new += 1
                    community_stats[f"{cid}_NEW"] += 1
                    
                    record = {
                        "packet": packet,
                        "mapped": {
                            "case_id": packet["case_id"],
                            "target_message_id": target["message_id"],
                            "conversation_id": cid,
                            "semantic_label": "TRUE_NEW",
                            "review_confidence": "HIGH",
                            "delta_seconds": delta_sec,
                            "candidates": [],
                        }
                    }
                    new_boundary_cases.append(record)
                    existing_target_msg_ids.add(target["message_id"])

                elif label == "TRUE_CONTINUE" and curr_cont < CAP_CONT_PER_GROUP:
                    curr_cont += 1
                    community_stats[f"{cid}_CONT"] += 1

                    # Build positive candidate from immediate context
                    pos_cand_id = f"ep_{cid}_{context[0]['message_id']}"
                    pos_candidate = {
                        "runtime_episode_id": pos_cand_id,
                        "summary": " ; ".join(m["text"][:24] for m in context[-3:]),
                        "recent_messages": [{"text": m["text"]} for m in context[-4:]],
                        "all_episode_message_ids": [m["message_id"] for m in context],
                        "anchor_message_ids": [m["message_id"] for m in context],
                        "semantic_relation": "POSITIVE",
                    }

                    # Mine 1-3 hard negative candidates from earlier active context or competing messages
                    candidates = [pos_candidate]
                    if i >= 35:
                        neg_context_1 = msgs[i-25:i-17]
                        neg_cand_1 = {
                            "runtime_episode_id": f"ep_comp_{cid}_{neg_context_1[0]['message_id']}",
                            "summary": " ; ".join(m["text"][:24] for m in neg_context_1[-3:]),
                            "recent_messages": [{"text": m["text"]} for m in neg_context_1[-4:]],
                            "all_episode_message_ids": [m["message_id"] for m in neg_context_1],
                            "anchor_message_ids": [m["message_id"] for m in neg_context_1],
                            "semantic_relation": "NEGATIVE",
                        }
                        candidates.append(neg_cand_1)

                    if i >= 60:
                        neg_context_2 = msgs[i-55:i-47]
                        neg_cand_2 = {
                            "runtime_episode_id": f"ep_comp_{cid}_{neg_context_2[0]['message_id']}",
                            "summary": " ; ".join(m["text"][:24] for m in neg_context_2[-3:]),
                            "recent_messages": [{"text": m["text"]} for m in neg_context_2[-4:]],
                            "all_episode_message_ids": [m["message_id"] for m in neg_context_2],
                            "anchor_message_ids": [m["message_id"] for m in neg_context_2],
                            "semantic_relation": "NEGATIVE",
                        }
                        candidates.append(neg_cand_2)

                    record = {
                        "packet": packet,
                        "mapped": {
                            "case_id": packet["case_id"],
                            "target_message_id": target["message_id"],
                            "conversation_id": cid,
                            "semantic_label": "TRUE_CONTINUE",
                            "review_confidence": "HIGH",
                            "delta_seconds": delta_sec,
                            "positive_available": True,
                            "primary_positive_candidate_id": pos_cand_id,
                            "hard_negative_present": len(candidates) > 1,
                            "candidates": candidates,
                        }
                    }
                    new_boundary_cases.append(record)
                    new_ranking_cases.append(record)
                    existing_target_msg_ids.add(target["message_id"])

            if curr_new >= CAP_NEW_PER_GROUP and curr_cont >= CAP_CONT_PER_GROUP:
                break

        print(f"Group {cid}: mined {curr_new} NEW, {curr_cont} CONTINUE. Total: {curr_new + curr_cont}")

    print(f"\nTotal new boundary cases mined: {len(new_boundary_cases)}")
    print(f"Total new ranking cases mined: {len(new_ranking_cases)}")

    print("\n=== Step 3: Assembling Boundary 5K Dataset ===")
    all_boundary_cases = baseline_boundary_cases + new_boundary_cases
    assert len(all_boundary_cases) == 5010, f"Expected 5010 boundary cases, got {len(all_boundary_cases)}"
    
    # Verify strict nesting: every baseline ID must be in all_boundary_cases
    final_boundary_ids = {c["packet"]["case_id"] for c in all_boundary_cases}
    assert baseline_boundary_ids.issubset(final_boundary_ids), "Strict nesting violated for Boundary 5K!"
    print("Strict nesting verified: baseline 2,210 cases ⊂ 5,010 boundary dataset.")

    boundary_file = BOUNDARY_OUT_DIR / "boundary_train_5k.jsonl"
    with open(boundary_file, "w", encoding="utf-8") as f:
        for c in all_boundary_cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    boundary_sha = file_sha256(boundary_file)
    print(f"Boundary 5K saved: {boundary_file} (SHA256: {boundary_sha})")

    b_labels = Counter(c["mapped"]["semantic_label"] for c in all_boundary_cases)
    b_convs = Counter(c["packet"]["conversation_id"] for c in all_boundary_cases)
    print("Boundary 5K label distribution:", dict(b_labels))
    print("Boundary 5K community distribution:", dict(b_convs))

    print("\n=== Step 4: Assembling Ranking 5K Dataset ===")
    # Baseline: 2,007 cases
    # Add new multi-community ranking cases (up to 2,000)
    # Add 1,000 additional weak CONTINUE cases from train-20k (starting after index 1178)
    additional_mc_ranking = new_ranking_cases[:2000]
    
    additional_weak_ranking = []
    weak_skipped = 0
    weak_added = 0
    with open(WEAK_TRAIN_20K_PATH) as f:
        for line in f:
            r = json.loads(line)
            if r.get("ground_truth", {}).get("label", "").startswith("CONTINUE:"):
                # Skip the first 1178 to avoid duplicating the baseline weak cases
                if weak_skipped < 1178:
                    weak_skipped += 1
                    continue
                if weak_added < 1100:
                    additional_weak_ranking.append(r)
                    weak_added += 1
                else:
                    break

    all_ranking_cases = baseline_ranking_cases + additional_mc_ranking + additional_weak_ranking
    assert len(all_ranking_cases) == 5007, f"Expected 5007 ranking cases, got {len(all_ranking_cases)}"

    # Verify strict nesting: every baseline ID must be in all_ranking_cases
    final_ranking_ids = set()
    for c in all_ranking_cases:
        cid = c.get("case_id") or c.get("packet", {}).get("case_id")
        final_ranking_ids.add(cid)

    assert baseline_ranking_ids.issubset(final_ranking_ids), "Strict nesting violated for Ranking 5K!"
    print("Strict nesting verified: baseline 2,007 cases ⊂ 5,007 ranking dataset.")

    ranking_file = RANKING_OUT_DIR / "ranking_train_5k.jsonl"
    with open(ranking_file, "w", encoding="utf-8") as f:
        for c in all_ranking_cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    ranking_sha = file_sha256(ranking_file)
    print(f"Ranking 5K saved: {ranking_file} (SHA256: {ranking_sha})")

    # Generate dataset manifest
    manifest_payload = {
        "experiment_id": "router_v0_2_dual_model_5k_scaling_v0_1",
        "datasets": {
            "boundary_5k": {
                "file": str(boundary_file),
                "sha256": boundary_sha,
                "total_unique_cases": len(all_boundary_cases),
                "nested_from_baseline": True,
                "baseline_cases_count": 2210,
                "new_semantic_cases_count": len(new_boundary_cases),
                "breakdown": {
                    "TRUE_NEW": b_labels["TRUE_NEW"],
                    "TRUE_CONTINUE": b_labels["TRUE_CONTINUE"],
                },
                "community_distribution": dict(b_convs),
            },
            "ranking_5k": {
                "file": str(ranking_file),
                "sha256": ranking_sha,
                "total_unique_cases": len(all_ranking_cases),
                "nested_from_baseline": True,
                "baseline_cases_count": 2007,
                "new_semantic_cases_count": len(additional_mc_ranking),
                "additional_weak_cases_count": len(additional_weak_ranking),
                "breakdown": {
                    "baseline_cases": 2007,
                    "multi_community_semantic_continue": len(additional_mc_ranking),
                    "weak_continue": len(additional_weak_ranking),
                }
            }
        }
    }

    manifest_file = OUT_BASE / "datasets/manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest_payload, f, indent=2, ensure_ascii=False)

    print(f"Dataset manifest saved to {manifest_file}")
    print("=== Dataset Building Completed Successfully! ===")


if __name__ == "__main__":
    main()
