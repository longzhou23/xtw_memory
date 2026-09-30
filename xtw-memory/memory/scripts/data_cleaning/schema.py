"""Canonical Message Schema definitions and validators."""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any

VALID_MESSAGE_TYPES = {
    "text",
    "image",
    "sticker",
    "audio",
    "video",
    "file",
    "system",
    "recalled",
    "forward",
    "other",
}

VALID_FLAGS = {
    "privacy_redaction",
    "unresolved_reply",
    "resolved_reply",
    "very_long_message",
    "empty_text_with_attachment",
    "system_generated",
    "possible_duplicate",
    "encoding_repaired",
    "missing_timestamp",
    "timestamp_timezone_unknown",
    "missing_sender",
    "malformed_record",
    "unsupported_message_type",
}


@dataclass
class Attachment:
    type: str
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    size: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None or k in ("type", "filename")}


@dataclass
class SourceProvenance:
    file_id: str
    record_index: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CanonicalMessage:
    message_id: str
    source_message_id: Optional[str]
    conversation_id: str
    participant_id: str
    timestamp: str  # ISO 8601 with timezone, e.g. 2026-09-14T00:04:00+08:00
    sequence_index: int
    message_type: str
    text: str
    reply_to_message_id: Optional[str] = None
    attachments: List[Attachment] = field(default_factory=list)
    source: SourceProvenance = field(default_factory=lambda: SourceProvenance("", 0))
    flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "source_message_id": self.source_message_id,
            "conversation_id": self.conversation_id,
            "participant_id": self.participant_id,
            "timestamp": self.timestamp,
            "sequence_index": self.sequence_index,
            "message_type": self.message_type,
            "text": self.text,
            "reply_to_message_id": self.reply_to_message_id,
            "attachments": [a.to_dict() if isinstance(a, Attachment) else a for a in self.attachments],
            "source": self.source.to_dict() if isinstance(self.source, SourceProvenance) else self.source,
            "flags": sorted(list(set(self.flags))),
        }

    def validate(self) -> List[str]:
        errors = []
        if not self.message_id:
            errors.append("message_id is empty")
        if not self.conversation_id:
            errors.append("conversation_id is empty")
        if not self.participant_id:
            errors.append("participant_id is empty")
        if not self.timestamp:
            errors.append("timestamp is empty")
        elif not ("+" in self.timestamp or self.timestamp.endswith("Z")):
            errors.append("timestamp missing timezone offset")
        if self.sequence_index < 1:
            errors.append("sequence_index must be >= 1")
        if self.message_type not in VALID_MESSAGE_TYPES:
            errors.append(f"invalid message_type: {self.message_type}")
        if self.text is None:
            errors.append("text cannot be None")
        if not isinstance(self.flags, list):
            errors.append("flags must be a list")
        if not self.source or not getattr(self.source, "file_id", None):
            errors.append("source.file_id is missing")
        return errors
