"""Audio I/O helpers around ffmpeg (decode anything, encode stems)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

ALLOWED_EXT = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".webm", ".mp4", ".caf", ".aiff", ".aif",
               ".amr", ".3gp", ".3ga", ".wma"}   # the last ones: Android voice recorders and older phones
# MIME type -> extension, for files that arrive without one (in-browser recordings, some phone pickers)
MIME_EXT = {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/m4a": ".m4a",
            "audio/aac": ".aac", "audio/x-aac": ".aac", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav",
            "audio/flac": ".flac", "audio/x-flac": ".flac", "audio/ogg": ".ogg", "audio/opus": ".opus", "audio/webm": ".webm",
            "video/webm": ".webm", "video/mp4": ".mp4", "audio/x-caf": ".caf", "audio/aiff": ".aiff", "audio/x-aiff": ".aiff",
            "audio/amr": ".amr", "audio/3gpp": ".3gp", "video/3gpp": ".3gp", "audio/x-ms-wma": ".wma"}


def magic_ext(head: bytes):
    """Extension for a plain audio container recognised from its first bytes, else None."""
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return ".mp3"
    for sig, ext in ((b"fLaC", ".flac"), (b"OggS", ".ogg"), (b"#!AMR", ".amr"), (b"caff", ".caf"), (b"\x1aE\xdf\xa3", ".webm")):
        if head.startswith(sig):
            return ext
    if head[:4] in (b"RIFF", b"RF64") and head[8:12] == b"WAVE":
        return ".wav"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return ".aiff"
    if head[4:8] == b"ftyp":
        return ".3gp" if head[8:11] == b"3gp" else ".m4a"
    return None


class AudioError(RuntimeError):
    pass


def _clean(msg: str, *paths) -> str:
    """ffmpeg names the file it failed on; never show server paths to users."""
    for p in paths:
        msg = msg.replace(str(p) + ": ", "").replace(str(p), "<file>")
    return msg.strip()


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise AudioError("ffmpeg not found on PATH")
    return exe


def probe_duration(path: Path) -> float:
    exe = shutil.which("ffprobe")
    if not exe:
        raise AudioError("ffprobe not found on PATH")
    r = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise AudioError("not a readable audio file (%s)" % _clean((r.stderr.strip().splitlines() or ["ffprobe failed"])[-1], path))
    info = json.loads(r.stdout or "{}")
    if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
        raise AudioError("the file has no audio stream")
    try:
        return float(info["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        pass
    # Browser recordings (MediaRecorder webm, fragmented mp4) are written as a stream and carry no
    # duration in the header: decode once and read how far ffmpeg got.
    d = decoded_duration(path)
    if d is None:
        raise AudioError("could not read the duration of the file")
    return d


def decoded_duration(path: Path):
    r = subprocess.run([ffmpeg(), "-nostdin", "-hide_banner", "-i", str(path), "-vn", "-f", "null", "-"],
                       capture_output=True, text=True)
    times = re.findall(r"time=(\d+):(\d\d):(\d\d(?:\.\d+)?)", r.stderr or "")
    if r.returncode != 0 or not times:
        return None
    h, m, s = times[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


def decode(path: Path, out_wav: Path, sr: int = 44100, channels: int = 2) -> None:
    r = subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(path), "-vn", "-ac", str(channels), "-ar", str(sr),
                        "-c:a", "pcm_s16le", str(out_wav)], capture_output=True, text=True)
    if r.returncode != 0:
        raise AudioError("could not decode audio: %s" % _clean((r.stderr.strip().splitlines() or ["ffmpeg failed"])[-1], path, out_wav))


def encode_mp3_mono(wav: Path, out_mp3: Path, bitrate: str = "96k") -> None:
    """Mono 44.1 kHz MP3: WebKit's decodeAudioData cannot read ffmpeg's AAC/m4a (prototype finding)."""
    r = subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(wav), "-ac", "1", "-ar", "44100", "-c:a", "libmp3lame",
                        "-b:a", bitrate, str(out_mp3)], capture_output=True, text=True)
    if r.returncode != 0:
        raise AudioError("could not encode %s: %s" % (out_mp3.name, _clean(r.stderr.strip()[-300:], wav, out_mp3)))


def load_mono(path: Path, sr: int = 22050) -> np.ndarray:
    """Decode to float32 mono via ffmpeg (no soundfile/audioread quirks)."""
    r = subprocess.run([ffmpeg(), "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True)
    if r.returncode != 0:
        raise AudioError("could not read %s" % path.name)
    return np.frombuffer(r.stdout, dtype=np.float32).copy()
