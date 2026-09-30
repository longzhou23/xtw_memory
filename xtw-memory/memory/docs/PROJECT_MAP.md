Project: xtw-memory
Module: project map
Version: v0.1
Status: CURRENT
Last updated: 2026-09-30
Canonical: YES
Supersedes: none
Superseded by: none

# Project Map

Status labels describe evidence in the reviewed workspace, not intended design.

```text
Raw Chat                         DONE (source exists; no completeness claim)
   ↓
Event                            DONE (normalization/data pipeline exists)
   ↓
Episode Router                   CURRENT / FROZEN baseline: Two-Stage v0.2
   ↓
Episode Lifecycle                FROZEN P0 (bounded implementation/evidence)
   ↓
Working Context                  FROZEN P0 (per Episode FIFO in tested path)
   ↓
Temporary Memory                 EXPERIMENTAL / partial integration evidence
   ↓
Memory Write                     PARTIAL (cloud probes; provenance limits)
   ↓
FORMED_WITH                      FROZEN contract in writer path; real quality limited
   ↓
Final Consolidation              NOT ESTABLISHED / TODO
   ↓
Long-Term Memory                 NOT STARTED as validated end-to-end flow
   ↓
Recall                           FROZEN BASELINE (historical P0; silver data reused)
   ↓
Diffusion                        EXPERIMENTAL (zero-edge real graph limitation)
   ↓
Agent                            NOT ESTABLISHED as complete integrated system
```

The Router decision subgraph is separate from later lifecycle/write concerns:

```text
Current Event + short local context + candidate Episode context
                       ↓
              Judge A: Boundary
               NEW / CONTINUE
                       ↓ CONTINUE
              Judge B: Ranking
                Which Episode?
```

Related evidence: [current architecture](ARCHITECTURE_CURRENT.md), [status](PROJECT_STATUS.md), [limitations](KNOWN_LIMITATIONS.md).
