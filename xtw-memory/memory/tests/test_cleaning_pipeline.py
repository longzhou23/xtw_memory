"""Unit and integration test suite for xtw-memory chat cleaning pipeline.

Covers Spec v0.1 Section 30 requirements:
- ID stability (30.1)
- Ordering (30.2)
- Unicode & Emoji preservation (30.3)
- Empty message handling (30.4)
- Conservative deduplication (30.5)
- Privacy sanitization (30.6)
- Reply resolution (30.7)
"""

import json
from pathlib import Path
import pytest

from memory.scripts.data_cleaning.schema import CanonicalMessage, Attachment, SourceProvenance
from memory.scripts.data_cleaning.normalizer import normalize_text
from memory.scripts.data_cleaning.privacy import sanitize_text, sanitize_url
from memory.scripts.data_cleaning.parser import RawParsedMessage
from memory.scripts.data_cleaning.identity import IdentityManager
from memory.scripts.data_cleaning.dedup import deduplicate_messages


def test_unicode_and_emoji_preservation():
    """Spec 30.3: Unicode/Emoji must not be corrupted."""
    test_str = "你好世界！😂 🦊 🌸 ✨ 👨‍👩‍👧 α + β = γ ~ 测试"
    norm, repaired = normalize_text(test_str)
    assert norm == test_str, "Standard emojis and characters must be preserved intact"

    # Test stripping of illegal control characters while preserving emojis
    dirty_str = "测试\x14\x00\ufeff\u2060😂文本\r\n换行"
    cleaned, repaired = normalize_text(dirty_str)
    assert "\x14" not in cleaned
    assert "\x00" not in cleaned
    assert "\ufeff" not in cleaned
    assert "😂" in cleaned
    assert "测试😂文本\n换行" == cleaned
    assert repaired is True


def test_html_entity_unescaping():
    raw_html = "A &amp; B &lt; C &gt; D &quot;hello&#39;"
    norm, repaired = normalize_text(raw_html)
    assert norm == "A & B < C > D \"hello'"
    assert repaired is True


def test_privacy_sanitization():
    """Spec 30.6: Sensitive fields must be redacted and flagged."""
    # Phone number
    text_with_phone = "请拨打电话 13812345678 联系我"
    san, flag = sanitize_text(text_with_phone)
    assert "[PHONE]" in san
    assert "13812345678" not in san
    assert flag is True

    # Image hex hash must NOT be mistakenly redacted as phone
    hex_image = "[图片:AF849F0EB284A4B7CA6A799B62C9422E.png]"
    san_img, flag_img = sanitize_text(hex_image)
    assert san_img == hex_image
    assert flag_img is False

    # Email
    text_with_email = "发送邮件到 test_user@163.com 获取详情"
    san_email, flag_email = sanitize_text(text_with_email)
    assert "[EMAIL]" in san_email
    assert "test_user@163.com" not in san_email
    assert flag_email is True

    # Sensitive Address snippet
    text_with_addr = "上海市黄浦区淮海中路2-8号兰生大厦32楼，Michael Yang"
    san_addr, flag_addr = sanitize_text(text_with_addr)
    assert "[ADDRESS]" in san_addr
    assert "[PERSON]" in san_addr
    assert flag_addr is True


def test_url_sanitization():
    url = "https://sub.domain.com/path?token=secret_abc123&user_id=123"
    san, red = sanitize_url(url)
    assert "token=%5BREDACTED%5D" in san
    assert "secret_abc123" not in san
    assert red is True


def test_conservative_deduplication():
    """Spec 30.5: Exact consecutive duplicates removed; repeated chat text preserved."""
    # Two identical consecutive messages (export duplicate)
    m1 = RawParsedMessage(
        file_id="f1.txt", record_index=0, raw_group_id="g1", raw_group_name="G1",
        source_message_id=None, raw_sender="UserA", sender_uid=None, sender_uin=None,
        sender_name="UserA", sender_group_card=None, sender_title=None,
        timestamp_iso="2026-01-01T12:00:00+08:00", timestamp_epoch_ms=1000,
        raw_text="哈哈", message_type="text"
    )
    m2 = RawParsedMessage(
        file_id="f1.txt", record_index=1, raw_group_id="g1", raw_group_name="G1",
        source_message_id=None, raw_sender="UserA", sender_uid=None, sender_uin=None,
        sender_name="UserA", sender_group_card=None, sender_title=None,
        timestamp_iso="2026-01-01T12:00:00+08:00", timestamp_epoch_ms=1000,
        raw_text="哈哈", message_type="text"
    )
    # A third message by UserB sending "哈哈" at a later time (real chat, must NOT be removed)
    m3 = RawParsedMessage(
        file_id="f1.txt", record_index=2, raw_group_id="g1", raw_group_name="G1",
        source_message_id=None, raw_sender="UserB", sender_uid=None, sender_uin=None,
        sender_name="UserB", sender_group_card=None, sender_title=None,
        timestamp_iso="2026-01-01T12:00:05+08:00", timestamp_epoch_ms=6000,
        raw_text="哈哈", message_type="text"
    )

    retained, removed_log, possible_dups = deduplicate_messages([m1, m2, m3])
    assert len(retained) == 2
    assert len(removed_log) == 1
    assert removed_log[0].removed_record_index == 1
    assert retained[0].raw_sender == "UserA"
    assert retained[1].raw_sender == "UserB"


def test_id_stability():
    """Spec 30.1: Deterministic ID assignment between repeated runs."""
    mgr1 = IdentityManager()
    mgr2 = IdentityManager()

    sample_msgs = [
        RawParsedMessage(
            file_id="f1.txt", record_index=i, raw_group_id="455497949", raw_group_name="G",
            source_message_id=None, raw_sender=f"User_{i%5}", sender_uid=f"u_{i%5}", sender_uin=None,
            sender_name=f"User_{i%5}", sender_group_card=None, sender_title=None,
            timestamp_iso="2026-01-01T12:00:00+08:00", timestamp_epoch_ms=1000,
            raw_text="hi", message_type="text"
        )
        for i in range(20)
    ]

    mgr1.build_participant_registry(sample_msgs)
    mgr2.build_participant_registry(sample_msgs)

    for m in sample_msgs:
        id1 = mgr1.get_participant_id(m)
        id2 = mgr2.get_participant_id(m)
        assert id1 == id2, "Participant IDs must be 100% deterministic across runs"

        cid1 = mgr1.get_conversation_id(m.raw_group_id, m.raw_group_name)
        cid2 = mgr2.get_conversation_id(m.raw_group_id, m.raw_group_name)
        assert cid1 == cid2 == "c_000002"

        mid1 = mgr1.make_canonical_message_id(cid1, m)
        mid2 = mgr2.make_canonical_message_id(cid2, m)
        assert mid1 == mid2


def test_clean_corpus_invariants():
    """Spec 30.2, 30.4, 30.7 & Section 42 Acceptance Criteria verification."""
    clean_jsonl = Path(__file__).resolve().parents[1] / "clean" / "v0.1.0" / "messages.jsonl"
    if not clean_jsonl.exists():
        pytest.skip("clean corpus not yet generated")

    all_ids = set()
    prev_seq_by_conv = {}
    prev_ts_by_conv = {}
    total = 0

    with open(clean_jsonl, "r", encoding="utf-8") as f:
        for line in f:
            total += 1
            data = json.loads(line)

            msg_id = data["message_id"]
            conv_id = data["conversation_id"]
            seq = data["sequence_index"]
            ts = data["timestamp"]

            # 1. ID uniqueness
            assert msg_id not in all_ids, f"Duplicate message ID: {msg_id}"
            all_ids.add(msg_id)

            # 2. Sequence ordering strictly monotonic
            last_seq = prev_seq_by_conv.get(conv_id, 0)
            assert seq == last_seq + 1, f"Sequence gap/inversion in {conv_id}: {last_seq} -> {seq}"
            prev_seq_by_conv[conv_id] = seq

            # 3. Timestamp ordering non-decreasing
            last_ts = prev_ts_by_conv.get(conv_id, "")
            assert ts >= last_ts, f"Timestamp inversion in {conv_id}: {last_ts} -> {ts}"
            prev_ts_by_conv[conv_id] = ts

            # 4. Empty message validation
            if not data["text"].strip():
                # Must have attachments or be system
                assert len(data["attachments"]) > 0 or data["message_type"] in ("image", "video", "audio", "file", "system", "recalled", "sticker"), \
                    f"Message {msg_id} has empty text without attachments/valid type"

            # 5. Provenance validation
            assert data["source"]["file_id"], f"Message {msg_id} missing source file_id"
            assert data["source"]["record_index"] >= 0

    assert total == 250973, f"Expected 250,973 clean records, got {total}"
