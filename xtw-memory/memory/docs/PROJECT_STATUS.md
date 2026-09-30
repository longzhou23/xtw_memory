Project: xtw-memory
Module: project status
Version: v0.1
Status: CURRENT
Last updated: 2026-09-30
Canonical: YES
Supersedes: none
Superseded by: none

# Project Status

| Module | Status | Evidence / note |
|---|---|---|
| Episode Lifecycle | FROZEN (P0) | memory-demo archive `archive/recall-p0-2026-09-22/docs/RECALL_P0_STAGE_SUMMARY.md`; lifecycle memo in `docs/memos/agent/` |
| Temporary Memory Fabric | FROZEN baseline / integration open | `components/memory-demo/benchmark-results/temporary-fabric-p0/FINAL_REPORT.md`; 120-event deterministic micro replay, not model-quality evidence |
| Write Provenance | PARTIAL | `components/memory-demo/benchmark-results/memory-write-provenance-p0/FINAL_REPORT.md`; 14 real writes, zero positive usage selection |
| Episode-scoped writer | PARTIAL | `components/memory-demo/benchmark-results/episode-scoped-write-p0/FINAL_REPORT.md`; isolation verified in bounded controls, two unnecessary same-Episode links, real Router unavailable |
| Recall | FROZEN BASELINE (historical P0) | `components/memory-demo/archive/recall-p0-2026-09-22/`; TEST_SILVER consumed/reused; not a fresh estimate |
| Diffusion | EXPERIMENTAL | `components/memory-demo/benchmark-results/diffusion-p0/FINAL_REPORT.md`; synthetic invariants passed, evaluated graph had 0 edges |
| Router v0.2 | CURRENT STABLE BASELINE | `router-v0.2-small-scale-refinement-v0.1`; separate Boundary and Ranking Laya 322M models |
| Final Consolidation | TODO / NOT ESTABLISHED | No end-to-end canonical completion evidence found in reviewed sources |
| Long-Term Memory | NOT STARTED as end-to-end validated path | Architecture concept exists; integration/quality proof unresolved |
| PageIndex exploration | PARKED | See `PARKING_LOT.md` |
| Router 5K Boundary forensic | PAUSED | See `PAUSED_QUESTIONS.md`; do not continue automatically |

## Router evidence snapshot

- 2K Refined: stable baseline; Boundary DEV Macro F1 0.6705, Ranking DEV Top-1 72.18%, 150-event regression produced 31 episodes. This is internal evidence, not a pristine holdout claim.
- HNR P0: PARTIAL; ranking improved but strict +10pp gate missed at +9.02pp; its HOLDOUT was consumed. Post-validation is authoritative over the original report body.
- Shared Backbone P0: FAILED / PARKED under this formulation; Boundary parity failed. Do not generalize to all sharing designs.
- Dual-model 5K: FAIL; fixed-0.50 Boundary collapsed to CONTINUE, Ranking flat, 150 replay produced 3 episodes. Root cause not established.
- c_000008 400 replay: CONSUMED, INCONCLUSIVE; earlier PASS claims were withdrawn in the corrected report.

See [experiment ledger](EXPERIMENT_LEDGER.md) for evidence levels and report links.
