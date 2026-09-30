Project: xtw-memory
Module: Router history
Version: v0.1
Status: HISTORICAL SUMMARY
Last updated: 2026-09-30
Canonical: YES
Supersedes: none
Superseded by: none

# Router Evolution

Order below follows the experiment lineage visible in reviewed reports; where exact chronology/spec linkage is not confirmed it is called out rather than invented.

1. **Router P0.** Why: make an Episode router usable for downstream memory. Found candidate coverage was sufficient in a small 300-message benchmark; local context helped short/ambiguous messages. Conclusion: concise public context plus candidate-specific context; freeze P0 inputs rather than continue sweeps. Next: evaluate on broader routing tasks. Evidence: `../../Episode_Router_P0_阶段总结与冻结配置.md`.
2. **One-stage scoring.** Why: score candidate Episodes directly with JEV/Laya-style scoring. Found one decision conflates boundary detection and candidate identity; early replay weaknesses motivate separating tasks. Conclusion: historical, no longer mainline. Next: two-stage design. Exact report mapping is incomplete.
3. **Weak-label scaling.** Why: improve weak judgment model with larger training sets. Found DEV Macro F1 increased from 2.8K to 5K/10K/20K, while TEST_SILVER was reused and not a fresh holdout. Conclusion: valid internal scaling observation, not semantic-gold generalization. Next: improve label/task quality rather than equate quantity with quality.
4. **HNR.** Why: improve candidate ranking under hard negatives. Found ranking improved on a sealed holdout but +9.02pp missed strict +10pp gate; post-validation marked PARTIAL, holdout consumed. Conclusion: retain evidence, do not promote checkpoint as passed. Next: no automatic follow-up.
5. **Two-Stage architecture.** Why: separate “NEW or CONTINUE?” from “Which Episode?”. Found refinement resolved substantial candidate-ranking/reply issues on the frozen 150 replay; 2K Refined chosen as stable baseline. Conclusion: MAINLINE with two independent models.
6. **Multi-community semantic expansion.** Why: assess improvement beyond original community. Found a dual-blind-reviewed set from five communities used in refinement and later 5K scale. Conclusion: limited cross-community evidence; not unlimited generalization.
7. **Shared Backbone P0.** Why: reduce duplicate parameters/memory while preserving two tasks. Found ~half parameters and reduced allocated memory, but Boundary parity failed; one-seed setup limits causal attribution. Conclusion: this formulation FAILED/PARKED, not all sharing designs.
8. **5K scaling.** Why: increase two-model training data to ~5K without architecture change. Found Boundary collapsed to CONTINUE, Ranking flat, 150 replay over-merged to 3 episodes. Conclusion: FAIL; root cause NOT ESTABLISHED; no 10K scale.
9. **Fresh c_000008 replay correction.** A 400-record replay was initially presented as PASS, but corrected final report withdrew that verdict: chronology, quote matching, semantic audit and runtime equivalence were inadequate. Conclusion: CONSUMED / INCONCLUSIVE; never describe as untouched fresh evidence.

Full experiment results stay in the [ledger](../EXPERIMENT_LEDGER.md) and original `benchmark-results/` artifacts. This summary does not rewrite those records.
