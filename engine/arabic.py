"""Arabic text normalization used by both the scorer and the mock bot.

Matching raw Arabic strings is brittle: the same word can be written with or
without diacritics, with different alef/yaa/taa-marbuta forms, with tatweel,
or with Arabic-Indic digits. We normalize both sides before comparing.
"""
from __future__ import annotations

import re
import unicodedata

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"
_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ALEF = re.compile(r"[إأآٱ]")
_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Lowercase, strip diacritics/tatweel, unify letter variants and digits."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", str(text))
    t = t.translate(_ARABIC_INDIC)
    t = _DIACRITICS.sub("", t).replace(_TATWEEL, "")
    t = _ALEF.sub("ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    t = t.lower()
    return _WS.sub(" ", t).strip()


def compact_digits(text: str) -> str:
    """Remove separators inside digit runs so 'SA44 2000 0001…' still matches."""
    t = normalize(text).upper()
    t = re.sub(r"(?<=\d)[\s\-‐.](?=\d)", "", t)
    return re.sub(r"(?<=SA)[\s\-](?=\d)", "", t)


def contains(haystack_norm: str, needle: str) -> bool:
    return normalize(needle) in haystack_norm
