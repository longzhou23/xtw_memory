"""Reply Resolver for linking quoted / replied messages to canonical message IDs."""

import re
from typing import Dict, List, Optional, Tuple
from memory.scripts.data_cleaning.parser import RawParsedMessage


class ReplyResolver:
    """Resolves structured reply references to canonical message IDs."""

    def __init__(self):
        pass

    @staticmethod
    def resolve_replies(
        messages: List[RawParsedMessage],
        id_map: Dict[Tuple[str, int], str],  # (file_id, record_index) -> canonical message_id
        source_id_map: Dict[str, str],       # source_message_id -> canonical message_id
    ) -> Dict[Tuple[str, int], Optional[str]]:
        """Resolves reply links for a list of messages within a conversation.
        
        Returns:
            Dict[(file_id, record_index), resolved_canonical_id]
        """
        # Map: (file_id, record_index) -> resolved target canonical id
        resolved: Dict[Tuple[str, int], Optional[str]] = {}

        # Build minute index for TXT candidate matching: minute_str -> list of (record_index, text, file_id)
        # minute_str format: "MM-DD HH:mm", e.g. "06-07 00:28"
        minute_index: Dict[str, List[Tuple[int, str, str, str]]] = {}
        for m in messages:
            can_id = id_map[(m.file_id, m.record_index)]
            # ISO timestamp: YYYY-MM-DDTHH:mm:ss+08:00 -> MM-DD HH:mm
            if len(m.timestamp_iso) >= 16:
                mm_dd_hh_mm = f"{m.timestamp_iso[5:10]} {m.timestamp_iso[11:16]}"
                minute_index.setdefault(mm_dd_hh_mm, []).append((
                    m.record_index,
                    m.file_id,
                    m.raw_text,
                    can_id,
                ))

        for idx, m in enumerate(messages):
            key = (m.file_id, m.record_index)

            # Case 1: JSON direct platform ID reference
            if m.reply_target_message_id:
                target_can_id = source_id_map.get(m.reply_target_message_id)
                resolved[key] = target_can_id
                continue

            # Case 2: TXT reply info (target_minute, target_uid, target_snippet)
            if m.reply_info:
                target_min = m.reply_info.get("target_minute", "")
                target_snippet = m.reply_info.get("target_snippet", "").strip()
                # Clean snippet if multiline
                first_line_snippet = target_snippet.split("\n")[0].strip()

                candidates = minute_index.get(target_min, [])
                # Candidates must be strictly before current message
                prior_candidates = [c for c in candidates if (c[1] != m.file_id or c[0] < m.record_index)]

                matched_id = None
                if first_line_snippet and first_line_snippet != "原消息":
                    for cand_rec, cand_file, cand_text, cand_id in reversed(prior_candidates):
                        if first_line_snippet in cand_text or cand_text.startswith(first_line_snippet[:15]):
                            matched_id = cand_id
                            break
                elif prior_candidates:
                    # Snippet is '原消息' or empty
                    # If single candidate in that minute, or pick most recent prior candidate
                    matched_id = prior_candidates[-1][3]

                resolved[key] = matched_id
                continue

            resolved[key] = None

        return resolved
