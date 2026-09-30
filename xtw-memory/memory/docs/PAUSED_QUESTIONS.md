Project: xtw-memory
Module: paused questions
Version: v0.1
Status: PAUSED
Last updated: 2026-09-30
Canonical: YES
Supersedes: none
Superseded by: none

# Paused Questions

## 5K Boundary Failure

**Status: PAUSED. DO NOT CONTINUE AUTOMATICALLY.** See [`dual-model 5K final report`](../benchmark-results/router-v0.2-dual-model-5k-scaling-v0.1/FINAL_REPORT.md).

Observed: fixed threshold 0.50 Boundary collapsed to CONTINUE (0/27 TRUE_NEW recall; Macro F1 0.4765 vs 2.2K baseline 0.6705); Ranking Top-1 flat at 72.18%; frozen 150 replay collapsed from 31 episodes to 3. Fresh replay was not authorized. **ROOT CAUSE: NOT YET ESTABLISHED.** The report contains hypotheses, not a proven causal finding. Do not state CONTINUE class proportion as the established cause.

Unresolved hypotheses:

A. calibration shift
B. semantic discrimination collapse
C. dataset semantic mismatch
D. optimization issue
E. other

If and only if the user explicitly restarts this investigation, possible threshold-free diagnostics (not an authorization to run) include: score distributions by gold class and epoch; AUROC/AUPRC; threshold-free separation; best-achievable Macro F1; epoch-wise score analysis. Preserve the frozen data/checkpoints/reports and preregister the allowed diagnostics first. No 10K expansion, threshold tuning on consumed evaluation, or fresh replay is implied.

Other paused/parked architecture ideas are tracked in [PARKING_LOT.md](PARKING_LOT.md).
