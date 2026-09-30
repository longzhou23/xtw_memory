#!/usr/bin/env python3
"""Merge per-batch Cognitive Unit JSON files without changing their contents."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BATCH_DIR = ROOT / "cognitive_units_batches"
OUT = BATCH_DIR / "cognitive_units_database.json"

def main():
    files = sorted(BATCH_DIR.glob("batch_[0-9][0-9].json"))
    if len(files) != 14:
        raise SystemExit(f"expected 14 batch files, found {len(files)}")
    batches = []
    units = []
    per_memory = []
    for expected, path in enumerate(files, 1):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["batch"]["batch"] != f"{expected:02d}":
            raise ValueError(f"unexpected batch label in {path}")
        batches.append(data["batch"])
        units.extend(data["units"])
        per_memory.extend(data["perMemory"])
    database = {
        "version": "0.1.0",
        "schema": "iris-cognitive-unit-store/v0.1",
        "source": "iris_full_backup_2026-09-21.json",
        "rules": "IRIS_Memory_Cognitive_Unit_清洗规范_v0.1.md",
        "rawMemoryCount": sum(b["rawMemoryCount"] for b in batches),
        "derivedCognitiveUnitCount": len(units),
        "batches": batches,
        "units": units,
        "perMemory": per_memory,
        "merge": {
            "orderedBy": "source memory order, then unit order within each source memory",
            "deduplicated": False,
            "crossMemoryEnrichment": False,
            "kgNodesRelationsIncluded": False,
            "sourceBatchFiles": [p.name for p in files],
        },
    }
    OUT.write_text(json.dumps(database, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "rawMemoryCount": database["rawMemoryCount"], "derivedCognitiveUnitCount": len(units)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
