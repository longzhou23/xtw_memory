Project: xtw-memory
Module: specification index
Version: v0.1
Status: PARTIAL inventory
Last updated: 2026-09-30
Canonical: YES
Supersedes: none
Superseded by: none

# Spec Index

This is a content-reviewed starter index, not a complete spec archive. Specs remain at original paths.

| Spec / design document | Goal | Date | Executed? / result | Superseded? | Related evidence |
|---|---|---|---|---|---|
| Episode Router P0 memo | establish usable P0 Router inputs/policy | 2026-09-21 | yes; frozen historical P0 | no; later v0.2 is current mainline | [`memo`](Episode_Router_P0_阶段总结与冻结配置.md) |
| Router v0.2 two-stage smoke/refinement specs | separate boundary from candidate ranking | 2026-09 (exact per artifact) | yes; 2K refined baseline retained | smoke superseded by refinement, not deleted | [`smoke`](../benchmark-results/router-v0.2-two-stage-smoke-v0.1/FINAL_REPORT.md), [`refinement`](../benchmark-results/router-v0.2-small-scale-refinement-v0.1/FINAL_REPORT.md) |
| HNR P0 spec/recipe | evaluate hard-negative ranking with gates | 2026-09-29 | yes; +9.02pp gate miss; partial after validation | old PASS text superseded by post-validation correction | [`status`](../benchmark-results/laya-episode-routing-hard-negative-ranking-v0.1/evaluation/POST_VALIDATION_STATUS.md) |
| Shared Backbone P0 spec/manifest | test one shared trunk with two heads | 2026-09 | yes; Boundary parity fail | no; parked formulation | [`report`](../benchmark-results/router-v0.2-shared-backbone-p0/FINAL_REPORT.md) |
| Dual-model 5K scaling spec/manifest | test multi-community scaling without architecture change | 2026-09-30 | yes; FAIL; no fresh replay | current failure, forensic paused | [`report`](../benchmark-results/router-v0.2-dual-model-5k-scaling-v0.1/FINAL_REPORT.md) |
| Frozen judgment benchmark spec | define judgment benchmark v0.1.0 | see JSON metadata | executed; TEST_SILVER status applies | not treated as gold | [`spec`](../benchmarks/judgment/episode-routing-v0.1.0/benchmark_spec.json) |
| memory-demo Recall/Diffusion/Write freeze notes | freeze or constrain P0 stages | 2026-09-22 onward | multiple staged experiments; see original docs | historical stage docs retained | [`project docs`](../../components/memory-demo/docs/) |

Other reports that function as specs, audit plans, or phase gates are not yet fully reconciled. See [`DOCUMENT_INVENTORY.md`](DOCUMENT_INVENTORY.md); do not infer execution/result from title alone.
