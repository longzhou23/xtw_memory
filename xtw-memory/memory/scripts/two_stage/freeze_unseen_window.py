#!/usr/bin/env python3
"""Freeze a 400-message consecutive window from unseen community group_1054790154."""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_FILE = PROJECT_ROOT.parent / "private/xiaotianwen-instance/instance/astrobot-data/plugin_data/astrbot_plugin_group_chat_plus/chat_history/aiocqhttp/group/1054790154.json"
OUT_DIR = PROJECT_ROOT / "memory/benchmark-results/router-v0.2-fresh-unseen-community-replay-v0.1"
WINDOW_FILE = OUT_DIR / "replay-window.jsonl"
FINGERPRINT_FILE = OUT_DIR / "replay-fingerprint.json"
MANIFEST_FILE = OUT_DIR / "manifest.json"

TZ_CST = timezone(timedelta(hours=8))


def main():
    # This experiment's input is immutable. Never silently regenerate its
    # fingerprint or overwrite the historical (already consumed) replay data.
    if WINDOW_FILE.exists() or FINGERPRINT_FILE.exists() or MANIFEST_FILE.exists():
        raise SystemExit("Frozen replay artifacts already exist; refusing to overwrite them")
    print(f"Reading raw unseen group chat from {RAW_FILE}...")
    with open(RAW_FILE) as f:
        msgs = json.load(f)

    # Take first 400 consecutive messages (unfiltered, non-cherry-picked)
    WINDOW_SIZE = 400
    assert len(msgs) >= WINDOW_SIZE, f"Expected at least {WINDOW_SIZE} messages, got {len(msgs)}"
    if any(msgs[i]["timestamp"] > msgs[i + 1]["timestamp"] for i in range(WINDOW_SIZE - 1)):
        raise ValueError("Export is not chronological; do not call it a continuous chronological window")

    events = []
    for idx in range(WINDOW_SIZE):
        m = msgs[idx]
        s = m.get("message_str", "")
        match = re.match(r"^\[.*?\]\s*.*?\([^)]*\):\s*(.*)$", s, re.DOTALL)
        text = match.group(1).strip() if match else s.strip()

        ts = m.get("timestamp", 0)
        dt = datetime.fromtimestamp(ts, tz=TZ_CST)
        iso_str = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        sender_id = str(m.get("sender", {}).get("user_id", "unknown"))
        sender_name = m.get("sender", {}).get("nickname", "用户")
        event_id = m.get("message_id") or f"msg_{idx:05d}"

        # Quote resolution
        reply_to = None
        q_match = re.search(r"\[引用\s*>>>\s*(.*?)(?:\(ID:(\d+)\))?:\s*(.*?)\]", text, re.DOTALL)
        if q_match:
            q_sender = q_match.group(1).strip()
            q_id = q_match.group(2)
            q_text = q_match.group(3).strip()

            for prev in reversed(events):
                # A sender-only match can attach the quote to a different
                # message by the same person. Require both sender and text.
                if q_id and prev["senderId"] == q_id and q_text and q_text != "(无法获取引用内容)" and q_text in prev["text"]:
                    reply_to = prev["eventId"]
                    break

        msg_type = "reply" if reply_to else ("image" if "[图片]" in text else "text")

        events.append({
            "rawIndex": idx,
            "eventId": event_id,
            "timestamp": iso_str,
            "senderId": sender_id,
            "senderName": sender_name,
            "text": text,
            "messageType": msg_type,
            "replyTo": reply_to,
            "mentions": [],
        })

    # Write window file
    print(f"Writing {len(events)} events to {WINDOW_FILE}...")
    h = hashlib.sha256()
    with open(WINDOW_FILE, "w", encoding="utf-8") as f:
        for ev in events:
            line = json.dumps(ev, ensure_ascii=False) + "\n"
            f.write(line)
            h.update(line.encode("utf-8"))

    sha256_hash = h.hexdigest()
    print(f"Replay window frozen. SHA-256: {sha256_hash}")

    fingerprint = {
        "dataset_name": "unseen_community_group_1054790154_window_400",
        "community_group_id": "1054790154",
        "assigned_conversation_id": "c_000008",
        "message_count": len(events),
        "first_message": {
            "rawIndex": events[0]["rawIndex"],
            "eventId": events[0]["eventId"],
            "timestamp": events[0]["timestamp"],
            "senderName": events[0]["senderName"],
            "text": events[0]["text"][:60],
        },
        "last_message": {
            "rawIndex": events[-1]["rawIndex"],
            "eventId": events[-1]["eventId"],
            "timestamp": events[-1]["timestamp"],
            "senderName": events[-1]["senderName"],
            "text": events[-1]["text"][:60],
        },
        "time_range": {
            "start": events[0]["timestamp"],
            "end": events[-1]["timestamp"],
        },
        "sha256": sha256_hash,
        "explicit_replies_count": sum(1 for e in events if e["replyTo"]),
        "frozen_before_inference": True,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    with open(FINGERPRINT_FILE, "w", encoding="utf-8") as f:
        json.dump(fingerprint, f, indent=2, ensure_ascii=False)

    manifest = {
        "experiment_id": "router_v0_2_fresh_unseen_community_replay_v0_1",
        "status": "WINDOW_FROZEN_READY_FOR_REPLAY",
        "models": {
            "judge_a_boundary": {
                "checkpoint": "router-v0.2-small-scale-refinement-v0.1/boundary/checkpoint",
                "sha256": "482963c38aa714a710ac97a27cdd1c231f77911f4fbc527eeb3d6c645aa139cd",
                "frozen_threshold": 0.50,
            },
            "judge_b_ranking": {
                "checkpoint": "router-v0.2-small-scale-refinement-v0.1/ranking/checkpoint",
                "sha256": "41a06635613e3969ecf27315b37f68b36e835ad2df39c4e403fade575a4cbb18",
            }
        },
        "unseen_community": {
            "group_id": "1054790154",
            "conversation_id": "c_000008",
            "prior_use": {
                "in_c000001_to_c000007": False,
                "in_boundary_training": False,
                "in_boundary_dev": False,
                "in_ranking_training": False,
                "in_hard_negative_bank": False,
                "in_150_replay": False,
                "in_threshold_calibration": False,
            }
        },
        "window": fingerprint,
    }

    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print("Window manifest and fingerprint saved successfully!")


if __name__ == "__main__":
    main()
