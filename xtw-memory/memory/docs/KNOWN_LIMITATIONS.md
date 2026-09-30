Project: xtw-memory
Module: known limitations
Version: v0.1
Status: CURRENT
Last updated: 2026-09-30
Canonical: YES
Supersedes: none
Superseded by: none

# Known Limitations

- Weak Teacher / weak-silver labels are not semantic gold; label distribution and quality vary by task.
- `TEST_SILVER` and several regression banks have been used repeatedly. Their results are diagnostic/regression evidence, not untouched generalization evidence.
- Some HOLDOUTs are consumed. HNR HOLDOUT is consumed; c_000008 replay is consumed and inconclusive.
- c_000008's corrected report finds non-chronological file order, questionable reply anchoring, invalid auto-filled semantic review, and non-equivalent runtime; previous “fresh PASS”, “0% mixing”, and “31/31 long-gap accuracy” claims are withdrawn.
- Multi-community semantic review covers a limited set of communities/cases; it does not establish broad domain generalization.
- Boundary TRUE_NEW is rare in natural chat; overall accuracy can conceal failure to detect boundaries.
- Ranking fresh evidence is limited; DEV Top-1 and regression are not equivalent to independent semantic holdout performance.
- HNR strict +10pp gate failed; historical PASS/promotion language in body is superseded by correction header/post-validation artifacts.
- Shared Backbone finding applies only to tested P0 formulation and one seed; negative transfer is suspected, not causally established.
- Dual-model 5K root cause is not established. Do not reduce it to “CONTINUE proportion too high.”
- Temporary write provenance cloud probe saw no positive usedMemoryIds; episode-scoped experiment had unnecessary same-Episode links and no real Router replay.
- Diffusion has not demonstrated benefit on a real graph with edges; evaluated Cognitive Unit graph had zero edges.
- Final Consolidation and validated Long-Term Memory end-to-end path remain unfinished/unproven.
- Raw exports include private conversation data. Do not expose, duplicate, or relocate them as part of documentation work.
- Some metadata/hashes/checkpoint mappings remain to reconcile; marked PARTIAL in registries and Inventory.
