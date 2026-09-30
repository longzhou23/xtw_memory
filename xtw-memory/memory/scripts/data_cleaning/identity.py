"""Stable Anonymous Identity and Key Mapper."""

import re
from typing import Dict, List, Tuple, Any, Optional
from memory.scripts.data_cleaning.parser import RawParsedMessage


def clean_sender_name(raw_sender: str) -> str:
    """Strips leading group title brackets if present."""
    s = raw_sender.strip()
    if s == "0":
        return "系统"
    m = re.match(r"^\[(.*?)\]\s*(.*)$", s)
    if m:
        name = m.group(2).strip()
        if name:
            return name
        return m.group(1).strip()
    return s


class IdentityManager:
    """Manages deterministic anonymous mapping for participants, conversations, and messages."""

    def __init__(self):
        # Known conversation ID mapping (ordered by raw group ID)
        self.conv_map: Dict[str, str] = {
            "196394153": "c_000001",
            "455497949": "c_000002",
        }
        self.conv_metadata: Dict[str, Dict[str, Any]] = {}
        self.participant_map: Dict[str, str] = {}
        self.participant_records: Dict[str, Dict[str, Any]] = {}

    def get_conversation_id(self, raw_group_id: str, raw_group_name: str) -> str:
        if raw_group_id not in self.conv_map:
            # Deterministic fallback
            new_id = f"c_{len(self.conv_map)+1:06d}"
            self.conv_map[raw_group_id] = new_id
        c_id = self.conv_map[raw_group_id]
        if c_id not in self.conv_metadata:
            self.conv_metadata[c_id] = {
                "conversation_id": c_id,
                "raw_group_id": raw_group_id,
                "raw_group_name": raw_group_name,
            }
        return c_id

    def build_participant_registry(self, all_messages: List[RawParsedMessage]) -> None:
        """Collects all participant identities across all messages and assigns deterministic IDs."""
        # 1. First collect all JSON UIDs and their associated names
        json_uid_to_names: Dict[str, set] = {}
        name_to_json_uid: Dict[str, str] = {}

        for m in all_messages:
            if m.sender_uid and m.sender_uid != "未知":
                names = json_uid_to_names.setdefault(m.sender_uid, set())
                for n in (m.sender_name, m.sender_group_card):
                    if n and n.strip():
                        names.add(n.strip())
                        name_to_json_uid[n.strip()] = m.sender_uid

        # 2. Extract canonical identity key for each message
        # Format of key: 'system', 'uid:<uid>', or 'name:<cleaned_name>'
        raw_keys: set = set()
        key_metadata: Dict[str, Dict[str, Any]] = {}

        for m in all_messages:
            if m.is_system or m.raw_sender == "0" or m.sender_uid == "未知":
                continue

            if m.sender_uid and m.sender_uid != "未知":
                k = f"uid:{m.sender_uid}"
            else:
                c_name = clean_sender_name(m.raw_sender)
                # If this name uniquely matches a JSON user in the same group
                if m.raw_group_id == "455497949" and c_name in name_to_json_uid:
                    k = f"uid:{name_to_json_uid[c_name]}"
                else:
                    k = f"name:{m.raw_group_id}:{c_name}"

            raw_keys.add(k)
            meta = key_metadata.setdefault(k, {
                "key": k,
                "raw_senders": set(),
                "uids": set(),
                "uins": set(),
                "group_ids": set(),
            })
            meta["raw_senders"].add(m.raw_sender)
            meta["group_ids"].add(m.raw_group_id)
            if m.sender_uid:
                meta["uids"].add(m.sender_uid)
            if m.sender_uin:
                meta["uins"].add(m.sender_uin)

        # 3. Sort keys lexicographically for 100% deterministic ID assignment
        sorted_keys = sorted(list(raw_keys))
        self.participant_map = {"system": "p_system"}
        self.participant_records = {
            "p_system": {
                "participant_id": "p_system",
                "key": "system",
                "raw_senders": ["0", "系统消息"],
                "uids": [],
                "uins": [],
                "group_ids": ["196394153", "455497949"],
            }
        }

        for idx, k in enumerate(sorted_keys, 1):
            p_id = f"p_{idx:06d}"
            self.participant_map[k] = p_id
            km = key_metadata[k]
            self.participant_records[p_id] = {
                "participant_id": p_id,
                "key": k,
                "raw_senders": sorted(list(km["raw_senders"])),
                "uids": sorted(list(km["uids"])),
                "uins": sorted(list(km["uins"])),
                "group_ids": sorted(list(km["group_ids"])),
            }

    def get_participant_id(self, m: RawParsedMessage) -> str:
        if m.is_system or m.raw_sender == "0" or m.sender_uid == "未知":
            return "p_system"

        if m.sender_uid and m.sender_uid != "未知":
            k = f"uid:{m.sender_uid}"
        else:
            c_name = clean_sender_name(m.raw_sender)
            # Check if name maps to a uid
            cand_key = f"name:{m.raw_group_id}:{c_name}"
            # Find in map
            if cand_key in self.participant_map:
                k = cand_key
            else:
                # Check if it was mapped to a UID key
                found = False
                for existing_k in self.participant_map:
                    if existing_k.startswith("uid:"):
                        rec = self.participant_records.get(self.participant_map[existing_k], {})
                        if m.raw_sender in rec.get("raw_senders", []):
                            k = existing_k
                            found = True
                            break
                if not found:
                    k = cand_key

        return self.participant_map.get(k, "p_unknown")

    def make_canonical_message_id(self, conv_id: str, m: RawParsedMessage) -> str:
        if m.source_message_id:
            return f"m_{conv_id}_j_{m.source_message_id}"
        # Short file tag: group_196394153... -> t196, group_455497949... -> t455
        if "196394153" in m.file_id:
            tag = "t196"
        elif "455497949" in m.file_id:
            tag = "t455"
        else:
            tag = "txt"
        return f"m_{conv_id}_{tag}_{m.record_index:06d}"
