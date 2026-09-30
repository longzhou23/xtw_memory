Project: xtw-memory
Module: dataset registry
Version: v0.1
Status: PARTIAL inventory
Last updated: 2026-09-30
Canonical: YES
Supersedes: none
Superseded by: none

# Dataset Registry

Only values verified in the cited artifacts are asserted. `—` means not verified here, not zero. Fingerprints are recorded only where reports explicitly state them. Split state is intentionally distinguished from quality. Dataset paths below refer to the canonical `memory/` workspace; the clean and judgment corpus directories are present in the current local checkout but are Git-ignored, so a fresh clone will not contain them unless provisioned separately.

| Name | Path / source | size / scope | labels / review | split / status | Fingerprint / notes |
|---|---|---|---|---|---|
| Clean v0.1.0 corpus | `../clean/v0.1.0/` (local-only; Git-ignored) | `messages.jsonl` and manifest present in this checkout; report states 250,973 msgs | normalized/anonymized; source report | source corpus | See `../reports/CLEANING_REPORT-v0.1.0.md`; raw source and identity mapping remain outside the versioned project |
| Multi-community clean v0.1 | `../clean/multi_community_v0.1/` (local-only; Git-ignored) | `messages.jsonl` and manifest present in this checkout; 5 communities; 124,725 source msgs per refinement report | dual-blind consensus sample, not full gold | expansion source | See refinement report; per-community breakdown there |
| Judgment v0.1.0 | `../judgment/v0.1.0/` (local-only; Git-ignored) | manifest, cases, labels and splits present in this checkout | weak/teacher-derived; audits in reports | TEST_SILVER; repeatedly used | See `../reports/JUDGMENT_DATASET_REPORT-v0.1.0.md` and freeze audit; fresh clones need local data provisioning |
| Router Boundary 2.2K baseline | `../benchmark-results/router-v0.2-small-scale-refinement-v0.1/` (datasets/manifests) | 2,210 train cases in report | semantic reviewed mixture; DEV 301 | TRAIN / DEV | Inputs and hashes in experiment manifest |
| Router Ranking 2K baseline | same as above | 2,007 unique cases | semantic + weak + 7 runtime hard negatives | TRAIN / DEV | Not the same population as Boundary |
| HNR sealed HOLDOUT | `../benchmark-results/laya-episode-routing-hard-negative-ranking-v0.1/` | 407 total, 366 rankable | dual-blind HIGH silver | **CONSUMED** | window manifest SHA `079f23eafa43059533a03d6156868888670572aec9c17640fe76820cf2c1fa37`; full split hashes in report |
| HNR weak diagnostic test | `../judgment/v0.1.0/splits/test.jsonl` per report | 400 | weak silver | TEST_SILVER; reused diagnostic | Not fresh/holdout gold |
| Shared-backbone datasets | shared-backbone P0 `manifest.json` | Boundary 2,210; Ranking 2,007 unique / 2,028 effective | inherited labels; not independently blind-adjudicated for this run | existing DEV | No c_000008 used |
| Dual-model Boundary 5K | `../benchmark-results/router-v0.2-dual-model-5k-scaling-v0.1/datasets/boundary-5k/` | 5,010; expanded 2,800 | multi-community dual-blind consensus per report | TRAIN | SHA `3efce5113103eeed3934c9053e2913e000ac51b533407d9ca69f5cdf49d87514`; composition in report |
| Dual-model Ranking 5K | same experiment `datasets/ranking-5k/` | 5,007 | semantic + weak expansion | TRAIN | SHA `1cb626423e42c33ab3db64f806454849c2ef2595a0d9690b196f9ff2022a2b98` |
| c_000008 replay window | `../benchmark-results/router-v0.2-fresh-unseen-community-replay-v0.1/replay-window.jsonl` | 400 records | no valid full semantic gold audit; generated review labels invalid | **FRESH_CONSUMED / INCONCLUSIVE** | SHA `063de8ca5a18891a9b64898a186220945a05e9beb48402d7a2d0b3f56d49375d`; not future fresh holdout |
| Memory-demo frozen Recall benchmark | `../../components/memory-demo/benchmark-results/frozen/` and historical packages | frozen v0.2.0 family | annotations/benchmark audit applies; see source docs | consumed historical evaluation | Do not assume all old reports refer to same run/split |
| Memory-demo judgment benchmark | `../../components/memory-demo/benchmark-results/qwen-system-one-frozen-judgment-benchmark-v0.1-20260929/` | 400 TEST_SILVER | partial human audit, not gold-certified | TEST_SILVER | benchmark SHA `6a35a8fa4984831c0c61be18a3045ba679a8ca73a69aa604b77234e68e5a47d2`; SEALED_UNREAD separately listed there |
| Diffusion Cognitive Unit graph | `../../components/memory-demo/data/cognitive-units/cognitive_units_database.json` | 2,196 nodes | existing nodes; no inferred edges | zero-edge graph | graph SHA `92f5b405b10f00ba82c05f5f8197fc277966853d70499cbcd949d3ece7e34ef8` in report |
| Temporary Fabric real-chat slice | memory-demo raw group export, references in reports | 120-event micro replay; separate 20-event provenance probe | real source text, limited manual review | consumed diagnostic | Never move raw source; refer to original report |

## Required fields not yet reconciled

Across all candidate datasets, exact message/case counts, community/time coverage, human-review status, teacher provenance, split assignments, and fingerprints have not been reconciled into one exhaustive catalog. In particular, do not promote `TEST_SILVER` to gold, `CONSUMED_HOLDOUT` to fresh, or a derived replay window to untouched based on a folder name. See `DOCUMENT_INVENTORY.md` and `KNOWN_LIMITATIONS.md`.
