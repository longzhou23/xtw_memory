Project: xtw-memory
Module: model registry
Version: v0.1
Status: PARTIAL inventory
Last updated: 2026-09-30
Canonical: YES
Supersedes: none
Superseded by: none

# Model Registry

Checkpoint paths are indexed, not moved. Hashes appear only where a reviewed report states them; for full provenance consult that report's manifest. `—` means not reconciled in this pass.

| Model / artifact | Purpose | Checkpoint / source | Training / evidence | Status / metrics | Superseded by |
|---|---|---|---|---|---|
| Laya 322M baseline | Boundary / early Router | paths in Router experiment manifests | weak silver phases | HISTORICAL; exact SHA must be read from each manifest | refined Two-Stage for current routing |
| Laya 20K | weak-label Router baseline | memory-demo run artifacts / reports | 20K weak silver | historical scaling baseline; TEST_SILVER reused | not a direct substitute for v0.2 two-task architecture |
| HNR `best-dev-ranking` | Ranking improvement | HNR checkpoint path in manifest | 2,007 training cases; holdout consumed | PARTIAL; +9.02pp strict holdout Top-1 gate failure | no approved promotion |
| Boundary Judge A v0.2 | Boundary NEW/CONTINUE | `router-v0.2-small-scale-refinement-v0.1` manifest | 2,210 cases | current stable baseline; DEV Macro F1 .6705 @ .50 | 5K Boundary experiment failed |
| Ranking Judge B v0.2 | Candidate ranking | same experiment manifest | 2,007 unique cases | current stable baseline; DEV Top-1 72.18% | 5K Ranking was flat |
| Shared Backbone P0 | shared Boundary + Ranking | `router-v0.2-shared-backbone-p0/model/` | single seed, 2 epochs; existing data | FAILED / PARKED; Boundary parity failure; ~49.94% params reduction | two independent judges retained |
| Boundary 5K | Boundary scaling | `router-v0.2-dual-model-5k-scaling-v0.1/` | Boundary 5,010 cases | FAIL; 0/27 TRUE_NEW recall at fixed .50 | not a replacement |
| Ranking 5K | candidate ranking scaling | same 5K experiment | Ranking 5,007 cases | FLAT; Top-1 72.18% | v0.2 Ranking baseline retained |
| Bare Laya a01 | alternative provider/replay comparator | memory-demo alternative run `.../real-episode-laya-alt-20260928-a01/` | run report | historical comparator | — |
| Cloud JEV | JudgmentProvider implementation | provider credentials/runtime, no checkpoint path | replay reports r03-r05 | cloud probe/report family; exact provider version sometimes unavailable | not assumed equivalent to Laya/Qwen |
| Qwen System-One | local candidate judgment provider | `Qwen/Qwen3.5-4B-Base` + scorer LoRA; revisions in Qwen benchmark report | TEST_SILVER 400; q02 references | benchmark completed; accuracy 49.50%, Macro F1 .2893; no UNKNOWN output | not current mainline |
| Qwen q02 continuous reference | Router comparison | `memory-demo` run q02 | 150-message historical replay | comparison evidence only; do not transfer old claims to c_000008 corrected report | — |
| JEV benchmark references | judgment baselines | `memory/benchmarks/judgment/episode-routing-v0.1.0/` | benchmark spec, providers | per-run model identity varies; inventory incomplete | — |

## Hash completion needed

This registry is not a checkpoint checksum report. Before any promotion/reproduction, resolve exact checkpoint filenames and SHA-256 from each experiment's `manifest.json`/audit, and do not infer identity from model names or report comparisons. In particular, separate Boundary and Ranking files; do not label shared-backbone, 5K, q02, and current v0.2 as one model.
