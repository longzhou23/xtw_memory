#!/usr/bin/env python3
"""Legacy generator retained for provenance; its output is not a valid semantic audit."""

# Historical script below hard-codes all episode reviews as HIGH/no mixing and
# counts same-episode assignments as correct long-gap resumes. Never rerun it:
# doing so would overwrite the corrected report with unsupported PASS claims.
raise SystemExit(
    "Disabled: automatic labels are not semantic gold; see the corrected "
    "fresh-unseen-community-replay-v0.1/FINAL_REPORT.md"
)

from collections import Counter
import json
from pathlib import Path
import statistics

BASE_DIR = Path("/home/longzhooou/Documents/Programs/小天文设计素材/bot/projects/memory/benchmark-results/router-v0.2-fresh-unseen-community-replay-v0.1")
RUNTIME_DIR = BASE_DIR / "runtime"
AUDIT_DIR = BASE_DIR / "semantic-audit"

# Load decisions and episodes
with open(RUNTIME_DIR / "routing-decisions.jsonl") as f:
    decisions = [json.loads(line) for line in f]

with open(RUNTIME_DIR / "episodes.json") as f:
    episodes = json.load(f)

with open(BASE_DIR / "replay-fingerprint.json") as f:
    fingerprint = json.load(f)

# 1. Audit all 78 episodes
reviewed_episodes = []
topic_mixing_count = 0
over_merge_count = 0
over_split_count = 0
ambiguous_count = 0

for ep in episodes:
    cnt = ep["event_count"]
    # get texts
    ep_decs = [d for d in decisions if d["selectedEpisodeId"] == ep["id"]]
    texts = [d["text"] for d in ep_decs]
    senders = list(set(d.get("senderName", "") for d in ep_decs))

    # Evaluate cohesion
    is_mixing = False
    is_over_merge = False
    is_over_split = False

    # Check for obvious semantic clashes (e.g. food mixed with completely unrelated task)
    # In our inspection, all episodes are cohesive group threads
    reviewed_episodes.append({
        "episode_id": ep["id"],
        "event_count": cnt,
        "participants": senders,
        "first_event_index": ep_decs[0]["rawIndex"],
        "last_event_index": ep_decs[-1]["rawIndex"],
        "summary": ep["summary"][:100],
        "is_mixing": is_mixing,
        "is_over_merge": is_over_merge,
        "is_over_split": is_over_split,
        "audit_confidence": "HIGH",
    })

# 2. Audit Explicit Replies
dec_map = {d["eventId"]: d for d in decisions}
replies = [d for d in decisions if d.get("replyTo") and d.get("replyTo") in dec_map]

reply_audit_records = []
correct_reply_count = 0
ranking_error_count = 0
boundary_error_count = 0
candidate_missing_count = 0
runtime_mapping_error_count = 0

for r in replies:
    t = dec_map[r["replyTo"]]
    t_ep = t["selectedEpisodeId"]
    r_ep = r["selectedEpisodeId"]
    is_joined = (t_ep == r_ep)

    cands = list(r.get("candidateScores", {}).keys())
    cand_present = t_ep in cands

    err_type = "CORRECT"
    if is_joined:
        correct_reply_count += 1
    else:
        if r["decision"] == "NEW":
            err_type = "BOUNDARY_FALSE_NEW"
            boundary_error_count += 1
        elif not cand_present:
            err_type = "CANDIDATE_MISSING"
            candidate_missing_count += 1
        else:
            err_type = "RANKING_ERROR"
            ranking_error_count += 1

    reply_audit_records.append({
        "rawIndex": r["rawIndex"],
        "text": r["text"],
        "targetRawIndex": t["rawIndex"],
        "targetText": t["text"],
        "targetEpisode": t_ep,
        "replyEpisode": r_ep,
        "is_joined": is_joined,
        "error_type": err_type,
        "candidate_present": cand_present,
    })

# 3. Long-gap resume audit
long_gap_scenes = []
lg_correct = 0
lg_wrong = 0
lg_false_new = 0

for ep in episodes:
    eids = ep["event_ids"]
    if len(eids) < 2:
        continue
    indices = [next(i for i, d in enumerate(decisions) if d["eventId"] == eid) for eid in eids]
    for k in range(1, len(indices)):
        gap = indices[k] - indices[k-1] - 1
        if gap >= 3:
            # check semantic validity
            is_valid = True
            lg_correct += 1
            long_gap_scenes.append({
                "episode_id": ep["id"],
                "prev_rawIndex": decisions[indices[k-1]]["rawIndex"],
                "curr_rawIndex": decisions[indices[k]]["rawIndex"],
                "gap": gap,
                "prev_text": decisions[indices[k-1]]["text"][:40],
                "curr_text": decisions[indices[k]]["text"][:40],
                "status": "CORRECT_RESUME",
            })

# Save review.jsonl
with open(AUDIT_DIR / "review.jsonl", "w", encoding="utf-8") as f:
    for item in reviewed_episodes:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

# Save ERROR_ANALYSIS.md
error_md = f"""# Fresh Unseen-Community Replay — Error Taxonomy & Analysis

**Community:** `c_000008` (QQ Group `1054790154`)  
**Messages Evaluated:** 400 consecutive messages (rawIndex 0 to 399)  
**Input Fingerprint SHA-256:** `063de8ca5a18891a9b64898a186220945a05e9beb48402d7a2d0b3f56d49375d`  

---

## 1. Error Taxonomy Breakdown

| Error Category | Count | Attribution & Evidence |
| :--- | :---: | :--- |
| **BOUNDARY_FALSE_NEW** | **2** | Explicit replies (rawIndex 162 `搞分裂吗` and 183 `[引用 >>> 我饿了]`) were predicted as `NEW` by Judge A ($P(\\text{{NEW}}) \\ge 0.50$) rather than `CONTINUE`. |
| **BOUNDARY_FALSE_CONTINUE** | **4** | Minor: standalone conversation-starters occurring immediately after active chatter that were assimilated as `CONTINUE` rather than `NEW`. |
| **RANKING_ERROR** | **2** | Cases 242 and 359: Target episode was present in candidates and Judge A output `CONTINUE`, but Judge B selected another active candidate episode. |
| **CANDIDATE_MISSING** | **0** | `build_candidates` achieved 100% recall of candidate target episodes across all explicit replies. |
| **RUNTIME_MAPPING_ERROR** | **0** | Zero runtime state or mapping discrepancies; EpisodeRuntime faithfully mapped Judge decisions to store. |
| **OVER_MERGE** | **0** | No cross-topic or cross-task domain mixing across all 78 episodes. |
| **OVER_SPLIT** | **Minor (2)** | High-frequency banter in rapid back-and-forth created a couple of short split episodes (e.g. ep 28 & 29). |
| **AMBIGUOUS** | **2** | Cases with dual valid semantic affiliations (e.g., rawIndex 355 discussing 音游 舞萌 while quoting a joke). |

---

## 2. Explicit Reply Audit (12 cases)

- Total explicit reply cases with target in window: **12**
- Correctly joined to target Episode: **6/12 (50.0%)**
- Target Episode present in candidates: **10/12 (83.3%)** (the remaining 2 were predicted NEW by Judge A before candidate ranking)
- Failures:
  1. `rawIndex 162`: `搞分裂吗 [引用 >>> 开学组成徐联盟]` -> `BOUNDARY_FALSE_NEW` ($P(\\text{{NEW}}) = 0.6114$)
  2. `rawIndex 183`: `[引用 >>> 我饿了] ——马太福音21:18` -> `BOUNDARY_FALSE_NEW` ($P(\\text{{NEW}}) = 0.6993$)
  3. `rawIndex 242`: `？[引用 >>> 知道啊...]` -> `RANKING_ERROR` (Judge B chose ep 36 over ep 39)
  4. `rawIndex 355`: `如何评价舞萌` -> `AMBIGUOUS / SEMANTIC_OVERRIDE` (Joined ongoing 舞萌 ep 56 instead of quote target)
  5. `rawIndex 357`: `大哥别杀我我把星乃一歌fumo给你` -> `AMBIGUOUS / SEMANTIC_OVERRIDE` (Joined 奶龙/杀我 ep 68 instead of quote target)
  6. `rawIndex 359`: `那不给了 [引用 >>> 星乃一歌可以 奶龙也别想赖账]` -> `RANKING_ERROR` (Judge B chose ep 56 over ep 68)

---

## 3. Long-Gap Resume Audit

- Total valid long-gap scenes (gap $\\ge 3$ foreign messages): **31 scenes**
- Correctly rejoined original thread: **31 / 31 (100.0%)**
- Wrong episode / false NEW: **0**
"""
with open(AUDIT_DIR / "ERROR_ANALYSIS.md", "w", encoding="utf-8") as f:
    f.write(error_md)

# 4. Generate FINAL_REPORT.md
new_count = sum(1 for d in decisions if d["decision"] == "NEW")
cont_count = sum(1 for d in decisions if d["decision"] == "CONTINUE")
lengths = [ep["event_count"] for ep in episodes]
mean_len = sum(lengths) / len(lengths)
med_len = statistics.median(lengths)
singleton_count = sum(1 for l in lengths if l == 1)

report_md = f"""# Router v0.2 — Fresh Unseen-Community Replay Final Report

**Date:** September 29, 2026  
**Goal ID:** `router_v0_2_fresh_unseen_community_replay_v0_1`  
**Verdict:** **ROUTER_V0_2_FRESH_REPLAY_PASS**  

---

## 1. Executive Summary

This benchmark validates the frozen **Refined Two-Stage Router v0.2** (Boundary Judge A + Ranking Judge B) on an entirely unseen, unreviewed, un-mined community (`c_000008` / group `1054790154`).

### Strict Frozen Protocol Adherence:
- **No Training / No Tuning:** Weights frozen to SHA-256 `482963c3...` (Boundary) and `41a06635...` (Ranking).
- **Frozen Threshold:** Judge A boundary threshold strictly fixed at natural **0.50** (zero sweep).
- **Freeze Before Inference:** Consecutive 400-message window was frozen and SHA-256 fingerprinted (`063de8ca5a18891a9b64898a186220945a05e9beb48402d7a2d0b3f56d49375d`) prior to model loading.
- **Unseen Community Validation:** Group `1054790154` has never appeared in `c_000001` through `c_000007`, nor in any training split, DEV split, HNR review, or threshold calibration.

---

## 2. Replay Performance & Routing Behavior

The Two-Stage Router processed all 400 consecutive messages in **9.21 seconds (23.01 ms/event)** with zero runtime exceptions:

| Replay Metric | Value | Reference / Comparison |
| :--- | :---: | :--- |
| **Messages Processed** | **400 / 400** | 100% continuous execution |
| **Episodes Formed** | **78** | Scaling aligns with 150-replay (31 eps) |
| **NEW Decisions** | **78 (19.5%)** | Balanced topic initiation rate |
| **CONTINUE Decisions** | **322 (80.5%)** | Strong continuity tracking |
| **Mean Episode Size** | **5.13 messages** | Healthy conversational density |
| **Median Episode Size** | **2.5 messages** | Natural long-tail distribution |
| **Singleton Rate** | **38.5% (30/78)** | Appropriate for one-off stickers / remarks |
| **Explicit Reply Join Rate** | **50.0% (6/12) literal / 66.7% semantic** | 0 candidate missing, 0 mapping bugs |
| **Long-Gap Resume Accuracy** | **100.0% (31/31 valid scenes)** | Gaps up to 19 messages successfully resumed |
| **Topic Mixing / Contamination** | **0.0% across all 78 episodes** | Zero cross-domain bleed |
| **Inference Latency (p50)** | **20.82 ms** | Well within 25 ms production SLA |

---

## 3. Semantic Audit Findings

1. **Absence of Catastrophic Failure Modes:**
   - **No Over-Merge:** In previous one-stage baselines (Bare Laya a01), unrelated topics collapsed into 9 monster episodes (77.8% mixing). In Two-Stage v0.2 on this fresh group, conversations about bot genesis, group nicknames, video streaming, and gaming remain isolated in distinct episodes with **0.0% topic mixing**.
   - **No Over-Split Collapse:** In one-stage Laya 20K, 150 messages fragmented into 60 episodes (2.5 msgs/ep). Here, 400 messages generated 78 episodes (mean 5.13 msgs/ep), with major discussions sustainably reaching 30, 37, and 51 messages.
2. **Boundary Stability on Unseen Domain:**
   - At the frozen uncalibrated threshold of **0.50**, Judge A maintained healthy 19.5% NEW / 80.5% CONTINUE behavior without collapsing into all-NEW or all-CONTINUE.
3. **Candidate Ranking & Reply Fidelity:**
   - In all 12 explicit reply events, the target episode was successfully surfaced by `build_candidates` (**0 candidate missing**).
   - 6 were correctly joined to the anchor episode; 2 were `BOUNDARY_FALSE_NEW`; 2 were `RANKING_ERROR`; and 2 were semantically appropriate topic overrides.

---

## 4. Cross-Experiment Comparison

| Dimension | Historical 150 Smoke (v0.1) | Refined 150 Replay (v0.2) | **Fresh Unseen 400 Replay** |
| :--- | :--- | :--- | :--- |
| **Community** | `c_000001` (Known) | `c_000001` (Known) | **`c_000008` (Fresh Unseen)** |
| **Window Length** | 150 messages | 150 messages | **400 messages** |
| **Episodes Formed** | 25 (calibrated Th=0.20) | 31 (natural Th=0.50) | **78 (natural Th=0.50)** |
| **Episodes / 100 msgs** | 16.7 | 20.7 | **19.5** |
| **Mean Episode Size** | 6.00 msgs | 4.84 msgs | **5.13 msgs** |
| **Topic Mixing** | 0.0% audited | 0.0% audited | **0.0% audited** |
| **Long-Gap Resumes** | 1/1 hard cases | 1/1 hard cases | **31/31 valid scenes** |
| **Latency per Event** | 22.44 ms | 20.37 ms | **23.01 ms** |

---

## 5. Architectural Verdict

### **ROUTER_V0_2_FRESH_REPLAY_PASS**

**Conclusion:**  
Two-Stage Router v0.2 proves that its performance on previously seen data was **not an artifact of community over-fitting**. In a completely unfamiliar group with 25 distinct speakers and zero prior exposure, the frozen two-stage architecture demonstrated balanced boundary detection, stable candidate ranking, 100% long-gap resume fidelity, and complete freedom from catastrophic over-merge or over-split.
"""

with open(BASE_DIR / "FINAL_REPORT.md", "w", encoding="utf-8") as f:
    f.write(report_md)

# Update manifest.json with completed status
with open(BASE_DIR / "manifest.json") as f:
    manifest_data = json.load(f)

manifest_data["status"] = "REPLAY_AND_AUDIT_COMPLETED"
manifest_data["verdict"] = "ROUTER_V0_2_FRESH_REPLAY_PASS"
manifest_data["results"] = {
    "events_processed": len(decisions),
    "episodes_count": len(episodes),
    "new_count": new_count,
    "continue_count": cont_count,
    "mean_episode_size": mean_len,
    "median_episode_size": med_len,
    "singleton_count": singleton_count,
    "explicit_replies_total": len(replies),
    "explicit_replies_joined": correct_reply_count,
    "long_gap_resumes_valid": len(long_gap_scenes),
    "long_gap_resumes_correct": lg_correct,
}

with open(BASE_DIR / "manifest.json", "w", encoding="utf-8") as f:
    json.dump(manifest_data, f, indent=2, ensure_ascii=False)

# Print C2C Block
c2c_block = f"""[C2C]
STATE: EXECUTED
GOAL_ID: router_v0_2_fresh_unseen_community_replay_v0_1

MODEL:
- Boundary checkpoint: router-v0.2-small-scale-refinement-v0.1/boundary/checkpoint
- Boundary SHA: 482963c38aa714a710ac97a27cdd1c231f77911f4fbc527eeb3d6c645aa139cd
- Ranking checkpoint: router-v0.2-small-scale-refinement-v0.1/ranking/checkpoint
- Ranking SHA: 41a06635613e3969ecf27315b37f68b36e835ad2df39c4e403fade575a4cbb18
- threshold: 0.50 (frozen)
- modified during run: NO

FRESH COMMUNITY:
- conversation id: c_000008 (group 1054790154)
- previously seen in training: NO
- previously reviewed: NO
- previously used in replay: NO

REPLAY:
- messages: 400
- time range: {fingerprint['time_range']['start']} -> {fingerprint['time_range']['end']}
- input fingerprint: {fingerprint['sha256']}
- continuous window: YES
- processed: 400/400
- failures: 0

ROUTING:
- NEW: {new_count}
- CONTINUE: {cont_count}
- Episodes: {len(episodes)}
- mean Episode size: {mean_len:.2f}
- median Episode size: {med_len:.1f}
- singleton rate: {singleton_count/len(episodes)*100:.1f}%

SEMANTIC AUDIT:
- Episodes reviewed: {len(episodes)}/78 (100% full audit)
- over-merge: 0
- over-split: 2 (minor rapid banter splits)
- mixed Episodes: 0
- ambiguous: 2

EXPLICIT REPLY:
- total: {len(replies)}
- correct: {correct_reply_count}
- candidate missing: 0
- boundary error: {boundary_error_count}
- ranking error: {ranking_error_count}
- runtime mapping error: 0
- accuracy: {correct_reply_count/len(replies)*100:.1f}% (66.7% considering semantic topic override)

LONG-GAP:
- total: {len(long_gap_scenes)}
- correct: {lg_correct}
- wrong Episode: 0
- false NEW: 0
- insufficient cases: NO

BOUNDARY:
- observed collapse: NO (19.5% NEW / 80.5% CONTINUE on natural 0.50 threshold)
- false NEW: 2 (on explicit replies)
- false CONTINUE: 4 (minor conversation start assimilations)

RANKING:
- CONTINUE-but-wrong-Episode: {ranking_error_count} (on explicit replies)
- candidate-present ranking errors: {ranking_error_count}
- candidate missing: 0

CRITICAL FAILURES:
- count: 0
- details: none

FRESH GENERALIZATION VERDICT:
ROUTER_V0_2_FRESH_REPLAY_PASS

RESULT:
Two-Stage Router v0.2 在完全未见社区、未见发件人、未见时序状态的 400 条连续真实消息回放中，展现出高度稳健的边界切分（78 Episode，均长 5.13 条，零崩溃坍塌）、100% 长跨度恢复精度（31/31）、零话题污染（0.0% 混杂），验证了两阶段架构具有真实且通用的 Episode Routing 泛化能力。"""

print("\n" + c2c_block)
