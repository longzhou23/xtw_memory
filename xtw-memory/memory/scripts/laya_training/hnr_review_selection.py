"""Model-blind chronological DEV/HOLDOUT review sampling, precommitted.

Initial quotas 1000 / 1200 are deliberately above the 300 / 400 HIGH minima.
If blind review yields too few HIGH labels, the only allowed extension is the
next consecutive 500 eligible cases in the same frozen window, never cases
chosen because of model performance or semantic outcome.
"""
from __future__ import annotations

import json
from pathlib import Path

import hnr_source_preflight as source
from hnr_blind_packets import REVIEW_DIR, HOLDOUT_DIR, write_once, EXPECTED_WINDOW_MANIFEST_SHA256


def main() -> None:
    assert source.file_sha256(source.OUTPUT / "window-manifest.json") == EXPECTED_WINDOW_MANIFEST_SHA256
    result = {"selection_rule": "first N eligible clean cases chronologically; only next consecutive 500-case extension if required by high-confidence minimum, never baseline-error selection",
              "window_manifest_sha256": EXPECTED_WINDOW_MANIFEST_SHA256,
              "initial_quotas": {"DEV": 1000, "HOLDOUT": 1200},
              "min_high_confidence": {"DEV": 300, "HOLDOUT": 400},
              "extension_size": 500, "windows": {}}
    for window, count, directory in (("DEV", 1000, REVIEW_DIR), ("HOLDOUT", 1200, HOLDOUT_DIR)):
        packet = directory / f"{window.lower()}-blind.jsonl"
        rows = []
        with packet.open() as stream:
            for line in stream:
                if len(rows) == count:
                    break
                rows.append(json.loads(line))
        assert len(rows) == count
        subset = directory / f"{window.lower()}-natural-{count}.jsonl"
        digest = write_once(subset, rows)
        result["windows"][window] = {
            "parent_sha256": source.file_sha256(packet),
            "subset_path": str(subset.relative_to(source.OUTPUT)),
            "subset_sha256": digest,
            "case_count": count,
            "first_case_id": rows[0]["case_id"],
            "last_case_id": rows[-1]["case_id"],
        }
    manifest = REVIEW_DIR / "natural-selection-manifest.json"
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if manifest.exists():
        assert manifest.read_text() == payload
    else:
        manifest.write_text(payload)
    print(json.dumps({"manifest_sha256": source.file_sha256(manifest),
                      "cases": result["initial_quotas"]}, indent=2))


if __name__ == "__main__":
    main()
