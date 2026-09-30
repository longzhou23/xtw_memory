"""Generate model-blind HNR review packets from the frozen clean windows.

No raw export, teacher labels, checkpoint, predictions or Judgment HOLDOUT is
opened. The HNR HOLDOUT packet is stored separately and never passed to the
trainer. This does not create semantic labels.
"""
from __future__ import annotations

from collections import deque
from hashlib import sha256
import json
import os
from pathlib import Path

import hnr_source_preflight as source


EXPECTED_WINDOW_MANIFEST_SHA256 = "079f23eafa43059533a03d6156868888670572aec9c17640fe76820cf2c1fa37"
REVIEW_DIR = source.OUTPUT / "dataset/semantic-hard-negative-silver-v0.1/review-input"
HOLDOUT_DIR = source.OUTPUT / "sealed-fresh-holdout/review-input"


def previous_ids() -> set[str]:
    result: set[str] = set()
    with source.WEAK.open() as stream:
        for line in stream:
            case = json.loads(line)
            result.add(case["target_message_id"])
            result.update(case.get("source", {}).get("context_message_ids", []))
            for candidate in case.get("candidate_episodes", []):
                result.update(m["message_id"] for m in candidate.get("messages", []))
    for split in ("dev", "test"):
        with (source.JUDGMENT / f"{split}.jsonl").open() as stream:
            for line in stream:
                case = json.loads(line)
                result.add(case["target_message_id"])
                result.update(case.get("source", {}).get("context_message_ids", []))
                for candidate in case.get("candidate_episodes", []):
                    result.update(m["message_id"] for m in candidate.get("messages", []))
    return result


def window_of(message: dict) -> str | None:
    if message["conversation_id"] != "c_000001":
        return None
    month = message["timestamp"][:7]
    if "2026-01" <= month <= "2026-03":
        return "TRAIN"
    if month == "2026-04":
        return "DEV"
    if month == "2026-05":
        return "HOLDOUT"
    return None


def stripped(message: dict) -> dict:
    return {key: message.get(key) for key in (
        "message_id", "sequence_index", "participant_id", "timestamp", "text", "reply_to_message_id"
    )}


def make_packets() -> dict[str, list[dict]]:
    manifest_path = source.OUTPUT / "window-manifest.json"
    assert source.file_sha256(manifest_path) == EXPECTED_WINDOW_MANIFEST_SHA256, "Source window changed"
    manifest = json.loads(manifest_path.read_text())
    assert source.file_sha256(source.DATA) == manifest["source"]["sha256"]
    used = previous_ids()
    histories: deque[dict] = deque(maxlen=32)
    by_id: dict[str, dict] = {}
    packets: dict[str, list[dict]] = {key: [] for key in ("TRAIN", "DEV", "HOLDOUT")}
    ids: dict[str, list[str]] = {key: [] for key in packets}
    eligible: dict[str, list[str]] = {key: [] for key in packets}
    with source.DATA.open() as stream:
        for line in stream:
            message = json.loads(line)
            w = window_of(message)
            if message["conversation_id"] != "c_000001":
                continue
            if message["timestamp"][:7] > "2026-05":
                continue
            mid = message["message_id"]
            if w:
                ids[w].append(mid)
            text = message.get("text", "").strip()
            if (w and mid not in used and "system_generated" not in message.get("flags", [])
                    and len(text) >= 2 and not source.BRACKET.match(text)
                    and not text.startswith(source.PREFIXES)):
                eligible[w].append(mid)
                reply = message.get("reply_to_message_id")
                packets[w].append({
                    "case_id": f"hnr_{w.lower()}_{mid}",
                    "target_message_id": mid,
                    "conversation_id": message["conversation_id"],
                    "target": stripped(message),
                    "prior_context": list(histories),
                    "direct_reply_anchor": by_id.get(reply) if reply else None,
                    "review_instruction": "From conversation context alone: TRUE_NEW, TRUE_CONTINUE with semantic-thread description and valid anchor message IDs, or UNCERTAIN. Do not use runtime Episode IDs.",
                })
            # History is chronological and only includes strictly prior events.
            record = stripped(message)
            histories.append(record)
            by_id[mid] = record
    for w in packets:
        frozen = manifest["windows"][w]
        assert len(ids[w]) == frozen["messages"]
        assert source.ids_sha256(ids[w]) == frozen["source_message_id_sha256"]
        assert len(eligible[w]) == frozen["fresh_eligible_message_count_upper_bound"]
        assert source.ids_sha256(eligible[w]) == frozen["fresh_eligible_message_id_sha256"]
    return packets


def write_once(path: Path, rows: list[dict]) -> str:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if path.exists():
        # Immutable packets; verify determinism rather than silently overwrite.
        expected = sha256("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                                  for row in rows).encode()).hexdigest()
        assert source.file_sha256(path) == expected, f"Review packet changed: {path}"
        return expected
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return source.file_sha256(path)


def main() -> None:
    packets = make_packets()
    artifact = {"source_window_manifest_sha256": EXPECTED_WINDOW_MANIFEST_SHA256,
                "labels_present": False, "teacher_predictions_present": False,
                "model_predictions_present": False, "judgment_holdout_read": False, "packets": {}}
    for w, rows in packets.items():
        folder = HOLDOUT_DIR if w == "HOLDOUT" else REVIEW_DIR
        path = folder / (w.lower() + "-blind.jsonl")
        artifact["packets"][w] = {"path": str(path.relative_to(source.OUTPUT)),
                                  "count": len(rows), "sha256": write_once(path, rows)}
    out = REVIEW_DIR / "packet-manifest.json"
    payload = json.dumps(artifact, ensure_ascii=False, indent=2) + "\n"
    if out.exists():
        assert out.read_text() == payload
    else:
        out.write_text(payload)
    print(json.dumps({"packet_manifest": str(out), "sha256": source.file_sha256(out),
                      "case_counts": {w: len(rows) for w, rows in packets.items()}}, indent=2))


if __name__ == "__main__":
    main()
