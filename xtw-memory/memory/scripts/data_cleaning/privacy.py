"""Privacy Sanitization and Redaction for chat corpus."""

import re
from typing import Tuple
from urllib.parse import urlparse, parse_qsl, urlunparse, urlencode

# Chinese Mobile Phone Numbers (11 digits starting with 13-19)
# Must not be adjacent to letters/digits (to avoid image hashes like AF849F... or MD5)
PHONE_PATTERN = re.compile(r"(?<![0-9a-zA-Z])(?:(?:\+?86)?(1[3-9]\d{9}))(?![0-9a-zA-Z])")

# Email Addresses
EMAIL_PATTERN = re.compile(
    r"(?<![a-zA-Z0-9_.+-])[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.(?:com|cn|edu|net|org|gov|io|me|cc|top|xyz|vip|club|co|info|biz|tv|ltd|group|site|store|fun|icu|link|live|work|tech|online|art|space|wiki|cloud|pub|mobi|asia|pro|wang|ren|kim|bid|red|xin|press|help|app|dev|sh|ac\.cn|edu\.cn|com\.cn|net\.cn|org\.cn)(?![a-zA-Z0-9_.+-])",
    re.IGNORECASE,
)

# 18-digit Chinese National ID Card
ID_CARD_PATTERN = re.compile(
    r"(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"
)

# Explicit physical addresses identified in audit
EXPLICIT_ADDRESSES = [
    re.compile(r"上海市黄浦区淮海中路2-8号兰生大厦32楼"),
    re.compile(r"Michael Yang"),
]

# Sensitive URL query parameter keys
SENSITIVE_PARAM_KEYS = {
    "token",
    "auth",
    "ticket",
    "key",
    "secret",
    "session",
    "sid",
    "signature",
    "sign",
    "code",
    "tk",
    "robot_uin",
    "uin",
    "access_token",
    "refresh_token",
}

# Regex to detect URLs
URL_PATTERN = re.compile(r"https?://[^\s<>\"\'\)]+")

# Explicit account labels
ACCOUNT_LABEL_PATTERN = re.compile(r"(?:qq|QQ|uin|UIN|账号|帐号)[:：\s]*(\d{5,12})")


def sanitize_url(url: str) -> Tuple[str, bool]:
    """Redacts sensitive query parameters from a URL."""
    try:
        parsed = urlparse(url)
        if not parsed.query:
            return url, False
        query_params = parse_qsl(parsed.query, keep_blank_values=True)
        new_params = []
        redacted = False
        for k, v in query_params:
            if k.lower() in SENSITIVE_PARAM_KEYS:
                new_params.append((k, "[REDACTED]"))
                redacted = True
            else:
                new_params.append((k, v))
        if redacted:
            new_query = urlencode(new_params)
            new_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment,
            ))
            return new_url, True
    except Exception:
        pass
    return url, False


def sanitize_text(text: str) -> Tuple[str, bool]:
    """Sanitizes text for privacy leaks.
    
    Returns:
        (sanitized_text, privacy_redacted_flag)
    """
    if not text:
        return "", False

    redacted = False

    # 1. Redact explicit known sensitive address / person snippets
    for addr_re in EXPLICIT_ADDRESSES:
        if addr_re.search(text):
            text = addr_re.sub(lambda m: "[ADDRESS]" if "大厦" in m.group(0) else "[PERSON]", text)
            redacted = True

    # 2. Redact email addresses
    if "@" in text:
        def replace_email(match):
            nonlocal redacted
            redacted = True
            return "[EMAIL]"
        text = EMAIL_PATTERN.sub(replace_email, text)

    # 3. Redact Chinese mobile phone numbers
    # Protect image/media placeholders [图片:...], [视频:...], etc. temporarily
    placeholders = []
    def save_placeholder(m):
        placeholders.append(m.group(0))
        return f"__MEDIA_PLACEHOLDER_{len(placeholders)-1}__"
    
    masked_text = re.sub(r"\[(?:图片|视频|语音|文件):[^\]]+\]", save_placeholder, text)
    
    # Also mask 32-char hex hashes
    hex_hashes = []
    def save_hex(m):
        hex_hashes.append(m.group(0))
        return f"__HEX_HASH_{len(hex_hashes)-1}__"
    masked_text = re.sub(r"[0-9a-fA-F]{32}", save_hex, masked_text)

    def replace_phone(match):
        nonlocal redacted
        redacted = True
        return "[PHONE]"
    masked_text = PHONE_PATTERN.sub(replace_phone, masked_text)

    # 4. Redact ID cards
    def replace_id_card(match):
        nonlocal redacted
        redacted = True
        return "[ID_CARD]"
    masked_text = ID_CARD_PATTERN.sub(replace_id_card, masked_text)

    # 5. Redact explicit account numbers
    def replace_account(match):
        nonlocal redacted
        redacted = True
        full = match.group(0)
        num = match.group(1)
        return full.replace(num, "[ACCOUNT]")
    masked_text = ACCOUNT_LABEL_PATTERN.sub(replace_account, masked_text)

    # 6. Sanitize URLs
    def replace_url(match):
        nonlocal redacted
        u = match.group(0)
        s_u, u_red = sanitize_url(u)
        if u_red:
            redacted = True
            return s_u
        return u
    masked_text = URL_PATTERN.sub(replace_url, masked_text)

    # Restore hex hashes
    for idx, h in enumerate(hex_hashes):
        masked_text = masked_text.replace(f"__HEX_HASH_{idx}__", h)

    # Restore media placeholders
    for idx, ph in enumerate(placeholders):
        masked_text = masked_text.replace(f"__MEDIA_PLACEHOLDER_{idx}__", ph)

    return masked_text, redacted
