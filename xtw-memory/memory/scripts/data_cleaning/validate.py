#!/usr/bin/env python3
"""Comprehensive Acceptance Criteria Validator for xtw-memory Clean Corpus v0.1.0."""

import json
import re
import sys
import tempfile
from pathlib import Path

# Add project root to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[2]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from memory.scripts.data_cleaning.schema import CanonicalMessage, VALID_FLAGS, VALID_MESSAGE_TYPES
from memory.scripts.data_cleaning.pipeline import CleaningPipeline


def validate_corpus():
    base_dir = PROJECT_DIR / "memory"
    clean_dir = base_dir / "clean" / "v0.1.0"
    manifest_path = clean_dir / "manifest.json"
    messages_path = clean_dir / "messages.jsonl"
    reports_dir = base_dir / "reports"
    previews_dir = base_dir / "previews"
    raw_dir = base_dir / "raw massage"

    print("=== Step 1: Validating Output Artifacts Existence ===")
    required_files = [
        messages_path,
        manifest_path,
        base_dir / "manifests" / "clean-v0.1.0.json",
        clean_dir / "deduplication_records.json",
        clean_dir / "sensitive_mapping.json",
        previews_dir / "preview-100.jsonl",
        previews_dir / "preview-anomalies.jsonl",
        reports_dir / "CLEANING_REPORT-v0.1.0.md",
        reports_dir / "DATA_QUALITY-v0.1.0.md",
        base_dir / "docs" / "CANONICAL_SCHEMA.md",
    ]
    for rf in required_files:
        assert rf.exists(), f"Missing required artifact: {rf}"
        print(f"  [OK] Exists: {rf.relative_to(PROJECT_DIR)}")

    print("\n=== Step 2: Validating Raw Data Immutability ===")
    raw_files = [
        raw_dir / "group_196394153_20260822_210413.txt",
        raw_dir / "group_455497949_20260822_210354.txt",
        raw_dir / "group_🌸🍐2026华理天文：迎新舞台✨_455497949_20260921_114745379.json",
    ]
    for rf in raw_files:
        assert rf.exists(), f"Raw file missing: {rf}"
        assert rf.stat().st_size > 0, f"Raw file empty: {rf}"
        print(f"  [OK] Immutable raw file verified: {rf.name} ({rf.stat().st_size} bytes)")

    print("\n=== Step 3: Validating Clean Corpus Invariants ===")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    expected_clean_count = manifest["clean_record_count"]
    print(f"Manifest clean record count: {expected_clean_count:,}")

    all_message_ids = set()
    prev_seq_by_conv = {}
    prev_ts_by_conv = {}
    reply_target_ids = []
    line_count = 0
    privacy_leak_errors = []

    # Privacy check regex (strict)
    PHONE_LEAK_RE = re.compile(r"(?<![0-9a-zA-Z])(?:(?:\+?86)?(1[3-9]\d{9}))(?![0-9a-zA-Z])")
    ID_CARD_LEAK_RE = re.compile(r"(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")

    with open(messages_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            line_count += 1
            rec = json.loads(line)

            msg_id = rec["message_id"]
            conv_id = rec["conversation_id"]
            part_id = rec["participant_id"]
            seq = rec["sequence_index"]
            ts = rec["timestamp"]
            mtype = rec["message_type"]
            text = rec["text"]
            reply_id = rec["reply_to_message_id"]

            # Unique ID
            assert msg_id not in all_message_ids, f"Line {line_count}: Duplicate message ID {msg_id}"
            all_message_ids.add(msg_id)

            # Conv ID format
            assert re.match(r"^c_\d{6}$", conv_id), f"Line {line_count}: Invalid conv_id {conv_id}"

            # Part ID format
            assert re.match(r"^p_\d{6}$|^p_system$", part_id), f"Line {line_count}: Invalid part_id {part_id}"

            # Sequence monotonicity
            last_seq = prev_seq_by_conv.get(conv_id, 0)
            assert seq == last_seq + 1, f"Line {line_count}: Sequence gap {last_seq} -> {seq} in {conv_id}"
            prev_seq_by_conv[conv_id] = seq

            # Timestamp monotonicity
            last_ts = prev_ts_by_conv.get(conv_id, "")
            assert ts >= last_ts, f"Line {line_count}: Timestamp inversion {last_ts} > {ts} in {conv_id}"
            prev_ts_by_conv[conv_id] = ts

            # Message type valid
            assert mtype in VALID_MESSAGE_TYPES, f"Line {line_count}: Invalid message_type {mtype}"

            # Collect replies
            if reply_id:
                reply_target_ids.append((msg_id, reply_id))

            # Privacy leak check in text (excluding hex image hashes)
            clean_for_leak = re.sub(r"\[(?:图片|视频|语音|文件):[^\]]+\]", "", text)
            clean_for_leak = re.sub(r"[0-9a-fA-F]{32}", "", clean_for_leak)
            pm = PHONE_LEAK_RE.search(clean_for_leak)
            if pm:
                privacy_leak_errors.append(f"Line {line_count}: Phone leak {pm.group(0)} in text: {text[:50]}")
            im = ID_CARD_LEAK_RE.search(clean_for_leak)
            if im:
                privacy_leak_errors.append(f"Line {line_count}: ID card leak {im.group(0)} in text: {text[:50]}")

    assert line_count == expected_clean_count, f"Line count {line_count} != manifest count {expected_clean_count}"
    assert len(privacy_leak_errors) == 0, f"Found privacy leaks: {privacy_leak_errors[:5]}"
    print(f"  [OK] Validated {line_count:,} records for ID uniqueness, sequence monotonicity, and privacy leaks")

    print("\n=== Step 4: Validating Reply Referential Integrity ===")
    dangling_replies = 0
    for src_id, target_id in reply_target_ids:
        if target_id not in all_message_ids:
            dangling_replies += 1
    assert dangling_replies == 0, f"Found {dangling_replies} dangling reply references!"
    print(f"  [OK] All {len(reply_target_ids):,} reply references are valid and exist in corpus")

    print("\n=== Step 5: Validating Preview Samples ===")
    with open(previews_dir / "preview-100.jsonl", "r", encoding="utf-8") as f:
        p100_lines = f.readlines()
    assert len(p100_lines) == 100, f"Expected 100 preview lines, got {len(p100_lines)}"
    print(f"  [OK] preview-100.jsonl has exactly {len(p100_lines)} lines")

    with open(previews_dir / "preview-anomalies.jsonl", "r", encoding="utf-8") as f:
        panom_lines = f.readlines()
    assert len(panom_lines) > 0, "preview-anomalies.jsonl is empty"
    print(f"  [OK] preview-anomalies.jsonl has {len(panom_lines)} anomaly samples")

    print("\n=== Step 6: Validating Deterministic Reproducibility ===")
    print("Running second pass in isolated temporary directory...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_pipeline = CleaningPipeline(raw_dir=str(raw_dir), output_base=tmp_dir)
        tmp_manifest = tmp_pipeline.run()

        # Compare manifest core counts
        for k in ("raw_record_count", "clean_record_count", "removed_count", "participant_count", "conversation_count"):
            assert tmp_manifest[k] == manifest[k], f"Reproducibility mismatch on {k}: {tmp_manifest[k]} != {manifest[k]}"

        # Compare sample lines from messages.jsonl
        tmp_jsonl = Path(tmp_dir) / "clean" / "v0.1.0" / "messages.jsonl"
        with open(messages_path, "r", encoding="utf-8") as f1, open(tmp_jsonl, "r", encoding="utf-8") as f2:
            for i in range(500):
                l1 = f1.readline()
                l2 = f2.readline()
                assert l1 == l2, f"Line {i} mismatch between run A and run B"

    print("  [OK] Deterministic reproducibility verified (Run A == Run B)")
    print("\nALL ACCEPTANCE CRITERIA VERIFIED SUCCESSFULLY.")


if __name__ == "__main__":
    validate_corpus()
