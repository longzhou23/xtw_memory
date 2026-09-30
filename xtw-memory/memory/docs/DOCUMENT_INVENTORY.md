Project: xtw-memory
Module: document inventory
Version: v0.1
Status: PARTIAL — file census complete, per-file semantic review incomplete
Last updated: 2026-09-30
Canonical: YES
Supersedes: none
Superseded by: none

# Document Inventory

## Scope and method

Read-only recursive census of `memory/` and `components/memory-demo/`, excluding `node_modules`; only `.md` and `.txt` were counted. Current count after adding the inventory/report pages: **65 files** under `memory/`; **172 files** under `components/memory-demo/`; **237 total**. This is a file census, not a claim that all 237 bodies were read: selected canonical memos, final reports, audit/status docs and project README were content-reviewed; remaining items retain `UNKNOWN / REVIEW NEEDED` until individually checked. No docs were moved or archived during the original documentation pass; the current workspace move is separately recorded in `../docs/WORKSPACE_MIGRATION.md`.

## Inventory field interpretation

`type/title/module/date/status/duplicate?/superseded by?/canonical?` are recorded below for document families where content was checked. For unlisted files, filename/path is not treated as proof of title, date, result, or duplicate status. Current canonical entry points are listed with **YES**; original experiment reports are canonical evidence for their own run, not necessarily current conclusions.

| Path or family (relative to project root) | Type / content confirmed | Related module | Version/date | Status | Duplicate? | Superseded by? | Canonical? |
|---|---|---|---|---|---|---|---|
| `memory/README.md` | project entry | project | docs v0.1 / 2026-09-30 | CURRENT | no known duplicate | — | YES |
| `memory/docs/PROJECT_STATUS.md` | state summary | project | v0.1 / 2026-09-30 | CURRENT | no known duplicate | — | YES |
| `memory/docs/PROJECT_MAP.md` | flow/status map | project | v0.1 / 2026-09-30 | CURRENT | no known duplicate | — | YES |
| `memory/docs/HOW_IT_WORKS.md` | onboarding explainer | architecture | v0.1 / 2026-09-30 | CURRENT | no known duplicate | — | YES |
| `memory/docs/ARCHITECTURE_CURRENT.md` | current Router/mainline | Router | v0.1 / 2026-09-30 | MAINLINE | earlier architecture notes are historical | — | YES |
| `memory/docs/EXPERIMENT_LEDGER.md` | experiment index | experiments | v0.1 / 2026-09-30 | CURRENT | no known duplicate | — | YES |
| `memory/docs/DATASET_REGISTRY.md` | dataset registry | data | v0.1 / 2026-09-30 | PARTIAL | no known duplicate | — | YES (partial) |
| `memory/docs/MODEL_REGISTRY.md` | checkpoint/model registry | models | v0.1 / 2026-09-30 | PARTIAL | no known duplicate | — | YES (partial) |
| `memory/docs/DECISION_LOG.md` | architecture decisions | architecture | v0.1 / 2026-09-30 | CURRENT | no known duplicate | — | YES |
| `memory/docs/KNOWN_LIMITATIONS.md` | limitations | project | v0.1 / 2026-09-30 | CURRENT | no known duplicate | — | YES |
| `memory/docs/PAUSED_QUESTIONS.md` | pause record | Router | v0.1 / 2026-09-30 | PAUSED | no known duplicate | — | YES |
| `memory/docs/PARKING_LOT.md` / `ROADMAP.md` | deferred/current work | planning | v0.1 / 2026-09-30 | CURRENT | distinct purpose | — | YES |
| `memory/docs/SPEC_INDEX.md` | spec index | specifications | v0.1 / 2026-09-30 | PARTIAL | no known duplicate | — | YES (partial) |
| `memory/docs/history/ROUTER_EVOLUTION.md` | history summary | Router | v0.1 / 2026-09-30 | HISTORICAL SUMMARY | not a replacement for source reports | — | YES |
| `memory/docs/Episode_Router_P0_阶段总结与冻结配置.md` | detailed P0 memo | Router | 2026-09-21 | FROZEN P0 / historical | related memo exists in memory-demo; not proven byte/content duplicate | later v0.2 is mainline | YES for P0 findings |
| `memory/docs/agent_memory_latest_consensus.md` | architecture consensus memo | agent memory | date in body/incomplete here | design consensus, not implementation status | similar memo exists in memory-demo; not proven exact duplicate | not current implementation spec | historical source |
| `memory/benchmark-results/*/FINAL_REPORT.md` | per-run primary reports | Router/training | per-file metadata | SUCCESS/PARTIAL/FAILED varies by report | many filenames recur intentionally across run folders | corrected report/header governs | YES per run |
| `memory/benchmark-results/router-v0.2-fresh-unseen-community-replay-v0.1/FINAL_REPORT.md` | corrected final report | Router | 2026-09-30 | CONSUMED / INCONCLUSIVE | previous claims conflict, report explicitly withdraws them | supersedes earlier PASS claim/C2C | YES current verdict |
| `memory/benchmark-results/laya-episode-routing-hard-negative-ranking-v0.1/FINAL_REPORT.md` + `evaluation/POST_VALIDATION_*` | original report + corrections | HNR | 2026-09-29 | PARTIAL, holdout consumed | not duplicate; correction chain | post-validation status governs | YES jointly |
| `memory/benchmark-results/router-v0.2-dual-model-5k-scaling-v0.1/FINAL_REPORT.md` | final report | Router | 2026-09-30 | FAIL; cause NOT ESTABLISHED | no known duplicate | — | YES |
| `memory/reports/*` | cleaning, audit, benchmark reports | data/judgment | per report | varies; inspect each report | no semantic duplicate adjudication | not reconciled | source reports |
| `components/memory-demo/README.md` | project entry | diffusion/demo | current in component repo | CURRENT for that repo | separate entry point | — | YES for memory-demo, not memory/ |
| `components/memory-demo/archive/recall-p0-2026-09-22/` | frozen Recall P0 package | Recall | 2026-09-22 | ARCHIVED / FROZEN | historical/historical copy overlap exists | stage-specific | YES for archived evidence |
| `components/memory-demo/benchmark-results/{frozen,historical}/**` | benchmark reports and run artifacts | Recall | multiple dates | ARCHIVED / historical | duplicate report candidates exist | individual run lineage unresolved | per-run source |
| `components/memory-demo/benchmark-results/*/FINAL_REPORT.md` | per-experiment reports | write/fabric/router/diffusion | multiple dates | statuses differ | repeated basename is expected; same-content duplicates unverified | per report corrections apply | per run |
| `components/memory-demo/docs/**` | architecture, experiments, memos, freezes | multiple | multiple | CURRENT/FROZEN/HISTORICAL mixed | no global content comparison performed | unresolved | path-specific |
| `components/memory-demo/project-meta/duplicate-report.md` | pre-existing duplicate analysis | project docs | existing | source audit | use as prior audit, not independently revalidated here | — | YES for its stated audit |
| remaining `memory/**/*.md|txt` and `components/memory-demo/**/*.md|txt` | files in census not listed above | unknown until read | unknown | UNKNOWN / REVIEW NEEDED | UNKNOWN | UNKNOWN | no |

## Duplicate resolution

No file was deleted, archived, or moved. Same basename `FINAL_REPORT.md` across separate run directories is expected and not by itself a duplicate. `memory-demo` already has `project-meta/duplicate-report.md` and `memory-file-inventory.md`; those are linked as prior work, but the present pass did not re-run content hashing or adjudicate all candidate pairs. See `DUPLICATE_RESOLUTION.md`.

## Counts, path audit and unresolved work

- `memory/`: 65 Markdown/text docs; `memory-demo/`: 172; total 237.
- Specs found through filename/spec search include `memory/benchmarks/judgment/episode-routing-v0.1.0/benchmark_spec.json`, HNR controlled-ablation plan JSON, and experiment-local specs/manifests. JSON specs are not included in the 234-doc Markdown/text census.
- No inventory of binary/data artifacts, checkpoints, or every JSON manifest is claimed.
- Broken-link audit is limited to Markdown relative links in newly added docs plus manually verified cited paths. Existing external/absolute links and every historical report reference have not been exhaustively checked.
- Dates and report statuses for unreviewed files remain unknown. Do not infer status from filename (`FINAL`, `latest`, `frozen`) alone.
