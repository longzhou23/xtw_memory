# Workspace migration record

## Destination layout

`bot/projects/xtw-memory/` is the new workspace root. The former `bot/projects/memory/` project content moved to `xtw-memory/memory/`; the independent `memory-demo` and `xtw-memory-fabric` repositories moved to `components/` with their Git metadata preserved. The small `xiaotianwen_memory_evolution_memo` pointer documents moved under `docs/legacy-pointers/`.

## Excluded local data

Raw chat files, the full IRIS backup, identity mapping and Cognitive Unit source store remain under the legacy `bot/projects/memory/` data area and are not tracked. The old `memory/` path remains as a compatibility boundary with symlinks to moved benchmark/source paths and a note describing the data it retains.

Checkpoint weights, benchmark datasets, raw replay material and generated predictions were physically moved with the project tree, but are ignored from Git. Historical manifests/reports are not rewritten just to change recorded original paths.

## Git status at migration

- Parent `/home/longzhooou/Documents/Programs` repository has unrelated dirty/untracked workspace content. It is not being used for this project commit.
- `memory-demo` commits: `34dd9fa` (path/dependency edits + lockfile), `addbbd7` (ignore local builds/private data), `79a4e39` (source/docs/tests), and `df41c78` (relocated doc entry points). Its remaining benchmark/archive/data outputs and ten tracked artifact deletions remain uncommitted for privacy/provenance review.
- `xtw-memory-fabric` was clean at HEAD `341c146` before relocation; its history is preserved.
- New workspace Git commits: `35ce389` (initialize project root; 125 files: docs/source/tests, excluding local data/artifacts) and `5a868ee` (benchmark artifact index).
- No remote is configured for the new parent project repository.

## Compatibility and follow-up

The `benchmark-results` symlink in `bot/projects/` is retargeted into the new project. `bot/projects/memory/` remains a data/compatibility location, not the canonical code root. Absolute paths inside historical artifacts remain historical provenance; scripts should use workspace-relative paths for any future authorized use.
