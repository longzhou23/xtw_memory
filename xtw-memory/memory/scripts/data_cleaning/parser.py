"""Parsers for QQChatExporter raw export formats (TXT and JSON)."""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any, Tuple

TZ_CST = timezone(timedelta(hours=8))  # Asia/Shanghai UTC+8


@dataclass
class RawParsedMessage:
    file_id: str
    record_index: int
    raw_group_id: str
    raw_group_name: str
    source_message_id: Optional[str]
    raw_sender: str
    sender_uid: Optional[str]
    sender_uin: Optional[str]
    sender_name: Optional[str]
    sender_group_card: Optional[str]
    sender_title: Optional[str]
    timestamp_iso: str
    timestamp_epoch_ms: int
    raw_text: str
    message_type: str
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    reply_target_message_id: Optional[str] = None
    reply_info: Optional[Dict[str, Any]] = None
    mentions: List[Dict[str, Any]] = field(default_factory=list)
    is_system: bool = False
    is_recalled: bool = False
    raw_payload: Optional[Dict[str, Any]] = None


class JsonExportParser:
    """Parses QQChatExporter JSON export."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.file_id = file_path.split("/")[-1]

    def parse(self) -> Tuple[Dict[str, Any], List[RawParsedMessage]]:
        with open(self.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        chat_info = data.get("chatInfo", {})
        group_id = str(chat_info.get("peerUid", "455497949"))
        group_name = chat_info.get("name", "")

        metadata = {
            "group_id": group_id,
            "group_name": group_name,
            "total_messages": len(data.get("messages", [])),
            "export_time": data.get("statistics", {}).get("timeRange", {}).get("end", ""),
        }

        messages: List[RawParsedMessage] = []
        for idx, m in enumerate(data.get("messages", [])):
            raw_id = str(m.get("id", ""))
            ts_ms = m.get("timestamp", 0)
            # Parse time string: e.g. 2026-09-13T16:04:00.000Z
            iso_utc = m.get("time", "")
            if iso_utc:
                try:
                    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
                    dt_cst = dt.astimezone(TZ_CST)
                    ts_iso = dt_cst.isoformat()
                except Exception:
                    dt = datetime.fromtimestamp(ts_ms / 1000, tz=TZ_CST)
                    ts_iso = dt.isoformat()
            else:
                dt = datetime.fromtimestamp(ts_ms / 1000, tz=TZ_CST)
                ts_iso = dt.isoformat()

            sender_dict = m.get("sender", {})
            sender_uid = sender_dict.get("uid")
            sender_uin = str(sender_dict.get("uin")) if sender_dict.get("uin") is not None else None
            sender_name = sender_dict.get("name")
            sender_card = sender_dict.get("groupCard")
            sender_title = sender_dict.get("title")
            raw_sender = sender_card or sender_name or sender_uid or "未知"

            content_dict = m.get("content", {})
            raw_text = content_dict.get("text", "") or ""
            elements = content_dict.get("elements", [])
            resources = content_dict.get("resources", [])
            mentions_list = content_dict.get("mentions", [])

            is_system = bool(m.get("system", False))
            is_recalled = bool(m.get("recalled", False))
            raw_type = m.get("type", "text")

            # Extract attachments
            attachments = []
            has_sticker = False
            for el in elements:
                el_type = el.get("type")
                data_obj = el.get("data", {})
                if el_type == "image":
                    sub_type = data_obj.get("subType")
                    if sub_type == "sticker":
                        has_sticker = True
                    attachments.append({
                        "type": "sticker" if sub_type == "sticker" else "image",
                        "filename": data_obj.get("filename"),
                        "mime_type": f"image/{data_obj.get('filename', '').split('.')[-1].lower()}" if data_obj.get("filename") else "image/jpeg",
                        "size": data_obj.get("size"),
                        "width": data_obj.get("width"),
                        "height": data_obj.get("height"),
                    })
                elif el_type == "video":
                    attachments.append({
                        "type": "video",
                        "filename": data_obj.get("filename"),
                        "mime_type": "video/mp4",
                        "size": data_obj.get("size"),
                    })
                elif el_type == "audio":
                    attachments.append({
                        "type": "audio",
                        "filename": data_obj.get("filename"),
                        "mime_type": "audio/amr",
                        "size": data_obj.get("size"),
                    })
                elif el_type == "file":
                    attachments.append({
                        "type": "file",
                        "filename": data_obj.get("filename"),
                        "size": data_obj.get("size"),
                    })

            # Check reply target
            reply_target_id = None
            reply_info = None
            for el in elements:
                if el.get("type") == "reply":
                    r_data = el.get("data", {})
                    ref_id = r_data.get("messageId") or r_data.get("referencedMessageId")
                    if ref_id:
                        reply_target_id = str(ref_id)
                        reply_info = {
                            "target_message_id": str(ref_id),
                            "sender_uin": str(r_data.get("senderUin", "")),
                            "sender_name": r_data.get("senderName", ""),
                            "content": r_data.get("content", ""),
                            "timestamp": r_data.get("timestamp"),
                        }
                    break

            # Canonical message type mapping
            if is_recalled:
                msg_type = "recalled"
            elif is_system or raw_type == "system":
                msg_type = "system"
            elif has_sticker and (not raw_text or raw_text.startswith("[图片:")):
                msg_type = "sticker"
            elif raw_type == "reply":
                # Replies are typically text responses to earlier messages
                msg_type = "text"
            elif raw_type in ("image", "video", "audio", "file"):
                msg_type = raw_type
            elif raw_type == "forward":
                msg_type = "forward"
            elif attachments and (not raw_text or raw_text.startswith(("[图片:", "[视频:", "[语音:", "[文件:"))):
                msg_type = attachments[0]["type"]
            elif raw_type == "text":
                msg_type = "text"
            else:
                msg_type = "other"

            # Mentions
            mentions = []
            for men in mentions_list:
                m_uid = men.get("uid")
                m_name = men.get("name")
                if m_uid or m_name:
                    mentions.append({"uid": m_uid, "name": m_name})

            messages.append(RawParsedMessage(
                file_id=self.file_id,
                record_index=idx,
                raw_group_id=group_id,
                raw_group_name=group_name,
                source_message_id=raw_id,
                raw_sender=raw_sender,
                sender_uid=sender_uid,
                sender_uin=sender_uin,
                sender_name=sender_name,
                sender_group_card=sender_card,
                sender_title=sender_title,
                timestamp_iso=ts_iso,
                timestamp_epoch_ms=ts_ms,
                raw_text=raw_text,
                message_type=msg_type,
                attachments=attachments,
                reply_target_message_id=reply_target_id,
                reply_info=reply_info,
                mentions=mentions,
                is_system=is_system,
                is_recalled=is_recalled,
                raw_payload=None,
            ))

        return metadata, messages


class TxtExportParser:
    """Parses QQChatExporter TXT export format."""

    MSG_PATTERN = re.compile(
        r"(?:^|\n)([^\n]+?):\n时间: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\n内容:(.*?)(?=\n[^\n]+?:\n时间: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\n内容:|\Z)",
        re.DOTALL,
    )
    REPLY_PATTERN = re.compile(r"\n回复:\s*(\d{2}-\d{2} \d{2}:\d{2})\s+([a-zA-Z0-9_-]+)\s+-\s+(.*)", re.DOTALL)
    MENTION_PATTERN = re.compile(r"\n提及:\s*([^\n]+)")
    RESOURCE_PATTERN = re.compile(r"  - ([a-zA-Z0-9_]+):\s*([^\n]+)")

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.file_id = file_path.split("/")[-1]

    def parse(self) -> Tuple[Dict[str, Any], List[RawParsedMessage]]:
        with open(self.file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse header
        header_text = content[:2000]
        group_name_match = re.search(r"聊天名称:\s*([^\n]+)", header_text)
        group_name = group_name_match.group(1).strip() if group_name_match else ""

        # Extract group ID from filename, e.g. group_196394153_... -> 196394153
        id_match = re.search(r"group_(\d+)_", self.file_id)
        group_id = id_match.group(1) if id_match else "unknown_group"

        msg_count_match = re.search(r"消息总数:\s*(\d+)", header_text)
        expected_count = int(msg_count_match.group(1)) if msg_count_match else None

        metadata = {
            "group_id": group_id,
            "group_name": group_name,
            "expected_count": expected_count,
            "file_id": self.file_id,
        }

        messages: List[RawParsedMessage] = []
        matches = list(self.MSG_PATTERN.finditer(content))

        for idx, m in enumerate(matches):
            raw_sender = m.group(1).strip()
            dt_str = m.group(2).strip()
            body = m.group(3)

            # Parse timestamp to ISO 8601 with +08:00
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ_CST)
            ts_iso = dt.isoformat()
            ts_ms = int(dt.timestamp() * 1000)

            # Extract sender title & clean name
            sender_title = None
            clean_name = raw_sender
            title_m = re.match(r"^\[(.*?)\]\s*(.*)$", raw_sender)
            if title_m:
                sender_title = title_m.group(1).strip()
                n = title_m.group(2).strip()
                clean_name = n if n else sender_title

            is_system = (raw_sender == "0")

            # Extract sections: \n资源:, \n提及:, \n回复:
            resources_part = None
            mentions_part = None
            reply_part = None

            # Split body at the first section header
            split_pos = len(body)
            for tag in ("\n资源:", "\n提及:", "\n回复:"):
                pos = body.find(tag)
                if pos != -1 and pos < split_pos:
                    split_pos = pos

            raw_text = body[:split_pos].strip()

            # Resources
            attachments = []
            if "\n资源:" in body:
                res_idx = body.find("\n资源:")
                end_res = len(body)
                for tag in ("\n提及:", "\n回复:"):
                    p = body.find(tag, res_idx)
                    if p != -1 and p < end_res:
                        end_res = p
                res_block = body[res_idx:end_res]
                for rm in self.RESOURCE_PATTERN.finditer(res_block):
                    r_type = rm.group(1).strip()
                    r_file = rm.group(2).strip()
                    mime = None
                    if r_type == "image":
                        ext = r_file.split(".")[-1].lower() if "." in r_file else "jpg"
                        mime = f"image/{ext}"
                    elif r_type == "video":
                        mime = "video/mp4"
                    elif r_type == "audio":
                        mime = "audio/amr"
                    attachments.append({
                        "type": r_type,
                        "filename": r_file,
                        "mime_type": mime,
                    })

            # Mentions
            mentions = []
            if "\n提及:" in body:
                men_m = self.MENTION_PATTERN.search(body)
                if men_m:
                    men_text = men_m.group(1).strip()
                    for item in re.split(r"[,，\s]+", men_text):
                        if item.strip():
                            mentions.append({"name": item.strip()})

            # Reply
            reply_info = None
            if "\n回复:" in body:
                rep_m = self.REPLY_PATTERN.search(body)
                if rep_m:
                    reply_info = {
                        "target_minute": rep_m.group(1).strip(),
                        "target_uid": rep_m.group(2).strip(),
                        "target_snippet": rep_m.group(3).strip(),
                    }

            # Message type
            is_recalled = "撤回了一条消息" in raw_text
            if is_recalled:
                msg_type = "recalled"
            elif is_system:
                msg_type = "system"
            elif attachments and (not raw_text or raw_text.startswith(("[图片:", "[视频:", "[语音:", "[文件:"))):
                msg_type = attachments[0]["type"]
            elif raw_text.startswith("[图片:") and not attachments:
                msg_type = "image"
            elif raw_text.startswith("[视频:") and not attachments:
                msg_type = "video"
            elif raw_text.startswith("[语音:") and not attachments:
                msg_type = "audio"
            elif raw_text.startswith("[文件:") and not attachments:
                msg_type = "file"
            else:
                msg_type = "text"

            messages.append(RawParsedMessage(
                file_id=self.file_id,
                record_index=idx,
                raw_group_id=group_id,
                raw_group_name=group_name,
                source_message_id=None,
                raw_sender=raw_sender,
                sender_uid=None,
                sender_uin=None,
                sender_name=clean_name,
                sender_group_card=clean_name if title_m else None,
                sender_title=sender_title,
                timestamp_iso=ts_iso,
                timestamp_epoch_ms=ts_ms,
                raw_text=raw_text,
                message_type=msg_type,
                attachments=attachments,
                reply_target_message_id=None,
                reply_info=reply_info,
                mentions=mentions,
                is_system=is_system,
                is_recalled=is_recalled,
                raw_payload=None,
            ))

        return metadata, messages
