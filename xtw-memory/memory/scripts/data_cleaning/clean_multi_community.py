#!/usr/bin/env python3
"""Process others_QCE multi-community groups through the cleaning pipeline into an isolated version directory."""

import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Any, Tuple

PROJECT_DIR = Path(__file__).resolve().parents[3]
import sys
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from memory.scripts.data_cleaning.schema import (
    CanonicalMessage,
    Attachment,
    SourceProvenance,
)
from memory.scripts.data_cleaning.parser import (
    JsonExportParser,
    RawParsedMessage,
    TZ_CST,
)
from memory.scripts.data_cleaning.normalizer import normalize_text
from memory.scripts.data_cleaning.privacy import sanitize_text
from memory.scripts.data_cleaning.identity import IdentityManager
from memory.scripts.data_cleaning.dedup import deduplicate_messages
from memory.scripts.data_cleaning.reply_resolver import ReplyResolver

VERSION = "multi_community_v0.1"


class MultiCommunityCleaningPipeline:
    def __init__(self, raw_dir: str, output_base: str):
        self.raw_dir = Path(raw_dir)
        self.output_base = Path(output_base)
        self.clean_dir = self.output_base / "clean" / VERSION
        self.clean_dir.mkdir(parents=True, exist_ok=True)
        self.identity_mgr = IdentityManager()

        # Seed existing conv_map to avoid collision with c_000001 and c_000002
        self.identity_mgr.conv_map = {
            "196394153": "c_000001",
            "455497949": "c_000002",
            "314798398": "c_000003",
            "663176075": "c_000004",
            "681038889": "c_000005",
            "738655813": "c_000006",
            "881322040": "c_000007",
        }

    def run(self) -> Dict[str, Any]:
        start_time = time.time()
        print(f"=== Starting Multi-Community Data Cleaning Pipeline {VERSION} ===")

        raw_files = sorted(list(self.raw_dir.glob("group_*.json")))
        assert len(raw_files) >= 3, f"Expected at least 3 groups, found {len(raw_files)}"

        all_raw_messages: List[RawParsedMessage] = []
        raw_file_stats = []

        for rf in raw_files:
            print(f"Parsing {rf.name} ({rf.stat().st_size / 1024 / 1024:.2f} MB)...")
            t0 = time.time()
            parser = JsonExportParser(str(rf))
            meta, msgs = parser.parse()

            # Override group_id from filename if peerUid was None
            m_gid = re.search(r"group_(\d+)_", rf.name)
            gid = m_gid.group(1) if m_gid else meta["group_id"]
            for m in msgs:
                m.raw_group_id = gid

            duration = round(time.time() - t0, 3)
            raw_file_stats.append({
                "file_id": rf.name,
                "group_id": gid,
                "group_name": meta.get("group_name", ""),
                "record_count": len(msgs),
                "duration_seconds": duration,
            })
            all_raw_messages.extend(msgs)

        print(f"Total raw records parsed across {len(raw_files)} groups: {len(all_raw_messages):,}")

        # Deduplication
        print("Running deduplication...")
        retained_messages, dedup_log, possible_dups = deduplicate_messages(all_raw_messages)
        print(f"  -> Retained {len(retained_messages):,} messages (deduped {len(dedup_log)} duplicates)")

        # Participant Registry
        print("Building participant registry...")
        self.identity_mgr.build_participant_registry(retained_messages)
        print(f"  -> Registered {len(self.identity_mgr.participant_records):,} unique participants")

        # Group by conversation
        by_conv: Dict[str, List[RawParsedMessage]] = {}
        for m in retained_messages:
            conv_id = self.identity_mgr.get_conversation_id(m.raw_group_id, m.raw_group_name)
            by_conv.setdefault(conv_id, []).append(m)

        for c_id in by_conv:
            by_conv[c_id].sort(key=lambda x: (x.timestamp_iso, x.file_id, x.record_index))

        # Assign message IDs & resolve replies
        print("Assigning canonical IDs and resolving replies...")
        id_map: Dict[Tuple[str, int], str] = {}
        source_id_map: Dict[str, str] = {}

        for conv_id, c_msgs in by_conv.items():
            for m in c_msgs:
                can_id = self.identity_mgr.make_canonical_message_id(conv_id, m)
                id_map[(m.file_id, m.record_index)] = can_id
                if m.source_message_id:
                    source_id_map[m.source_message_id] = can_id

        resolved_replies: Dict[Tuple[str, int], Any] = {}
        for conv_id, c_msgs in by_conv.items():
            conv_resolved = ReplyResolver.resolve_replies(c_msgs, id_map, source_id_map)
            resolved_replies.update(conv_resolved)

        # Assemble clean messages
        print("Normalizing, sanitizing, and writing clean messages...")
        clean_messages_path = self.clean_dir / "messages.jsonl"
        clean_count = 0
        group_counts = Counter()

        with open(clean_messages_path, "w", encoding="utf-8") as out_f:
            for conv_id in sorted(by_conv.keys()):
                c_msgs = by_conv[conv_id]
                seq_counter = 1
                for m in c_msgs:
                    m_key = (m.file_id, m.record_index)
                    can_msg_id = id_map[m_key]
                    p_id = self.identity_mgr.get_participant_id(m)

                    norm_text, _ = normalize_text(m.raw_text)
                    clean_text, _ = sanitize_text(norm_text)

                    # Skip empty messages without attachments
                    if not clean_text and not m.attachments and not m.is_system:
                        continue

                    reply_to_id = resolved_replies.get(m_key)

                    attachments_clean = [
                        Attachment(
                            type=att["type"],
                            filename=att.get("filename"),
                            mime_type=att.get("mime_type", "application/octet-stream"),
                            size=att.get("size"),
                            width=att.get("width"),
                            height=att.get("height"),
                        )
                        for att in m.attachments
                    ]

                    provenance = SourceProvenance(
                        file_id=m.file_id,
                        record_index=m.record_index,
                    )

                    can_msg = CanonicalMessage(
                        message_id=can_msg_id,
                        source_message_id=m.source_message_id,
                        conversation_id=conv_id,
                        participant_id=p_id,
                        timestamp=m.timestamp_iso,
                        sequence_index=seq_counter,
                        message_type=m.message_type,
                        text=clean_text,
                        reply_to_message_id=reply_to_id,
                        attachments=attachments_clean,
                        source=provenance,
                        flags=[],
                    )

                    out_f.write(json.dumps(can_msg.to_dict(), ensure_ascii=False) + "\n")
                    seq_counter += 1
                    clean_count += 1
                    group_counts[conv_id] += 1

        duration = round(time.time() - start_time, 2)
        print(f"Cleaning complete in {duration}s. Written {clean_count:,} messages.")

        manifest = {
            "version": VERSION,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "groups_processed": len(raw_files),
            "raw_file_stats": raw_file_stats,
            "clean_message_count": clean_count,
            "group_distribution": dict(group_counts),
            "conversation_map": self.identity_mgr.conv_map,
            "duration_seconds": duration,
        }

        with open(self.clean_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        return manifest


if __name__ == "__main__":
    raw_dir = "/home/longzhooou/Documents/Programs/小天文设计素材/bot/projects/memory/raw massage/others_QCE"
    output_base = "/home/longzhooou/Documents/Programs/小天文设计素材/bot/projects/memory"
    pipeline = MultiCommunityCleaningPipeline(raw_dir, output_base)
    manifest = pipeline.run()
    print("\n--- Multi-Community Cleaning Summary ---")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
