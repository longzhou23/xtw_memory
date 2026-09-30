Project: xtw-memory
Module: experiment ledger
Version: v0.1
Status: CURRENT
Last updated: 2026-09-30
Canonical: YES
Supersedes: none
Superseded by: none

# Experiment Ledger

Evidence levels: **L0** exploratory/diagnostic; **L1** internal reproducible/frozen-input experiment; **L2** independent/zero-trust audit or reproduction; **L3** sealed/frozen holdout (consumed status still applies); **L4** fresh unseen-community evaluation with eligibility and semantic audit. Levels indicate design strength, not “truth”; reports below do not necessarily reach L4. For multi-evidence work, level is conservative and qualified in Notes.

| ID / version | Goal; data/model | Main result (short) | Status | Level | Evidence |
|---|---|---|---|---|---|
| Recall baseline / improved Recall | memory-demo Recall P0 and follow-ups | P0 stage frozen; optimizations/history retained; silver benchmark repeatedly used | FROZEN baseline | L1 | [`Recall P0 archive`](../../components/memory-demo/archive/recall-p0-2026-09-22/README.md); [`optimization notes`](../../components/memory-demo/docs/experiments/RECALL_OPTIMIZATION.md) |
| Diffusion zero-edge validation | 2,196-node Cognitive Unit graph, 0 edges; 50 DEV | synthetic invariants pass; no real non-seed rescue possible | EXPERIMENTAL / limitation | L1 | [`diffusion report`](../../components/memory-demo/benchmark-results/diffusion-p0/FINAL_REPORT.md) |
| Temporary Memory Fabric P0 | deterministic 120-event adapter replay | 102 spills/temp memories; 49 associations; no LLM calls | PARTIAL / micro replay | L1 | [`fabric report`](../../components/memory-demo/benchmark-results/temporary-fabric-p0/FINAL_REPORT.md) |
| Temporary Fabric dynamics P0 | dynamics controls | see original final report; not general real-chat proof | EXPERIMENT | L0-L1 | [`dynamics report`](../../components/memory-demo/benchmark-results/temporary-fabric-p0-dynamics/FINAL_REPORT.md) |
| Write Provenance P0 | 20 consecutive raw events; configured cloud provider, 14 writes | 14 empty usedMemoryIds; no positive usage selection | PARTIAL | L1 | [`provenance report`](../../components/memory-demo/benchmark-results/memory-write-provenance-p0/FINAL_REPORT.md) |
| Write Provenance control | controlled comparison | original artifact retained; review before using as model-quality claim | EXPERIMENT | L0-L1 | [`control report`](../../components/memory-demo/benchmark-results/memory-write-provenance-control/FINAL_REPORT.md) |
| Episode-scoped Temporary Write P0 | synthetic-realistic private facts, 22 cases, cloud comparison | isolation boundary verified; 2 unnecessary same-Episode uses; Router unavailable; freeze withheld | PARTIAL | L1 | [`scoped write report`](../../components/memory-demo/benchmark-results/episode-scoped-write-p0/FINAL_REPORT.md) |
| Memory-conditioned Write P0 | controlled writer runs | retain reports; precise verdict requires report review | EXPERIMENT | L0-L1 | [`run report`](../../components/memory-demo/benchmark-results/memory-conditioned-write-p0/FINAL_REPORT.md) |
| Router P0 | early Episode routing; JEV pointwise | context/candidate findings; historical frozen config | FROZEN historical | L1 | [`P0 memo`](../docs/Episode_Router_P0_阶段总结与冻结配置.md) |
| JEV benchmark | judgment v0.1.0 | benchmark artifacts include spec, splits, audits | PARTIAL / silver | L1-L2 | [`reports`](../reports/JUDGMENT_DATASET_REPORT-v0.1.0.md), [`benchmark spec`](../benchmarks/judgment/episode-routing-v0.1.0/benchmark_spec.json) |
| Cloud JEV r05 | cloud JEV run | report inventory found; detailed conclusion needs source-specific review | UNKNOWN/PARTIAL | L0-L1 | [`runtime report`](../../components/memory-demo/benchmark-results/real-episode-temporary-fabric-replay-p0/runs/real-episode-replay-20260928-r05/FINAL_REPORT.md) |
| Bare Laya a01 | local Laya baseline | comparative anchor in later reports | HISTORICAL | L1 | [`comparison`](../../components/memory-demo/benchmark-results/real-episode-temporary-fabric-laya-alternative-p0/runs/real-episode-laya-alt-20260928-a01/FINAL_REPORT.md) |
| Qwen q02 / System-One benchmark | Qwen 3.5 4B scorer; TEST_SILVER 400 | independent judgment result 49.50% accuracy, Macro F1 .2893; forced binary, zero UNKNOWN | COMPLETED; TEST_SILVER | L1-L2 | [`benchmark report`](../../components/memory-demo/benchmark-results/qwen-system-one-frozen-judgment-benchmark-v0.1-20260929/FINAL_REPORT.md) |
| Weak-label dataset audit / Laya scaling 1K–20K | weak silver, Laya 322M | scaling report shows DEV gain; TEST_SILVER reused, not fresh | HISTORICAL BASELINE | L1 | [`scaling report`](../benchmark-results/laya-episode-routing-weak-silver-scaling-v0.2/SCALING_REPORT.md) |
| Laya 1K / 2K / 2.8K | weak silver phases | historical rows retained; score trend in scaling report | HISTORICAL | L1 | [`scaling matrix`](../benchmark-results/laya-episode-routing-weak-silver-scaling-v0.2/SCALING_REPORT.md) |
| Laya 5K / 10K / 20K (weak-silver) | same reused TEST_SILVER | DEV Macro F1 0.6161 / .6522 / .6767; not equivalent to dual-model semantic 5K | HISTORICAL | L1 | [`scaling matrix`](../benchmark-results/laya-episode-routing-weak-silver-scaling-v0.2/SCALING_REPORT.md) |
| Laya Zero Trust Audit | source/data/checkpoint audit | audit artifact exists; consult for exact reproduced scope | AUDITED | L2 | [`audit`](../benchmark-results/laya-episode-routing-zero-trust-audit-v0.1/AUDIT_REPORT.md) |
| Laya 20K system replay | 2K clean events, HNR report | replay metrics in HNR original report; do not conflate with HNR HOLDOUT gate | HISTORICAL | L1 | [`HNR report`](../benchmark-results/laya-episode-routing-hard-negative-ranking-v0.1/FINAL_REPORT.md) |
| HNR P0 | Laya 322M hard-negative ranking | ranking improved; strict +10pp HOLDOUT gate failed at +9.02pp; HOLDOUT consumed; post-validation partial | PARTIAL / PARKED | L3 consumed | [`post-validation status`](../benchmark-results/laya-episode-routing-hard-negative-ranking-v0.1/evaluation/POST_VALIDATION_STATUS.md); [`original report with correction header`](../benchmark-results/laya-episode-routing-hard-negative-ranking-v0.1/FINAL_REPORT.md) |
| HNR post-validation | controlled ablation/post-validation | supports limited single-seed DEV evidence; does not cure frozen checkpoint failure | PARTIAL | L1-L2 | [`post-validation C2C`](../benchmark-results/laya-episode-routing-hard-negative-ranking-v0.1/evaluation/POST_VALIDATION_C2C.md) |
| Two-Stage smoke | Router v0.2 two independent judges | architectural smoke; early regression evidence | HISTORICAL | L1 | [`smoke`](../benchmark-results/router-v0.2-two-stage-smoke-v0.1/FINAL_REPORT.md) |
| Two-Stage refinement / 2K | semantic multi-community expansion + 150 replay | Boundary Macro F1 .6705; Ranking Top-1 72.18%; 31 episodes, 150 replay | CURRENT STABLE BASELINE | L1 | [`refinement report`](../benchmark-results/router-v0.2-small-scale-refinement-v0.1/FINAL_REPORT.md) |
| Fresh unseen-community c_000008 replay (400) | 400 records; frozen artifacts | prior PASS withdrawn; ordering/quote-link/semantic-audit defects; consumed, inconclusive | CONSUMED / INCONCLUSIVE | L0-L1 | [`corrected report`](../benchmark-results/router-v0.2-fresh-unseen-community-replay-v0.1/FINAL_REPORT.md); [`eligibility audit`](../benchmark-results/router-v0.2-fresh-unseen-community-replay-v0.1/ELIGIBILITY_AUDIT.md) |
| Shared Backbone P0 | shared encoder + two heads; 2K datasets | ~49.94% params reduction; Boundary gate failed; ranking near parity | FAILED / PARKED (this formulation) | L1 | [`report`](../benchmark-results/router-v0.2-shared-backbone-p0/FINAL_REPORT.md) |
| Dual-model 5K scaling | 5,010 Boundary / 5,007 Ranking; independent Laya models | Boundary collapse, Ranking flat, 150 replay 3 episodes; root cause NOT ESTABLISHED | FAIL / PAUSED forensic | L1 | [`report`](../benchmark-results/router-v0.2-dual-model-5k-scaling-v0.1/FINAL_REPORT.md) |

Missing or incomplete evidence references are explicitly marked; this ledger is not a replacement for original reports. Also see [dataset registry](DATASET_REGISTRY.md), [model registry](MODEL_REGISTRY.md), and [inventory](DOCUMENT_INVENTORY.md).
