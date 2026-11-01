"""Audio I/O helpers around ffmpeg (decode anything, encode stems)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np

ALLOWED_EXT = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".webm", ".mp4", ".caf", ".aiff", ".aif"}


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
        raise AudioError("could not read the duration of the file")


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
