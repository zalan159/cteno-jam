"""Lyric text helpers (no heavy dependencies)."""
from __future__ import annotations

import unicodedata
from typing import List


def is_cjk(ch: str) -> bool:
    o = ord(ch)
    return 0x2E80 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0x3040 <= o <= 0x30FF or 0xAC00 <= o <= 0xD7AF


def units(text: str) -> List[str]:
    """Split a lyric line into highlight units; Latin words keep their trailing space."""
    out: List[str] = []
    buf = ""
    for ch in text:
        if is_cjk(ch):
            if buf:
                out.append(buf); buf = ""
            out.append(ch)
        elif ch.isspace():
            if buf:
                out.append(buf + " "); buf = ""
        else:
            # CJK punctuation attaches to the previous unit
            if unicodedata.category(ch).startswith("P") and not buf and out:
                out[-1] += ch
            else:
                buf += ch
    if buf:
        out.append(buf)
    return [u for u in out if u.strip()]


