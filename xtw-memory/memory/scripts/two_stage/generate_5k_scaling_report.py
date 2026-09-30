#!/usr/bin/env python3
"""Generate scaling comparison, final report, and C2C block for Dual-Model 5K Scaling."""

import hashlib
import json
from pathlib import Path

OUT_BASE = Path("/home/longzhooou/Documents/Programs/小天文设计素材/bot/projects/memory/benchmark-results/router-v0.2-dual-model-5k-scaling-v0.1")

# 1. Load DEV metrics
with open(OUT_BASE / "evaluation/boundary.json") as f:
    b_5k = json.load(f)

with open(OUT_BASE / "evaluation/ranking.json") as f:
    r_5k = json.load(f)

with open(OUT_BASE / "replay-150/results.json") as f:
    replay_5k = json.load(f)

with open(OUT_BASE / "datasets/manifest.json") as f:
    ds_manifest = json.load(f)

# Baseline references
b_baseline = {
    "macro_f1": 0.6704723177979356,
    "true_new": {
        "precision": 0.47368421052631576,
        "recall": 0.3333333333333333,
        "f1": 0.391304347826087,
    },
    "false_continue": 18,
    "false_new": 10,
}

r_baseline = {
    "top1": 0.7218045112781954,
    "mrr": 0.8246374865735767,
    "hard_negatives": {
        "top1": 0.7131782945736435,
    }
}

replay_baseline = {
    "episodes_count": 31,
    "new_count": 31,
    "continue_count": 119,
    "mean_episode_length": 4.84,
    "explicit_replies_joined": 15,
    "explicit_replies_total": 17,
    "long_gap_10087_rejoined": True,
    "over_merge_collapse": False,
}

scaling_comp = {
    "goal_id": "router_v0_2_dual_model_5k_scaling_v0_1",
    "verdict": "DUAL_MODEL_5K_SCALING_FAIL",
    "scaling_signal": {
        "boundary": "NEGATIVE",
        "ranking": "FLAT",
        "overall": "NEGATIVE",
    },
    "boundary_scaling": {
        "baseline_2k": b_baseline,
        "scaled_5k": b_5k,
        "delta": {
            "macro_f1": b_5k["macro_f1"] - b_baseline["macro_f1"],
            "true_new_recall": b_5k["true_new"]["recall"] - b_baseline["true_new"]["recall"],
            "true_new_f1": b_5k["true_new"]["f1"] - b_baseline["true_new"]["f1"],
            "false_continue_increase": b_5k["false_continue"] - b_baseline["false_continue"],
        },
        "verdict": "NEGATIVE",
        "analysis": "Boundary Judge collapsed into majority-CONTINUE predictions (Recall dropped from 33.3% to 0.0%, False Continue rose to 27/27). More multi-community data without balanced representation or localized calibration induced severe boundary collapse."
    },
    "ranking_scaling": {
        "baseline_2k": r_baseline,
        "scaled_5k": r_5k,
        "delta": {
            "top1": r_5k["top1"] - r_baseline["top1"],
            "mrr": r_5k["mrr"] - r_baseline["mrr"],
            "hard_negative_top1": r_5k["hard_negatives"]["top1"] - r_baseline["hard_negatives"]["top1"],
        },
        "verdict": "FLAT",
        "analysis": "Ranking Judge performance saturated completely: Top-1 remained identical at 72.18% (0.00pp delta), MRR slightly rose from 0.8246 to 0.8263 (+0.0017), and Hard-negative Top-1 marginally rose from 71.32% to 71.71% (+0.39pp). Scaling data by 2.5x produced zero meaningful ranking gains on Laya 322M representation."
    },
    "replay_150_regression": {
        "baseline_2k": replay_baseline,
        "scaled_5k": {
            "episodes_count": replay_5k["episodes_count"],
            "new_count": replay_5k["new_count"],
            "continue_count": replay_5k["continue_count"],
            "mean_episode_length": replay_5k["mean_episode_length"],
            "explicit_replies_joined": replay_5k["explicit_replies"]["joined"],
            "explicit_replies_total": replay_5k["explicit_replies"]["total"],
            "long_gap_10087_rejoined": replay_5k["long_gap_10087_rejoined"],
        },
        "verdict": "CATASTROPHIC_OVER_MERGE_REGRESSION",
        "analysis": "Due to Boundary collapse, the router generated only 3 episodes for 150 events (mean size 50.00), completely losing thread boundaries and merging unrelated domains (e.g. food and PC disk cleanup) into monster threads. Known long-gap case 10087 failed to rejoin."
    },
    "fresh_replay_status": {
        "authorized": False,
        "reason": "Per Simple Spec Section 20, fresh unseen community replay is strictly conditioned on offline evaluation and regression replay showing no significant degradation. Because Boundary 5K offline and 150 regression suffered severe degradation, fresh replay was not authorized and was halted."
    }
}

with open(OUT_BASE / "evaluation/scaling-comparison.json", "w", encoding="utf-8") as f:
    json.dump(scaling_comp, f, indent=2, ensure_ascii=False)

# Update root manifest.json
root_manifest = {
    "experiment_id": "router_v0_2_dual_model_5k_scaling_v0_1",
    "status": "COMPLETED",
    "verdict": "DUAL_MODEL_5K_SCALING_FAIL",
    "scaling_verdicts": {
        "boundary": "NEGATIVE",
        "ranking": "FLAT",
        "overall": "NEGATIVE",
    },
    "datasets": ds_manifest["datasets"],
    "checkpoints": {
        "boundary_5k": {
            "checkpoint_dir": str(OUT_BASE / "training/boundary/checkpoint"),
            "selected_epoch": 2,
        },
        "ranking_5k": {
            "checkpoint_dir": str(OUT_BASE / "training/ranking/checkpoint"),
            "selected_epoch": 1,
        }
    },
    "offline_dev_results": {
        "boundary": b_5k,
        "ranking": r_5k,
    },
    "replay_150_regression": {
        "episodes": replay_5k["episodes_count"],
        "new": replay_5k["new_count"],
        "continue": replay_5k["continue_count"],
        "mean_length": replay_5k["mean_episode_length"],
        "explicit_replies_accuracy": replay_5k["explicit_replies"]["accuracy"],
        "long_gap_10087_rejoined": replay_5k["long_gap_10087_rejoined"],
        "verdict": "CATASTROPHIC_OVER_MERGE",
    },
    "fresh_unseen_replay": {
        "status": "NOT_AUTHORIZED_DUE_TO_REGRESSION",
    }
}

with open(OUT_BASE / "manifest.json", "w", encoding="utf-8") as f:
    json.dump(root_manifest, f, indent=2, ensure_ascii=False)

# Generate FINAL_REPORT.md
report_md = f"""# Router v0.2 — Dual-Model 5K Multi-Community Scaling Final Report

**Date:** September 30, 2026  
**Goal ID:** `router_v0_2_dual_model_5k_scaling_v0_1`  
**Verdict:** **DUAL_MODEL_5K_SCALING_FAIL**  
**Scaling Signal:** **NEGATIVE**  

---

## 1. Executive Summary

This benchmark tests the hypothesis that scaling training data from ~2K to ~5K cases on two independent Laya 322M models (Boundary Judge A and Ranking Judge B) using multi-community real chat data yields performance improvements without altering the Two-Stage Router architecture.

The empirical findings refute this hypothesis for simple multi-community data volume scaling:
1. **Boundary Judge A 5K (NEGATIVE):** DEV Macro F1 dropped steeply from **0.6705 to 0.4765 (-0.1940)**. The model collapsed into predicting almost exclusively `CONTINUE`, missing **27 out of 27 TRUE_NEW cases (Recall = 0.00%)**.
2. **Ranking Judge B 5K (FLAT / SATURATING):** DEV Top-1 remained identical at **72.18% (0.00pp gain)**, MRR marginally shifted from **0.8246 to 0.8263 (+0.0017)**, and Hard-Negative Top-1 marginally moved from **71.32% to 71.71% (+0.39pp)**. Adding 3,000 extra cases produced no meaningful ranking capability gains.
3. **150 Continuous Regression Replay (Catastrophic Over-Merge):** Because the 5K Boundary model failed to detect new topic boundaries, the 150-message continuous replay collapsed from **31 clean episodes in 2K baseline down to just 3 monster episodes** (mean length 50.00 messages). This reintroduced the severe over-merge failure mode of early baseline models.
4. **Fresh Unseen-Community Replay (Halted):** In strict accordance with Spec Section 20 ("Fresh evaluation is permitted only if 5K offline + regression do not degrade"), fresh replay was **not authorized** and was halted.

---

## 2. Dataset Construction & Invariant Audit

### Strict Nesting (`2K baseline ⊂ 5K`):
- **Boundary 5K:**
  - File: `datasets/boundary-5k/boundary_train_5k.jsonl` (SHA-256: `3efce5113103eeed3934c9053e2913e000ac51b533407d9ca69f5cdf49d87514`)
  - Total Unique Cases: **5,010**
  - Baseline nesting: All 2,210 cases from baseline are strictly preserved.
  - Multi-community expansion: 2,800 new cases mined across 5 communities (`c_000003` to `c_000007`) with strict dual-blind consensus (Pass A and Pass B agreement).
  - Breakdown: 3,611 TRUE_CONTINUE (72.1%), 1,399 TRUE_NEW (27.9%).
  - Community Balance: `c_000001`: 945, `c_000003`: 815, `c_000004`: 797, `c_000005`: 808, `c_000006`: 799, `c_000007`: 846. No community dominates.
- **Ranking 5K:**
  - File: `datasets/ranking-5k/ranking_train_5k.jsonl` (SHA-256: `1cb626423e42c33ab3db64f806454849c2ef2595a0d9690b196f9ff2022a2b98`)
  - Total Unique Cases: **5,007**
  - Baseline nesting: All 2,007 cases from baseline (822 semantic + 1,178 weak + 7 runtime bank) strictly preserved.
  - Multi-community expansion: 1,900 new multi-community semantic CONTINUE cases with hard negative competing candidates and `[包含回复目标]` features.
  - Additional weak cases: 1,100 weak CONTINUE cases from train-20k.

---

## 3. Offline Evaluation & Scaling Diagnostics

### Boundary Evaluation (DEV 301 natural cases):
| Metric | 2.2K Baseline | 5K Scaled Model | Delta | Verdict |
| :--- | :---: | :---: | :---: | :---: |
| **Macro F1** | **0.6705** | **0.4765** | **-0.1940** | **NEGATIVE** |
| **Accuracy** | 90.70% | 91.03% | +0.33pp | (trivial majority baseline) |
| **TRUE_NEW Precision** | 47.37% | 0.00% | -47.37pp | Severe collapse |
| **TRUE_NEW Recall** | 33.33% (9/27) | **0.00% (0/27)** | **-33.33pp** | Complete miss of boundaries |
| **TRUE_NEW F1** | **0.3913** | **0.0000** | **-0.3913** | Collapsed |
| **False Continue** | 18 / 27 | **27 / 27** | +9 failures | 100% false continue |
| **False New** | 10 / 274 | 0 / 274 | -10 | Biased toward CONTINUE |

### Ranking Evaluation (DEV 266 rankable cases):
| Metric | 2K Baseline | 5K Scaled Model | Delta | Verdict |
| :--- | :---: | :---: | :---: | :---: |
| **Top-1 Accuracy** | **72.18%** | **72.18%** | **0.00pp** | **FLAT** |
| **Top-2 Accuracy** | 84.96% | 84.96% | 0.00pp | FLAT |
| **MRR** | **0.8246** | **0.8263** | **+0.0017** | Marginal / Flat |
| **Hard-Negative Top-1** | **71.32%** | **71.71%** | **+0.39pp** | Marginal / Flat |

---

## 4. Frozen 150 Regression Replay Performance

| Dimension | 2K Refined Baseline | 5K Scaled Models | Impact & Evidence |
| :--- | :---: | :---: | :--- |
| **Total Events** | 150 | 150 | 100% processed |
| **Episodes Formed** | **31** | **3** | **Catastrophic Over-Merge** (lost 28 episode boundaries) |
| **NEW Decisions** | **31** | **3** | Boundary Judge collapsed to 98% CONTINUE |
| **CONTINUE Decisions** | 119 | 147 | Over-absorption of events |
| **Mean Episode Size** | **4.84 msgs** | **50.00 msgs** | Monster episodes formed |
| **Explicit Reply Joined** | 15/17 (88.2%) | 16/17 (94.1%)* | *Artificial inflation: nearly all events lumped into 1 episode |
| **Hard Case 10087 (gap 30)** | Rejoined (ep 3) | **Failed** | Drifts into runtime_ep_1 instead of target ep 3 |
| **Topic Mixing (10047 vs 10049)** | Separated | **Mixed (ep 1)** | Food & PC disk cleanup collapsed into same episode |

---

## 5. Architectural Conclusions & Policy Compliance

1. **Failure Attribution:**  
   - Blindly scaling multi-community data volume by ~2.5x without task-specialized data balance or curriculum training damages boundary discrimination. Because real chat streams are dominated by continuation, naive data expansion increases majority bias, driving Boundary Judge A into a trivial minimum where it predicts `CONTINUE` for almost every event.
   - For Ranking Judge B, 322M capacity appears saturated at ~72% Top-1 under current candidate window formats; adding more weak or heuristically mined CONTINUE cases yields zero Top-1 scaling gains.
2. **Next Steps Policy (Spec Section 27, 28, 32):**
   - **Do NOT scale to 10K:** Expanding raw volume further would amplify boundary collapse.
   - **Shared-model & MoE research:** Remains PARKED.
   - **Mainline status:** Keep the 2K Refined Two-Stage Router v0.2 (`router-v0.2-small-scale-refinement-v0.1`) as the stable, production-grade checkpoint.
"""

with open(OUT_BASE / "FINAL_REPORT.md", "w", encoding="utf-8") as f:
    f.write(report_md)

# C2C Block
c2c_block = f"""[C2C]
STATE: EXECUTED
GOAL_ID: router_v0_2_dual_model_5k_scaling_v0_1
ARCHITECTURE:
- Boundary model: independent Laya 322M
- Ranking model: independent Laya 322M
- shared backbone: NO
- architecture modified: NO
BOUNDARY DATA:
- unique cases: 5010
- CONTINUE: 3611
- TRUE_NEW: 1399
- communities: 6 (c_000001, c_000003, c_000004, c_000005, c_000006, c_000007)
- 2.2K nested in 5K: YES (exact 2210 subset verified)
- dataset SHA: 3efce5113103eeed3934c9053e2913e000ac51b533407d9ca69f5cdf49d87514
RANKING DATA:
- unique cases: 5007
- semantic cases: 2722 (822 baseline + 1900 multi-community)
- weak cases: 2278 (1178 baseline + 1100 weak expansion)
- runtime hard negatives: 7
- explicit reply cases: 462
- communities: 7
- 2K nested in 5K: YES (exact 2007 subset verified)
- dataset SHA: 1cb626423e42c33ab3db64f806454849c2ef2595a0d9690b196f9ff2022a2b98
BOUNDARY 5K:
- Macro F1: 0.4765
- baseline Macro F1: 0.6705
- delta: -0.1940
- TRUE_NEW P/R/F1: 0.0000 / 0.0000 / 0.0000
- False Continue: 27 / 27
- False New: 0 / 274
- scaling verdict: NEGATIVE
RANKING 5K:
- Top-1: 72.18%
- baseline Top-1: 72.18%
- delta: 0.00pp
- MRR: 0.8263
- baseline MRR: 0.8246
- Hard-negative Top-1: 71.71%
- scaling verdict: FLAT
150 REGRESSION:
- Episodes: 3
- NEW: 3
- CONTINUE: 147
- explicit reply correct: 16/17 (artifact of monster episode)
- boundary errors: 28 (severe boundary collapse)
- ranking errors: 1 (case 10087 drifted)
- mixing: CONFIRMED (food 10047 and PC disk cleanup 10049 merged into ep 1)
- over-merge: SEVERE (mean length 50.00 msgs/ep)
- over-split: 0
- long-gap: FAILED (case 10087 failed to rejoin target episode 3)
- regression status: REGRESSED_CATASTROPHIC_OVER_MERGE
FRESH UNSEEN COMMUNITY:
- conversation: NONE
- messages: 0
- fingerprint: NONE
- prior training exposure: NO
- processed: 0
- Episodes: 0
- mixing: N/A
- over-merge: N/A
- over-split: N/A
- explicit reply: N/A
- long-gap: N/A
- critical failures: 0
- status: NOT_AUTHORIZED_PER_SPEC_SECTION_20
SCALING:
- Boundary: NEGATIVE
- Ranking: FLAT
- overall: NEGATIVE
VERDICT:
DUAL_MODEL_5K_SCALING_FAIL
NEXT:
- proceed to 10K: NO
- shared-model research: PARKED
- MoE research: PARKED
RESULT:
Two-Stage 双 Laya 架构在单纯增加多社区数据到 5K 规模后未获得正面 scaling 收益：Boundary 判定发生严重 CONTINUE 坍塌（Macro F1 -0.1940，TRUE_NEW 检出率跌至 0%），Ranking 判定完全饱和（Top-1 持平 72.18%），并在 150 回放中退化为 3 个巨型 Episode 的恶性过度合并；严格证明单纯堆叠未校准的非平衡语料无法替代精细边界挖掘。"""

print("\n" + c2c_block)
