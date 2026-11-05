"""Recognise encrypted music-app downloads so we can refuse them with a plain-language message.

Music apps (QQ Music, NetEase Cloud Music, Kugou, Kuwo, Apple Music) save paid/member downloads
in their own encrypted containers. ffmpeg cannot read them, and the user usually does not know
the file is special: the browser may even hand us a name like "song.mgg2.flac". We only *detect*
these files (by magic bytes, trailing tags and the extensions in the file name) and ask for a
regular audio file. We never decrypt them.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# family -> extensions that only ever mean that app's encrypted format
EXT = {
    "qq": {".mgg", ".mgg0", ".mgg1", ".mgg2", ".mgga", ".mggl", ".mflac", ".mflac0", ".mflac1", ".mflaca",
           ".mmp4", ".qmc0", ".qmc2", ".qmc3", ".qmc4", ".qmc6", ".qmc8", ".qmcflac", ".qmcogg", ".tkm",
           ".bkcmp3", ".bkcm4a", ".bkcflac", ".bkcwav", ".bkcape", ".bkcogg", ".bkcwma"},
    "netease": {".ncm"},
    "kugou": {".kgm", ".kgma", ".kgg", ".vpr"},
    "kuwo": {".kwm"},
    "apple": {".m4p"},
}
# extension prefixes for QQ Music's ever-growing variants (.qmc*, .mgg*, .mflac*, .bkc*)
QQ_PREFIX = (".qmc", ".mgg", ".mflac", ".bkc")
ENCRYPTED_EXT = sorted(set().union(*EXT.values()))

APP = {
    "qq": ("QQ 音乐", "QQ Music"),
    "netease": ("网易云音乐", "NetEase Cloud Music"),
    "kugou": ("酷狗音乐", "Kugou Music"),
    "kuwo": ("酷我音乐", "Kuwo Music"),
    "apple": ("Apple Music", "Apple Music"),
}

_KGM = (bytes.fromhex("7CD532EB86027F4BA8AFA68E0FFF9914"), bytes.fromhex("0528BC96E9E45A4391AABDD07AF53631"))


def _plain_audio(head: bytes) -> bool:
    """True when the first bytes are a container ffmpeg reads (so the file is not encrypted)."""
    return (head.startswith((b"ID3", b"fLaC", b"OggS", b"caff", b"\x1aE\xdf\xa3", b"#!AMR", b"MAC "))
            or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0)  # MPEG/AAC ADTS frame sync
            or (head[:4] in (b"RIFF", b"RF64") and head[8:12] == b"WAVE")
            or (head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"))
            or head[4:8] == b"ftyp")


def family_from_name(name: str) -> Optional[str]:
    """Look at every extension in the name ("a.mgg2.flac" -> .mgg2, .flac)."""
    parts = os.path.basename(name or "").lower().split(".")[1:]
    for p in ("." + x.strip() for x in parts):
        for fam, exts in EXT.items():
            if p in exts:
                return fam
        if p.startswith(QQ_PREFIX):
            return "qq"
    return None


def sniff(path: Path, name: str = "") -> Optional[str]:
    """Return the app family ("qq", "netease", "kugou", "kuwo", "apple") of an encrypted file, else None."""
    path = Path(path)
    size = path.stat().st_size
    with open(path, "rb") as f:
        head = f.read(1 << 16)
        f.seek(max(0, size - (1 << 16)))
        tail = f.read()
    if head.startswith(b"CTENFDAM"):
        return "netease"
    if head.startswith(_KGM):
        return "kugou"
    if head.startswith(b"yeelion-kuwo"):
        return "kuwo"
    if head[4:8] == b"ftyp":
        # FairPlay: brand M4P/M4B with protection, or a protected sample entry ("drms"/"drmi"/"sinf")
        if head[8:12] == b"M4P " or b"drms" in head or b"drmi" in head or b"drms" in tail:
            return "apple"
    if tail.endswith((b"STag", b"QTag", b"musicex\x00")):
        return "qq"
    if _plain_audio(head):
        return None  # a real file that merely kept an old name (e.g. converted "x.mgg2.flac")
    return family_from_name(name)


def message(family: Optional[str], lang: Optional[str]) -> str:
    zh_app, en_app = APP.get(family or "", ("音乐 App", "a music app"))
    if (lang or "").startswith("zh"):
        return ("这是%s的加密文件，不能直接用。请换成 mp3、m4a、flac 等普通音频"
                "（比如从别处导出，或用会员下载的普通格式）。" % zh_app)
    return ("This is an encrypted %s download, so it can't be used directly. Please upload a regular "
            "audio file such as mp3, m4a or flac (for example exported from elsewhere, or downloaded in a "
            "standard format)." % en_app)


def unreadable(lang: Optional[str]) -> str:
    """Fallback when ffmpeg cannot read the upload at all."""
    if (lang or "").startswith("zh"):
        return ("读不出这个文件里的音频。可能是文件损坏、被加密（比如音乐 App 的专用下载格式），"
                "或者它不是音频文件。请换一个 mp3、m4a、flac 或 wav 文件再试。")
    return ("Couldn't read any audio from this file. It may be damaged, encrypted (for example a music app's "
            "protected download), or not an audio file at all. Please try a regular mp3, m4a, flac or wav file.")
