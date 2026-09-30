# xtw-memory project workspace

This is the dedicated workspace for the Xiaotian Memory research project.

## Layout

- `memory/` — Router training/evaluation source, project docs and local experiment artifacts.
- `components/memory-demo/` — existing independent Git repository for Recall, Diffusion and memory integration work.
- `components/xtw-memory-fabric/` — existing independent Git repository for Temporary Memory Fabric.
- `docs/` — workspace-level migration notes and repository map.

The two component repositories retain their own `.git` histories and working-tree changes. This repository tracks the `memory/` source/docs and workspace metadata; it intentionally does not absorb the component repositories' histories.

The Memory Demo's annotated `components/memory-demo/src/data/seed_graph.json` contains private IRIS-derived material and is intentionally Git-ignored; `data/raw/` and the Cognitive Unit snapshot are also local-only. A source-only checkout is therefore not expected to build/run without those separately managed local assets.

## Local data boundary

Raw chat exports, private backups, identity mappings and Cognitive Unit source stores remain in the legacy data area under `../memory/` (relative to `bot/projects/`). A compatibility directory there also points to the moved project assets for old scripts. Do not add those private/raw inputs to Git.

Model checkpoints and generated experiment datasets/replays were physically moved with `memory/` but are ignored by this repository. They are local artifacts, not source-controlled project files. See `memory/docs/MODEL_REGISTRY.md` and `DATASET_REGISTRY.md` for paths and evidence caveats.

## Git boundaries

This root Git repository is for the Memory workspace sources and documentation. `components/*` are independent repositories and are excluded from this parent repository. Commit changes inside a component from that component's own repository. There is no remote configured by this initialization.

Before running any experiment, review `memory/docs/PROJECT_STATUS.md` and `PAUSED_QUESTIONS.md`; the 5K Boundary forensic remains **PAUSED**.
