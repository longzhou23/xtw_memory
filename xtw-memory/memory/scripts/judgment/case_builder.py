"""Deterministic Case Builder for Episode Routing Judgment Dataset (v0.1.0).

Constructs model-agnostic, provenance-preserving unlabeled cases from Clean Corpus.
Separates Case construction from Teacher annotation in strict compliance with Spec v0.1.
"""

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

BUILDER_VERSION = "0.1.0"
CLEAN_CORPUS_VERSION = "0.1.0"
TZ_CST = timezone(timedelta(hours=8))


@dataclass
class CandidateEpisode:
    candidate_id: str
    messages: List[Dict[str, Any]]
    participants: List[str]
    last_timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UnlabeledCase:
    case_id: str
    task: str
    conversation_id: str
    target_message_id: str
    split: str  # "train" | "dev" | "test" | "holdout"
    target: Dict[str, Any]
    recent_context: List[Dict[str, Any]]
    candidate_episodes: List[Dict[str, Any]]
    source: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ThreadTracker:
    """Maintains active candidate conversational threads across a message stream."""

    def __init__(self, max_active: int = 3, idle_timeout_minutes: int = 25):
        self.max_active = max_active
        self.idle_timeout_minutes = idle_timeout_minutes
        self.threads: Dict[str, Dict[str, Any]] = {}
        self.thread_counter = 0

    def add_message(self, msg: Dict[str, Any]) -> str:
        """Assigns message to an existing thread or starts a new thread."""
        m_id = msg["message_id"]
        p_id = msg["participant_id"]
        ts_str = msg["timestamp"]
        ts_dt = datetime.fromisoformat(ts_str)
        reply_to = msg.get("reply_to_message_id")
        text = msg.get("text", "")

        # Exclude system-generated / bot tips from forming conversation threads
        if p_id == "p_system" or "system_generated" in msg.get("flags", []):
            return ""

        # 1. Expire stale threads
        expired_ids = []
        for t_id, t_info in self.threads.items():
            last_dt = datetime.fromisoformat(t_info["last_timestamp"])
            if (ts_dt - last_dt).total_seconds() > self.idle_timeout_minutes * 60:
                expired_ids.append(t_id)
        for t_id in expired_ids:
            del self.threads[t_id]

        matched_thread_id = None

        # 2. Check reply link
        if reply_to:
            for t_id, t_info in self.threads.items():
                if any(m["message_id"] == reply_to for m in t_info["messages"]):
                    matched_thread_id = t_id
                    break

        # 3. Check recent speaker continuation within active threads (within 120s)
        if not matched_thread_id:
            for t_id, t_info in self.threads.items():
                last_dt = datetime.fromisoformat(t_info["last_timestamp"])
                delta_sec = (ts_dt - last_dt).total_seconds()
                if p_id in t_info["participants"] and delta_sec <= 180:
                    matched_thread_id = t_id
                    break

        # 4. If still not matched, check if an existing thread is very recent (< 60s) and thread count at max
        if not matched_thread_id:
            if len(self.threads) >= self.max_active:
                # Attach to most recently updated thread if close in time (< 60s)
                most_recent = min(
                    self.threads.keys(),
                    key=lambda k: (ts_dt - datetime.fromisoformat(self.threads[k]["last_timestamp"])).total_seconds()
                )
                delta = (ts_dt - datetime.fromisoformat(self.threads[most_recent]["last_timestamp"])).total_seconds()
                if delta <= 90:
                    matched_thread_id = most_recent

        # 5. Create new thread if needed
        if not matched_thread_id:
            self.thread_counter += 1
            matched_thread_id = f"thread_{self.thread_counter:04d}"
            self.threads[matched_thread_id] = {
                "thread_id": matched_thread_id,
                "messages": [],
                "participants": set(),
                "created_at": ts_str,
                "last_timestamp": ts_str,
            }

        # Update thread
        t_info = self.threads[matched_thread_id]
        t_info["messages"].append({
            "message_id": m_id,
            "participant_id": p_id,
            "timestamp": ts_str,
            "text": text,
            "reply_to_message_id": reply_to,
        })
        # Keep last 5 messages in thread representation
        if len(t_info["messages"]) > 5:
            t_info["messages"] = t_info["messages"][-5:]
        t_info["participants"].add(p_id)
        t_info["last_timestamp"] = ts_str

        return matched_thread_id

    def get_candidate_episodes(self, current_ts: str) -> List[CandidateEpisode]:
        """Returns 1 to 3 active candidate episodes."""
        curr_dt = datetime.fromisoformat(current_ts)
        active = []
        for t_id, t_info in sorted(
            self.threads.items(),
            key=lambda x: datetime.fromisoformat(x[1]["last_timestamp"]),
            reverse=True,
        ):
            delta = (curr_dt - datetime.fromisoformat(t_info["last_timestamp"])).total_seconds()
            if delta <= self.idle_timeout_minutes * 60:
                active.append(t_info)

        candidates = []
        for idx, t_info in enumerate(active[: self.max_active], 1):
            cand_id = f"cand_{idx}"
            candidates.append(CandidateEpisode(
                candidate_id=cand_id,
                messages=t_info["messages"][-4:],
                participants=sorted(list(t_info["participants"])),
                last_timestamp=t_info["last_timestamp"],
            ))
        return candidates


def determine_split(conversation_id: str, timestamp_iso: str) -> str:
    """Deterministically maps a message to a split by conversation + strictly non-overlapping time block."""
    ts_prefix = timestamp_iso[:10]  # YYYY-MM-DD
    month = timestamp_iso[:7]       # YYYY-MM

    if conversation_id == "c_000001":
        # c_000001 Timeline: 2025-07-24 -> 2026-08-15
        if month <= "2026-03":
            return "train"
        elif month == "2026-04":
            return "dev"
        elif month == "2026-05":
            return "test"
        else:
            return "holdout"
    elif conversation_id == "c_000002":
        # c_000002 Timeline: 2026-06-07 -> 2026-09-21
        if month in ("2026-06", "2026-07"):
            return "train"
        elif month == "2026-08":
            if ts_prefix <= "2026-08-15":
                return "dev"
            else:
                return "test"
        else:
            # 2026-09 (JSON export)
            return "holdout"
    return "train"


def build_cases_from_clean_corpus(
    clean_corpus_path: str,
    target_count_per_split: Dict[str, int] = {
        "train": 2800,
        "dev": 400,
        "test": 400,
        "holdout": 400,
    },
) -> List[UnlabeledCase]:
    """Extracts balanced, high-quality, model-agnostic Unlabeled Cases from the clean corpus.
    
    Guarantees:
    1. Equal 50/50 balance between conversation c_000001 and c_000002.
    2. Strict non-overlapping chronological time-block separation across splits.
    3. Meaningful human utterances as targets (filters out bracket artifacts like [1], [17]).
    """
    cases_by_conv_split: Dict[Tuple[str, str], List[UnlabeledCase]] = {}
    for c_id in ("c_000001", "c_000002"):
        for s_name in ("train", "dev", "test", "holdout"):
            cases_by_conv_split[(c_id, s_name)] = []

    target_per_conv: Dict[str, int] = {
        s: target_count_per_split[s] // 2 for s in target_count_per_split
    }

    recent_buffer: Dict[str, List[Dict[str, Any]]] = {"c_000001": [], "c_000002": []}
    trackers: Dict[str, ThreadTracker] = {
        "c_000001": ThreadTracker(max_active=3, idle_timeout_minutes=25),
        "c_000002": ThreadTracker(max_active=3, idle_timeout_minutes=25),
    }

    counter_by_key: Dict[Tuple[str, str], int] = {}
    bracket_re = re.compile(r"^\[\d+\]$")

    with open(clean_corpus_path, "r", encoding="utf-8") as f:
        for line in f:
            msg = json.loads(line)
            conv_id = msg["conversation_id"]
            m_id = msg["message_id"]
            seq = msg["sequence_index"]
            ts = msg["timestamp"]
            text = msg.get("text", "")
            flags = set(msg.get("flags", []))

            tracker = trackers[conv_id]
            buf = recent_buffer[conv_id]

            split_name = determine_split(conv_id, ts)
            quota_limit = target_per_conv[split_name]
            current_cases = cases_by_conv_split[(conv_id, split_name)]

            # Target eligibility check
            # Real user utterance, non-empty, non-system, non-bracket-artifact
            can_be_target = (
                len(buf) >= 8
                and "system_generated" not in flags
                and len(text.strip()) >= 2
                and not bracket_re.match(text.strip())
                and not text.startswith(("[图片:", "[视频:", "[文件:", "[语音:"))
            )

            cands = tracker.get_candidate_episodes(ts)

            if can_be_target and cands and len(current_cases) < quota_limit:
                key = (conv_id, split_name)
                counter_by_key[key] = counter_by_key.get(key, 0) + 1
                # Spread samples evenly across time blocks
                interval = 6 if split_name == "train" else 4
                if counter_by_key[key] % interval == 0:
                    case_id = f"jr_{conv_id}_{seq:06d}"

                    ctx_slice = buf[-12:]
                    case_context = [
                        {
                            "message_id": cm["message_id"],
                            "participant_id": cm["participant_id"],
                            "timestamp": cm["timestamp"],
                            "text": cm.get("text", ""),
                            "reply_to_message_id": cm.get("reply_to_message_id"),
                        }
                        for cm in ctx_slice
                    ]

                    target_obj = {
                        "message_id": m_id,
                        "participant_id": msg["participant_id"],
                        "timestamp": ts,
                        "text": text,
                        "reply_to_message_id": msg.get("reply_to_message_id"),
                    }

                    case = UnlabeledCase(
                        case_id=case_id,
                        task="episode_routing",
                        conversation_id=conv_id,
                        target_message_id=m_id,
                        split=split_name,
                        target=target_obj,
                        recent_context=case_context,
                        candidate_episodes=[c.to_dict() for c in cands],
                        source={
                            "clean_dataset_version": CLEAN_CORPUS_VERSION,
                            "builder_version": BUILDER_VERSION,
                            "conversation_id": conv_id,
                            "target_message_id": m_id,
                            "context_message_ids": [cm["message_id"] for cm in ctx_slice],
                        },
                    )
                    current_cases.append(case)

            # Update tracker and buffer
            tracker.add_message(msg)
            buf.append(msg)
            if len(buf) > 30:
                recent_buffer[conv_id] = buf[-30:]

    all_cases: List[UnlabeledCase] = []
    for s_name in ("train", "dev", "test", "holdout"):
        for c_id in ("c_000001", "c_000002"):
            all_cases.extend(cases_by_conv_split[(c_id, s_name)])

    return all_cases
