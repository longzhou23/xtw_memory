"""Deterministic Text Normalizer for chat corpus."""

import html
import re
import unicodedata
from typing import Tuple

# Junk control characters to strip (excluding \n, \r, \t, and \u200d inside emojis)
STRIP_CHARS_PATTERN = re.compile(
    r"[\x00\x01-\x08\x0b\x0c\x0e-\x1f\x7f\ufeff\u2060\u2067\u202d\u202c\u2063]"
)

# Zero-width spaces when not part of joiner sequences
ZERO_WIDTH_SPACE_PATTERN = re.compile(r"\u200b+")


def normalize_text(text: str) -> Tuple[str, bool]:
    """Deterministically normalizes chat text.
    
    Returns:
        (normalized_text, repaired_flag)
    """
    if not text:
        return "", False

    repaired = False

    # 1. Normalize line endings (\r\n -> \n, \r -> \n)
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        repaired = True

    # 2. Unescape platform HTML entities if present (&amp;, &lt;, &gt;, &#39;, &quot;)
    if "&" in text:
        unescaped = html.unescape(text)
        if unescaped != text:
            text = unescaped
            repaired = True

    # 3. Strip illegal / junk control characters
    stripped = STRIP_CHARS_PATTERN.sub("", text)
    if stripped != text:
        text = stripped
        repaired = True

    # 4. Strip zero-width spaces
    cleaned_zw = ZERO_WIDTH_SPACE_PATTERN.sub("", text)
    if cleaned_zw != text:
        text = cleaned_zw
        repaired = True

    # 5. Unicode NFC normalization
    nfc_text = unicodedata.normalize("NFC", text)
    if nfc_text != text:
        text = nfc_text
        repaired = True

    return text, repaired
