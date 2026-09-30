# Legacy Memory data/compatibility boundary

Canonical Memory project workspace: [`../xtw-memory/`](../xtw-memory/README.md).

This legacy path remains only for local data and compatibility:

- raw chat exports under `raw massage/`;
- IRIS backup and identity mapping;
- Cognitive Unit source store under `cognitive_units_batches/`;
- symlinks to the moved project's `scripts/`, `docs/`, `benchmark-results/`, and related directories, so older local tools continue to resolve paths.

These data files are intentionally outside the new project Git repository. Do not stage or publish them. Project source and documentation now live in `../xtw-memory/memory/`.
