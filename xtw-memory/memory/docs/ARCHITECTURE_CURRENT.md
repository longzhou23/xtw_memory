Project: xtw-memory
Module: current architecture
Version: Router v0.2 / docs v0.1
Status: MAINLINE
Last updated: 2026-09-30
Canonical: YES
Supersedes: one-stage Router as mainline
Superseded by: none

# Current Architecture

## Episode Router v0.2 — MAINLINE

```text
Judge A — Boundary
  NEW / CONTINUE
       ↓ if CONTINUE
Judge B — Ranking
  Which Episode?
```

**Current implementation: 2 independent Laya 322M models.** This is not the Shared Backbone P0 experiment. Boundary input uses current event and recent local context; candidate ranking uses candidate context including summary/recent events and reply-target signal where available. Historical P0 configuration had up to 8 candidates, previous 5 events, candidate summary plus last 2 events. Do not assume every implementation/config copy exactly matches without runtime audit.

2K Refined `router-v0.2-small-scale-refinement-v0.1` is the **CURRENT STABLE BASELINE**. Evidence includes Boundary semantic improvement, Ranking DEV Top-1 72.18%, 150-event regression and subsequent data/refinement work. The 400-message c_000008 replay is consumed and inconclusive after its earlier PASS was withdrawn; it does not upgrade generalization status.

## Write/read system boundary

The broader conceptual path is documented in [PROJECT_MAP.md](PROJECT_MAP.md). Episode-scoped Temporary Memory integration has bounded code/control evidence, but real Router replay was unavailable in its report. `usedMemoryIds ⊆ injectedMemoryIds` and `FORMED_WITH` are provenance contracts, not proof that a model selects useful memories. Final Consolidation/Long-Term Memory are not yet established as a validated integrated mainline.

## Explicit non-mainline experiments

- One-stage scoring: historical; not current mainline.
- Shared Backbone + Dual Head P0: FAILED / PARKED under this specific recipe; Boundary parity gate failed. Does not prove every sharing design fails.
- HNR P0: PARTIAL; +9.02pp HOLDOUT Top-1 missed strict +10pp gate; post-validation supersedes historical PASS language.
- Dual-model 5K scaling: FAIL; see [5K pause record](PAUSED_QUESTIONS.md).
- MoE / Adapter: PARKED.

Do not use the current architecture page to silently rewrite any experiment report. Experiment source of truth is [EXPERIMENT_LEDGER.md](EXPERIMENT_LEDGER.md) plus linked original artifacts.
