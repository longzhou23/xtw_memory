# Canonical Message Schema (v0.1.0)

## Overview

The Canonical Message Schema defines a model-agnostic, deterministic, provenance-preserving representation for chat messages across diverse raw export formats (QQChatExporter JSON, QQChatExporter TXT, etc.).

All clean corpus records conform to this schema as JSON Lines (`.jsonl`), where each line is an independent JSON object.

---

## Schema Definition

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "CanonicalMessage",
  "type": "object",
  "required": [
    "message_id",
    "source_message_id",
    "conversation_id",
    "participant_id",
    "timestamp",
    "sequence_index",
    "message_type",
    "text",
    "reply_to_message_id",
    "attachments",
    "source",
    "flags"
  ],
  "properties": {
    "message_id": {
      "type": "string",
      "description": "Globally unique, deterministic identifier for this message in the clean corpus."
    },
    "source_message_id": {
      "type": ["string", "null"],
      "description": "Original platform message identifier if available (e.g. from JSON export), or null if the raw format lacks platform IDs."
    },
    "conversation_id": {
      "type": "string",
      "description": "Stable anonymous conversation identifier (e.g. 'c_000001', 'c_000002')."
    },
    "participant_id": {
      "type": "string",
      "description": "Stable anonymous participant identifier (e.g. 'p_000001', 'p_system')."
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 formatted timestamp with explicit timezone offset (e.g. '2026-09-14T00:04:00+08:00')."
    },
    "sequence_index": {
      "type": "integer",
      "minimum": 1,
      "description": "1-based strictly monotonic order within the conversation."
    },
    "message_type": {
      "type": "string",
      "enum": [
        "text",
        "image",
        "sticker",
        "audio",
        "video",
        "file",
        "system",
        "recalled",
        "forward",
        "other"
      ],
      "description": "Canonical classification of message content."
    },
    "text": {
      "type": "string",
      "description": "Normalized message text content. Strictly preserves colloquial expressions, typos, emojis, and slang."
    },
    "reply_to_message_id": {
      "type": ["string", "null"],
      "description": "Stable message_id of the quoted / referenced target message, or null if not a reply or unresolvable."
    },
    "attachments": {
      "type": "array",
      "description": "List of attachment metadata entries.",
      "items": {
        "type": "object",
        "required": ["type"],
        "properties": {
          "type": { "type": "string" },
          "filename": { "type": ["string", "null"] },
          "mime_type": { "type": ["string", "null"] },
          "size": { "type": ["integer", "null"] },
          "width": { "type": ["integer", "null"] },
          "height": { "type": ["integer", "null"] }
        }
      }
    },
    "source": {
      "type": "object",
      "required": ["file_id", "record_index"],
      "properties": {
        "file_id": {
          "type": "string",
          "description": "Identifier or filename of the raw input file."
        },
        "record_index": {
          "type": "integer",
          "minimum": 0,
          "description": "0-based position of the raw record within the input file."
        }
      }
    },
    "flags": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Quality, anomaly, and provenance audit flags."
    }
  }
}
```

---

## Allowed Quality Flags

- `privacy_redaction`: Sensitive information (phone number, email, physical address, sensitive URL token, etc.) was detected and redacted in text.
- `unresolved_reply`: Message explicitly quotes or replies to another message, but the referenced target could not be conclusively resolved in the current corpus.
- `very_long_message`: Message text length exceeds 500 characters (> 99.7th percentile).
- `empty_text_with_attachment`: Message contains no user-authored text, but includes one or more attachments.
- `system_generated`: Message represents an automated system notification (reaction tip, join/leave, poky tip).
- `possible_duplicate`: Non-consecutive record sharing exact timestamp, sender, and payload with another message.
- `encoding_repaired`: Raw characters had illegal control characters stripped or HTML entities unescaped.
- `missing_timestamp`: Timestamp could not be determined from source (retained as anomaly).
- `timestamp_timezone_unknown`: Source timestamp lacked explicit timezone and default was inferred.
- `missing_sender`: Sender identity could not be parsed from source.
- `malformed_record`: Raw syntax was partially abnormal but recovered.
- `unsupported_message_type`: Payload contains unknown platform message element.

---

## Provenance Invariant

For every record in Clean Corpus:
```text
record.source.file_id ∈ RawFiles
record.source.record_index < len(RawFile[record.source.file_id])
```
Any consumer can directly map any canonical record back to the exact byte position and block in the raw export.
