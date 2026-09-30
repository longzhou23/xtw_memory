#!/usr/bin/env python3
"""Explicit format adapter: CognitiveUnitStore -> DemoDataset.

This is a schema adapter only. It does not infer associations or edges.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "cognitive_units_batches" / "cognitive_units_database.json"
OUTPUT = ROOT / "cognitive_units_batches" / "cognitive_units_demo_dataset.json"

def main():
    store = json.loads(SOURCE.read_text(encoding="utf-8"))
    if store.get("version") != "0.1.0" or store.get("schema") != "iris-cognitive-unit-store/v0.1":
        raise ValueError("source is not CognitiveUnitStore v0.1")
    units = store.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("source contains no Cognitive Units")
    nodes = [{
        "id": unit["id"],
        "type": unit["type"],
        "label": unit["text"],
        "sourceMemoryIds": unit.get("provenance", {}).get("sourceMemoryIds", []),
        "metadata": {"cognitiveUnit": True, "cleaning": unit.get("cleaning", {}), "provenance": unit.get("provenance", {})},
    } for unit in units]
    first = nodes[0]["id"]
    dataset = {
        "version": "0.1.0",
        "schema": "iris-demo-dataset/v0.1",
        "datasetName": "IRIS Cognitive Units format adapter (no associations)",
        "sourceSchema": store["schema"],
        "adapter": {"name": "cognitive_units_to_demo_dataset", "associationGeneration": "none", "note": "Format adaptation only; edges intentionally empty."},
        "nodes": nodes,
        "edges": [],
        "cases": [{
            "id": "CU_FIRST_UNIT",
            "title": "First Cognitive Unit",
            "description": "Minimal loader case for schema validation; no associative edges were inferred.",
            "context": units[0]["text"],
            "initialAttention": {first: 1},
            "expectedEmergence": [first],
            "distractors": [],
            "tags": ["format_adapter", "no_associations"],
        }],
    }
    OUTPUT.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "version": dataset["version"], "nodes": len(nodes), "edges": 0, "cases": 1}, ensure_ascii=False))

if __name__ == "__main__": main()
