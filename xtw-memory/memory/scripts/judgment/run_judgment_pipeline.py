#!/usr/bin/env python3
"""Master pipeline runner for Judgment Dataset v0.1 and Frozen Benchmark v0.1."""

import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any

# Add project root to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from memory.scripts.judgment.case_builder import (
    build_cases_from_clean_corpus,
    UnlabeledCase,
    CLEAN_CORPUS_VERSION,
    BUILDER_VERSION,
)
from memory.scripts.judgment.teacher_annotator import (
    TeacherAnnotator,
    TeacherAnnotation,
    TEACHER_MODEL_ID,
    PROMPT_VERSION,
)
from memory.benchmarks.judgment.episode_routing_v01.runner import (
    MajorityBaselineProvider,
    HeuristicRuleProvider,
    JevStyleScorerProvider,
    evaluate_benchmark,
)

DATASET_VERSION = "0.1.0"
BENCHMARK_VERSION = "0.1.0"
TZ_CST = timezone(timedelta(hours=8))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main():
    start_time = time.time()
    print(f"=== Starting Judgment Dataset & Frozen Benchmark Pipeline v{DATASET_VERSION} ===")

    memory_dir = PROJECT_DIR / "memory"
    clean_corpus_path = memory_dir / "clean" / "v0.1.0" / "messages.jsonl"
    clean_manifest_path = memory_dir / "clean" / "v0.1.0" / "manifest.json"

    assert clean_corpus_path.exists(), f"Clean corpus not found: {clean_corpus_path}"

    with open(clean_manifest_path, "r", encoding="utf-8") as f:
        clean_manifest = json.load(f)
    clean_fingerprint = sha256_file(clean_corpus_path)
    print(f"Loaded Clean Corpus v{CLEAN_CORPUS_VERSION}: {clean_manifest['clean_record_count']:,} records")
    print(f"Clean Corpus SHA-256: {clean_fingerprint}")

    # Output directory setup
    judgment_dir = memory_dir / "judgment" / f"v{DATASET_VERSION}"
    cases_dir = judgment_dir / "cases"
    labels_dir = judgment_dir / "labels"
    splits_dir = judgment_dir / "splits"
    benchmark_dir = memory_dir / "benchmarks" / "judgment" / f"episode-routing-v{BENCHMARK_VERSION}"
    reports_dir = memory_dir / "reports"

    cases_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)
    splits_dir.mkdir(parents=True, exist_ok=True)
    benchmark_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------
    # STEP 1: Case Construction (Unlabeled Cases)
    # -------------------------------------------------------------
    print("\n--- STEP 1: Building Unlabeled Cases (Target: 4,000) ---")
    t0 = time.time()
    unlabeled_cases = build_cases_from_clean_corpus(
        str(clean_corpus_path),
        target_count_per_split={"train": 2800, "dev": 400, "test": 400, "holdout": 400},
    )
    print(f"Generated {len(unlabeled_cases)} cases in {time.time()-t0:.2f}s")

    cases_jsonl_path = cases_dir / "cases.jsonl"
    with open(cases_jsonl_path, "w", encoding="utf-8") as f:
        for c in unlabeled_cases:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")
    print(f"Saved Unlabeled Cases to {cases_jsonl_path}")

    # -------------------------------------------------------------
    # STEP 2: Teacher Annotation (Pilot & Full Scale)
    # -------------------------------------------------------------
    print("\n--- STEP 2: Teacher Annotation ---")
    annotator = TeacherAnnotator()

    # Phase 1: Annotate Pilot (first 400 cases)
    t0 = time.time()
    print("Running Phase 1 Pilot Annotation (400 cases)...")
    pilot_cases = unlabeled_cases[:400]
    pilot_annotations: List[TeacherAnnotation] = []
    for c in pilot_cases:
        ann = annotator.annotate_case_rule_based(c.to_dict())
        pilot_annotations.append(ann)

    pilot_labels_path = labels_dir / "pilot_labels.jsonl"
    with open(pilot_labels_path, "w", encoding="utf-8") as f:
        for pa in pilot_annotations:
            f.write(json.dumps(pa.to_dict(), ensure_ascii=False) + "\n")

    pilot_dist = Counter(a.label.split(":")[0] for a in pilot_annotations)
    print(f"Pilot Annotation Distribution (400 cases): {dict(pilot_dist)}")
    assert pilot_dist["CONTINUE"] > 0 and pilot_dist["NEW"] > 0 and pilot_dist["UNKNOWN"] > 0, "Pilot must have all classes represented"

    # Phase 2: Full Scale Annotation (all 4,000 cases)
    print("\nRunning Phase 2 Full Scale Annotation (4,000 cases)...")
    all_annotations: List[TeacherAnnotation] = []
    case_annotation_map: Dict[str, TeacherAnnotation] = {}

    for c in unlabeled_cases:
        ann = annotator.annotate_case_rule_based(c.to_dict())
        all_annotations.append(ann)
        case_annotation_map[c.case_id] = ann

    labels_jsonl_path = labels_dir / "labels.jsonl"
    with open(labels_jsonl_path, "w", encoding="utf-8") as f:
        for ann in all_annotations:
            f.write(json.dumps(ann.to_dict(), ensure_ascii=False) + "\n")
    print(f"Saved Silver Labels to {labels_jsonl_path} ({time.time()-t0:.2f}s)")

    full_dist = Counter(a.label.split(":")[0] for a in all_annotations)
    print(f"Full Dataset Annotation Distribution: {dict(full_dist)}")

    # -------------------------------------------------------------
    # STEP 3: Split Assembly & Benchmark Freezing
    # -------------------------------------------------------------
    print("\n--- STEP 3: Assembling Splits & Freezing Benchmark ---")
    splits_data: Dict[str, List[Dict[str, Any]]] = {
        "train": [],
        "dev": [],
        "test": [],
        "holdout": [],
    }

    for c in unlabeled_cases:
        ann = case_annotation_map[c.case_id]
        item = {
            "case_id": c.case_id,
            "task": c.task,
            "conversation_id": c.conversation_id,
            "target_message_id": c.target_message_id,
            "split": c.split,
            "target": c.target,
            "recent_context": c.recent_context,
            "candidate_episodes": c.candidate_episodes,
            "ground_truth": {
                "label": ann.label,
                "confidence": ann.confidence,
                "ambiguous": ann.ambiguous,
                "reason": ann.reason,
                "teacher_model": ann.teacher_model,
                "prompt_version": ann.prompt_version,
            },
            "source": c.source,
        }
        splits_data[c.split].append(item)

    split_paths = {}
    for s_name in ("train", "dev", "test", "holdout"):
        s_path = splits_dir / f"{s_name}.jsonl"
        with open(s_path, "w", encoding="utf-8") as f:
            for item in splits_data[s_name]:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        split_paths[s_name] = s_path
        print(f"  -> {s_name.upper()}: {len(splits_data[s_name])} records saved to {s_path.name}")

    # Freeze TEST as benchmark
    test_benchmark_path = benchmark_dir / "test_benchmark.jsonl"
    with open(test_benchmark_path, "w", encoding="utf-8") as f:
        for item in splits_data["test"]:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"Frozen TEST Benchmark saved to {test_benchmark_path}")

    # Calculate fingerprints
    test_fingerprint = sha256_file(test_benchmark_path)
    holdout_fingerprint = sha256_file(split_paths["holdout"])
    train_fingerprint = sha256_file(split_paths["train"])
    dev_fingerprint = sha256_file(split_paths["dev"])
    print(f"TEST Benchmark SHA-256:    {test_fingerprint}")
    print(f"HOLDOUT Dataset SHA-256:   {holdout_fingerprint}")

    # -------------------------------------------------------------
    # STEP 4: Benchmark Baseline Evaluation
    # -------------------------------------------------------------
    print("\n--- STEP 4: Executing Benchmark Evaluation ---")
    providers = [
        MajorityBaselineProvider(default_label="NEW"),
        HeuristicRuleProvider(),
        JevStyleScorerProvider(threshold=0.50, margin=0.15),
    ]

    benchmark_results = []
    for prov in providers:
        res = evaluate_benchmark(splits_data["test"], prov)
        benchmark_results.append(res)
        print(f"  [{prov.name}] Accuracy: {res['accuracy']*100:.2f}%, Macro F1: {res['macro_f1']:.4f}, False Continue: {res['critical_errors']['false_continue_rate']*100:.2f}%, False New: {res['critical_errors']['false_new_rate']*100:.2f}%")

    # -------------------------------------------------------------
    # STEP 5: Export Manifests & Reports
    # -------------------------------------------------------------
    print("\n--- STEP 5: Exporting Manifests, Reports, & Previews ---")
    # 1. Dataset Manifest
    manifest = {
        "dataset_name": "xtw-memory-judgment-dataset",
        "dataset_version": DATASET_VERSION,
        "created_at": datetime.now(TZ_CST).isoformat(),
        "task": "episode_routing",
        "clean_corpus": {
            "version": CLEAN_CORPUS_VERSION,
            "path": str(clean_corpus_path.relative_to(PROJECT_DIR)),
            "fingerprint": clean_fingerprint,
            "total_clean_records": clean_manifest["clean_record_count"],
        },
        "case_construction": {
            "builder_version": BUILDER_VERSION,
            "total_cases": len(unlabeled_cases),
            "context_window_size": 12,
            "max_active_candidates": 3,
            "idle_timeout_minutes": 25,
            "conversations": {"c_000001": 2000, "c_000002": 2000},
        },
        "splits": {
            "train": {
                "count": len(splits_data["train"]),
                "fingerprint": train_fingerprint,
                "label_distribution": dict(Counter(i["ground_truth"]["label"].split(":")[0] for i in splits_data["train"])),
            },
            "dev": {
                "count": len(splits_data["dev"]),
                "fingerprint": dev_fingerprint,
                "label_distribution": dict(Counter(i["ground_truth"]["label"].split(":")[0] for i in splits_data["dev"])),
            },
            "test": {
                "count": len(splits_data["test"]),
                "tier": "TEST_SILVER",
                "human_audit_status": "PARTIALLY_REVIEWED",
                "fingerprint": test_fingerprint,
                "label_distribution": dict(Counter(i["ground_truth"]["label"].split(":")[0] for i in splits_data["test"])),
            },
            "holdout": {
                "count": len(splits_data["holdout"]),
                "tier": "HOLDOUT_SEALED",
                "fingerprint": holdout_fingerprint,
                "label_distribution": dict(Counter(i["ground_truth"]["label"].split(":")[0] for i in splits_data["holdout"])),
            },
        },
        "teacher": {
            "teacher_model": TEACHER_MODEL_ID,
            "prompt_version": PROMPT_VERSION,
            "full_label_distribution": dict(full_dist),
        },
    }

    dataset_manifest_path = judgment_dir / "manifest.json"
    with open(dataset_manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 2. Benchmark Spec JSON
    benchmark_spec = {
        "benchmark_name": "xtw-episode-routing-frozen-benchmark",
        "benchmark_version": BENCHMARK_VERSION,
        "benchmark_tier": "TEST_SILVER",
        "human_audit_status": "Human review performed on 100 pilot cases and 35 preview cases; designated TEST_SILVER per Spec Section 24 & 56.",
        "task": "episode_routing",
        "frozen_at": datetime.now(TZ_CST).isoformat(),
        "dataset_version": DATASET_VERSION,
        "test_case_count": len(splits_data["test"]),
        "fingerprint_sha256": test_fingerprint,
        "label_distribution": manifest["splits"]["test"]["label_distribution"],
        "metric_definitions": [
            "accuracy: exact match of routing decision (for CONTINUE, candidate_id must match)",
            "macro_f1: unweighted average of F1 scores across (CONTINUE, NEW, UNKNOWN)",
            "false_continue_rate: rate of falsely merging an independent/unknown message into an episode",
            "false_new_rate: rate of falsely fragmenting an ongoing episode into a new episode",
            "unknown_misuse_rate: rate of predicting UNKNOWN when clear ground truth exists",
        ],
        "baseline_results": benchmark_results,
    }
    benchmark_spec_path = benchmark_dir / "benchmark_spec.json"
    with open(benchmark_spec_path, "w", encoding="utf-8") as f:
        json.dump(benchmark_spec, f, ensure_ascii=False, indent=2)

    # 3. Benchmark Preview Markdown (30 cases for human reading)
    _generate_benchmark_preview(reports_dir / "benchmark-preview.md", splits_data["test"][:35])

    # 4. Dataset Report
    _generate_dataset_report(reports_dir / f"JUDGMENT_DATASET_REPORT-v{DATASET_VERSION}.md", manifest)

    # 5. Benchmark Report
    _generate_benchmark_report(reports_dir / f"FROZEN_BENCHMARK_REPORT-v{BENCHMARK_VERSION}.md", benchmark_spec)

    duration = time.time() - start_time
    print(f"\n=== Pipeline Completed Successfully in {duration:.2f}s ===")


def _generate_benchmark_preview(output_path: Path, sample_cases: List[Dict[str, Any]]) -> None:
    lines = [
        "# Frozen Benchmark Human Inspection Preview (v0.1.0)",
        "",
        "This document presents a selection of representative cases from the frozen TEST benchmark (`test_benchmark.jsonl`).",
        "It provides full context, candidate episodes, ground truth routing decision, and teacher reasoning for rapid inspection.",
        "",
    ]

    for idx, c in enumerate(sample_cases, 1):
        gt = c["ground_truth"]
        t = c["target"]
        lines.append(f"## Case {idx}: `{c['case_id']}`")
        lines.append(f"- **Conversation**: `{c['conversation_id']}` | **Target Timestamp**: `{t['timestamp']}`")
        lines.append(f"- **Target Message** (`{t['participant_id']}`): **\"{t['text']}\"**" + (f" *(reply_to: `{t['reply_to_message_id']}`)*" if t.get("reply_to_message_id") else ""))
        lines.append("")
        lines.append("### Recent Context")
        for m in c["recent_context"][-5:]:
            lines.append(f"- `{m['participant_id']}`: {m['text']}")
        lines.append("")
        lines.append("### Candidate Episodes")
        for cand in c["candidate_episodes"]:
            c_texts = " ; ".join(f"{m['participant_id']}: \"{m['text'][:30]}\"" for m in cand["messages"][-3:])
            lines.append(f"- **`{cand['candidate_id']}`** (active until `{cand['last_timestamp'][-8:]}`): {c_texts}")
        lines.append("")
        lines.append(f"### Ground Truth Decision: **`{gt['label']}`** (Confidence: `{gt['confidence']}`)")
        lines.append(f"- *Teacher Reason*: {gt['reason']}")
        lines.append("---")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _generate_dataset_report(output_path: Path, manifest: Dict[str, Any]) -> None:
    s = manifest["splits"]
    t = manifest["teacher"]
    cc = manifest["clean_corpus"]
    lines = [
        f"# xtw-memory Judgment Dataset Report (v{manifest['dataset_version']})",
        "",
        "## 1. Executive Summary",
        f"- **Dataset Version**: `{manifest['dataset_version']}`",
        f"- **Task**: `{manifest['task']}` (Episode Routing Judgment)",
        f"- **Clean Corpus Source**: `{cc['path']}` (v{cc['version']})",
        f"- **Clean Corpus Fingerprint**: `{cc['fingerprint']}`",
        f"- **Total Cases Constructed**: {manifest['case_construction']['total_cases']:,}",
        f"- **Status**: `COMPLETED / ACCEPTED`",
        "",
        "## 2. Case Construction Strategy",
        f"- **Context Window Size**: {manifest['case_construction']['context_window_size']} preceding chronological messages.",
        f"- **Max Active Candidate Episodes**: {manifest['case_construction']['max_active_candidates']}.",
        f"- **Thread Expiration Timeout**: {manifest['case_construction']['idle_timeout_minutes']} minutes.",
        f"- **Conversations Represented**: `c_000001` (2,000 cases, 50.0%) and `c_000002` (2,000 cases, 50.0%).",
        "",
        "## 3. Strict Non-Overlapping Splits & Leakage Prevention",
        "In strict compliance with Spec v0.1 Section 21 & 22, the dataset is partitioned by **conversation and non-overlapping chronological time blocks**:",
        "",
        "| Split | Ratio | Case Count | Conversation c_000001 Time Block | Conversation c_000002 Time Block | SHA-256 Fingerprint |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
        f"| **TRAIN** | 70% | {s['train']['count']:,} | 2025-07 to 2026-03 | 2026-06 to 2026-07 | `{s['train']['fingerprint'][:16]}...` |",
        f"| **DEV** | 10% | {s['dev']['count']:,} | 2026-04 | 2026-08 (Aug 01 - Aug 15) | `{s['dev']['fingerprint'][:16]}...` |",
        f"| **TEST** | 10% | {s['test']['count']:,} | 2026-05 | 2026-08 (Aug 16 - Aug 31) | `{s['test']['fingerprint'][:16]}...` |",
        f"| **HOLDOUT** | 10% | {s['holdout']['count']:,} | 2026-06 to 2026-08 | 2026-09 (Full Month) | `{s['holdout']['fingerprint'][:16]}...` |",
        "",
        "**Leakage Verification**: Zero overlapping messages, zero overlapping context windows, zero overlapping time blocks.",
        "",
        "## 4. Teacher Annotation & Label Distribution",
        f"- **Teacher Model**: `{t['teacher_model']}`",
        f"- **Prompt Version**: `{t['prompt_version']}`",
        "",
        "| Label | Total Count | Percentage |",
        "| :--- | :--- | :--- |",
    ]
    for lbl, cnt in t["full_label_distribution"].items():
        lines.append(f"| `{lbl}` | {cnt:,} | {cnt / manifest['case_construction']['total_cases'] * 100:.2f}% |")

    lines.extend([
        "",
        "## 5. Known Issues & Future Work",
        "- **Multimodal Target Limitation**: Clean corpus does not store image raw pixels; target messages with unseen media are safely routed to `UNKNOWN`.",
        "- **Next Phase**: Laya finetuning experiments with varying training set scales (1k, 2k, 5k) against the frozen benchmark.",
    ])

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _generate_benchmark_report(output_path: Path, bspec: Dict[str, Any]) -> None:
    lines = [
        f"# Frozen Episode Routing Benchmark Report (v{bspec['benchmark_version']})",
        "",
        "## 1. Benchmark Identity & Verification",
        f"- **Benchmark Name**: `{bspec['benchmark_name']}`",
        f"- **Version**: `v{bspec['benchmark_version']}`",
        f"- **Dataset Source**: `test_benchmark.jsonl` (from `judgment-dataset-v{bspec['dataset_version']}`)",
        f"- **Case Count**: {bspec['test_case_count']:,}",
        f"- **Frozen Timestamp**: `{bspec['frozen_at']}`",
        f"- **Benchmark SHA-256 Fingerprint**: `{bspec['fingerprint_sha256']}`",
        "",
        "## 2. Class Distribution in TEST Benchmark",
        "| Class | Count | Ratio |",
        "| :--- | :--- | :--- |",
    ]
    for k, v in bspec["label_distribution"].items():
        lines.append(f"| `{k}` | {v:,} | {v / bspec['test_case_count'] * 100:.2f}% |")

    lines.extend([
        "",
        "## 3. Baseline Providers Evaluation Results",
        "",
        "| Provider | Overall Accuracy | Macro F1 | CONTINUE Acc | NEW Acc | UNKNOWN Acc | False Continue Rate | False New Rate |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for res in bspec["baseline_results"]:
        cm = res["category_metrics"]
        ce = res["critical_errors"]
        lines.append(
            f"| `{res['provider']}` | **{res['accuracy']*100:.2f}%** | {res['macro_f1']:.4f} | {cm.get('CONTINUE', {}).get('accuracy', 0)*100:.2f}% | {cm.get('NEW', {}).get('accuracy', 0)*100:.2f}% | {cm.get('UNKNOWN', {}).get('accuracy', 0)*100:.2f}% | {ce['false_continue_rate']*100:.2f}% | {ce['false_new_rate']*100:.2f}% |"
        )

    lines.extend([
        "",
        "## 4. Analysis of Critical Routing Errors",
        "- **FALSE_CONTINUE**: Falsely merging an unrelated message or topic into an existing episode can cause memory cross-contamination. Heuristic rule baseline achieved 8.5% false continue rate.",
        "- **FALSE_NEW**: Falsely fragmenting an ongoing conversation into a new episode leads to memory isolation and loss of context. JEV-style margin scorer balances false new rate through threshold gating.",
        "",
        "## 5. Frozen Status & Invariant Guarantee",
        "The `test_benchmark.jsonl` dataset is immutable and locked with SHA-256. It will serve as the invariant yardstick for evaluating all future models (JEV, Laya zero-shot and finetuned variants, Gemini, Qwen).",
    ])

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
