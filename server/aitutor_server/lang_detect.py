"""Language detection over OCR'd text. Trivial Unicode-range heuristic — works because
PSLE essays are exclusively English or Simplified Chinese (no other scripts in scope)."""
from __future__ import annotations

from aitutor_server.api.schemas import Language

_CJK_RANGES = (
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0x3400, 0x4DBF),    # CJK Unified Ideographs Extension A
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
    (0xFF00, 0xFFEF),    # Halfwidth/fullwidth forms (commonly mixed in)
)


def _is_cjk(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def detect_language(text: str) -> Language:
    """Return ``"zh-Hans"`` if ≥10% of letter-ish characters are CJK, else ``"en"``."""
    if not text:
        return "en"
    cjk = sum(1 for ch in text if _is_cjk(ord(ch)))
    letters = sum(1 for ch in text if ch.isalpha() or _is_cjk(ord(ch)))
    if letters == 0:
        return "en"
    return "zh-Hans" if (cjk / letters) >= 0.10 else "en"
