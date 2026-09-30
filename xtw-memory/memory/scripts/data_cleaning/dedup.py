"""Conservative Deduplication Module."""

from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Set
from memory.scripts.data_cleaning.parser import RawParsedMessage


@dataclass
class DeduplicationRecord:
    removed_file_id: str
    removed_record_index: int
    retained_file_id: str
    retained_record_index: int
    rule: str
    timestamp: str
    raw_sender: str
    text_snippet: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "removed_file_id": self.removed_file_id,
            "removed_record_index": self.removed_record_index,
            "retained_file_id": self.retained_file_id,
            "retained_record_index": self.retained_record_index,
            "rule": self.rule,
            "timestamp": self.timestamp,
            "raw_sender": self.raw_sender,
            "text_snippet": self.text_snippet[:60],
        }


def deduplicate_messages(
    messages: List[RawParsedMessage],
) -> Tuple[List[RawParsedMessage], List[DeduplicationRecord], Set[Tuple[str, int]]]:
    """Conservatively filters exact consecutive export duplicates.
    
    Returns:
        (retained_messages, deduplication_records, possible_duplicate_keys)
    """
    retained: List[RawParsedMessage] = []
    removed_log: List[DeduplicationRecord] = []
    possible_duplicates: Set[Tuple[str, int]] = set()

    # Track seen (sender, timestamp, text) to detect non-consecutive duplicate candidates
    seen_payloads: Dict[Tuple[str, str, str], Tuple[str, int]] = {}

    for idx, curr in enumerate(messages):
        # Check if consecutive duplicate with previous message in the same file
        if retained and curr.file_id == retained[-1].file_id:
            prev = retained[-1]
            # Exact consecutive match check
            # For JSON: only remove if same source_message_id (which never occurs in this corpus)
            # For TXT: same timestamp, same raw_sender, same text, same attachments
            if curr.source_message_id is not None:
                is_exact_dup = (curr.source_message_id == prev.source_message_id)
            else:
                is_exact_dup = (
                    curr.timestamp_iso == prev.timestamp_iso
                    and curr.raw_sender == prev.raw_sender
                    and curr.raw_text == prev.raw_text
                    and curr.attachments == prev.attachments
                )

            if is_exact_dup:
                removed_log.append(DeduplicationRecord(
                    removed_file_id=curr.file_id,
                    removed_record_index=curr.record_index,
                    retained_file_id=prev.file_id,
                    retained_record_index=prev.record_index,
                    rule="exact_consecutive_export_duplicate",
                    timestamp=curr.timestamp_iso,
                    raw_sender=curr.raw_sender,
                    text_snippet=curr.raw_text,
                ))
                continue

        # Check for non-consecutive possible duplicate
        payload_key = (curr.raw_sender, curr.timestamp_iso, curr.raw_text)
        if payload_key in seen_payloads:
            possible_duplicates.add((curr.file_id, curr.record_index))
            # Also flag the earlier one
            possible_duplicates.add(seen_payloads[payload_key])
        else:
            seen_payloads[payload_key] = (curr.file_id, curr.record_index)

        retained.append(curr)

    return retained, removed_log, possible_duplicates
