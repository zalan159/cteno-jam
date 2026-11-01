"""Lyrics: find them (user text / LRC → LRCLIB → Whisper) and time them unit by unit.

A *unit* is what gets highlighted: one CJK character, or one Latin word. Output format:

    {"source": "user|lrclib|whisper|none", "offset": float, "lines": [
        {"id": "l001", "start": 12.3, "end": 15.0, "text": "...",
         "chars": [{"c": "Twin", "t": 12.31, "end": 12.6}, ...]}]}

Alignment strategy (no non-commercial models):
  1. If Whisper word timestamps exist, align the lyric units to the recognised words with
     Needleman-Wunsch on normalised tokens (pinyin for Chinese when pypinyin is installed).
  2. Units Whisper missed are interpolated inside their line.
  3. Without Whisper words, units are placed on vocal-stem onsets inside each LRC line window
     (the prototype's method), with a global offset fitted to vocal activity.
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

import numpy as np

LRC_RE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]")
META_RE = re.compile(r"^\[(ti|ar|al|by|offset|length|re|ve):", re.I)


# ---------------------------------------------------------------- parsing
from .text import is_cjk, units  # noqa: E402,F401


def parse_lrc(text: str) -> List[Tuple[Optional[float], str]]:
    """Return [(time or None, line)]. Plain text (no tags) gives time None for every line."""
    rows: List[Tuple[Optional[float], str]] = []
    any_tag = False
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or META_RE.match(raw):
            continue
        tags = LRC_RE.findall(raw)
        body = LRC_RE.sub("", raw).strip()
        body = re.sub(r"<\d+:\d+(?:\.\d+)?>", "", body)  # enhanced LRC word tags
        if tags:
            any_tag = True
            for m, s in tags:
                rows.append((int(m) * 60 + float(s), body))
        else:
            rows.append((None, body))
    if any_tag:
        rows = sorted([r for r in rows if r[0] is not None], key=lambda r: r[0])
    return rows


# ---------------------------------------------------------------- LRCLIB
def lrclib_lookup(title: str, artist: str, duration: float, base: str = "https://lrclib.net",
                  timeout: float = 8.0) -> Optional[Dict]:
    """Synced lyrics from LRCLIB (https://lrclib.net, free, no key). Returns {"lrc", "id", "name", "artist"} or None."""
    if not title:
        return None
    headers = {"User-Agent": "CtenoJam/0.1 (self-hosted; lrclib lookup)"}

    def get(path, q):
        url = base.rstrip("/") + path + "?" + urllib.parse.urlencode(q)
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            return json.load(r)

    cands = []
    try:
        if artist:
            try:
                cands.append(get("/api/get", {"track_name": title, "artist_name": artist, "duration": int(round(duration))}))
            except Exception:  # noqa: BLE001 — 404 when not found
                pass
        res = get("/api/search", {"q": (title + " " + artist).strip()})
        cands += res if isinstance(res, list) else []
    except Exception:  # noqa: BLE001 — offline or rate limited
        if not cands:
            return None
    best = None
    for c in cands:
        if not isinstance(c, dict) or not c.get("syncedLyrics"):
            continue
        d = abs(float(c.get("duration") or 0) - duration)
        if d > 8:
            continue
        if best is None or d < best[0]:
            best = (d, c)
    if not best:
        return None
    c = best[1]
    return {"lrc": c["syncedLyrics"], "id": c.get("id"), "name": c.get("trackName"), "artist": c.get("artistName")}


# ---------------------------------------------------------------- whisper
def transcribe(vocals_path: str, model_name: str = "small", device: str = "auto",
               language: Optional[str] = None) -> Tuple[List[Dict], Optional[str]]:
    """faster-whisper word timestamps on the vocal stem. Returns ([{w, t, end, p}], language).

    The audio is decoded with ffmpeg here and handed over as an array, so faster-whisper's own
    PyAV decoder (version-sensitive) is not involved."""
    from faster_whisper import WhisperModel
    from .audio import load_mono
    dev = device if device in ("cpu", "cuda") else "auto"
    model = WhisperModel(model_name, device=dev, compute_type="int8" if dev != "cuda" else "float16")
    pcm = load_mono(vocals_path, 16000) if isinstance(vocals_path, str) else vocals_path
    segs, info = model.transcribe(pcm, word_timestamps=True, vad_filter=True, language=language,
                                  condition_on_previous_text=False)
    words = []
    for s in segs:
        for w in s.words or []:
            if w.word.strip():
                words.append({"w": w.word.strip(), "t": float(w.start), "end": float(w.end), "p": float(w.probability)})
    return words, getattr(info, "language", None)


def words_to_lines(words: List[Dict], gap: float = 1.2) -> List[Tuple[float, str]]:
    """Group Whisper words into lines on pauses (used when no lyrics were found)."""
    lines: List[Tuple[float, str]] = []
    cur: List[Dict] = []
    for w in words:
        if cur and (w["t"] - cur[-1]["end"] > gap or len(cur) >= 14):
            lines.append((cur[0]["t"], _join(cur)))
            cur = []
        cur.append(w)
    if cur:
        lines.append((cur[0]["t"], _join(cur)))
    return lines


def _join(ws: List[Dict]) -> str:
    s = ""
    for w in ws:
        if s and not (is_cjk(w["w"][0]) and is_cjk(s[-1])):
            s += " "
        s += w["w"]
    return s


# ---------------------------------------------------------------- alignment
def _norm_token(u: str) -> str:
    u = "".join(ch for ch in unicodedata.normalize("NFKC", u).lower() if ch.isalnum())
    if u and is_cjk(u[0]):
        try:
            from pypinyin import lazy_pinyin
            return "".join(lazy_pinyin(u))
        except ImportError:
            return u
    return u


def _whisper_tokens(words: List[Dict]) -> List[Tuple[str, float, float]]:
    """Split Whisper words into the same unit granularity as the lyrics."""
    out = []
    for w in words:
        us = units(w["w"]) or [w["w"]]
        n = len(us)
        for i, u in enumerate(us):
            t0 = w["t"] + (w["end"] - w["t"]) * i / n
            t1 = w["t"] + (w["end"] - w["t"]) * (i + 1) / n
            out.append((_norm_token(u), t0, t1))
    return out


def _sim(a: str, b: str) -> float:
    if not a or not b:
        return -1.0
    if a == b:
        return 2.0
    # partial credit for near matches (homophones, plural, typos)
    common = len(set(a) & set(b)) / max(len(set(a) | set(b)), 1)
    return 1.0 if common >= 0.6 else -1.0


def needleman_wunsch(a: List[str], b: List[str], gap: float = -0.6) -> List[Tuple[int, int]]:
    """Global alignment; returns matched index pairs (i in a, j in b)."""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return []
    S = np.zeros((n + 1, m + 1), dtype=np.float32)
    S[:, 0] = np.arange(n + 1) * gap
    S[0, :] = np.arange(m + 1) * gap
    bt = np.zeros((n + 1, m + 1), dtype=np.int8)
    for i in range(1, n + 1):
        ai = a[i - 1]
        for j in range(1, m + 1):
            d = S[i - 1, j - 1] + _sim(ai, b[j - 1])
            u = S[i - 1, j] + gap
            l = S[i, j - 1] + gap
            if d >= u and d >= l:
                S[i, j], bt[i, j] = d, 0
            elif u >= l:
                S[i, j], bt[i, j] = u, 1
            else:
                S[i, j], bt[i, j] = l, 2
    pairs = []
    i, j = n, m
    while i > 0 and j > 0:
        if bt[i, j] == 0:
            if _sim(a[i - 1], b[j - 1]) > 0:
                pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif bt[i, j] == 1:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def fit_offset(line_starts: List[float], vocal_act: np.ndarray, fps: float, span: float = 8.0) -> float:
    """Global LRC↔audio offset maximising 'silence just before, voice just after' at line starts.

    Songs are periodic, so the score has peaks one bar or phrase apart. A shift away from 0 must
    beat offset 0 clearly, and the score carries a small prior toward 0."""
    def score(off):
        s, n = 0.0, 0
        for t in line_starts:
            i = int((t + off) * fps)
            if 8 < i < len(vocal_act) - 40:
                s += vocal_act[i:i + 30].mean() - vocal_act[i - 8:i].mean()
                n += 1
        return s / max(n, 1)

    zero = score(0.0)
    best, best_s = 0.0, zero
    for off in np.arange(-span, span + 1e-9, 0.02):
        s = score(off) - 0.01 * abs(off)
        if s > best_s:
            best, best_s = float(off), s
    if best != 0.0 and best_s - zero < 0.08:
        return 0.0
    return round(best, 2)


def vocal_onsets(v: np.ndarray, sr: int = 22050, H: int = 256, rms: Optional[np.ndarray] = None) -> List[float]:
    """Sung-note onsets on a (separated, so somewhat noisy) vocal stem.

    Generic spectral-flux onsets fire on every bleed transient. Sung syllables are better found
    as (a) the start of a voiced stretch and (b) a pitch change that holds, plus (c) a clear
    re-articulation in loudness on the same pitch."""
    import librosa
    if rms is None:
        rms = librosa.feature.rms(y=v, hop_length=H)[0]
    f0 = librosa.yin(v, fmin=80, fmax=1000, sr=sr, frame_length=1024, hop_length=H)
    n = min(len(f0), len(rms))
    f0, rms = f0[:n], rms[:n]
    voiced = rms > 0.2 * np.percentile(rms, 95)
    midi = librosa.hz_to_midi(np.maximum(f0, 1.0))
    fps = sr / H
    out: List[float] = []
    prev, run_start, cand = None, None, None
    for i in range(n):
        if not voiced[i]:
            prev, cand = None, None
            continue
        if prev is None:
            out.append(i / fps)            # (a) voicing starts
            prev = midi[i]
            continue
        if abs(midi[i] - prev) > 0.7:
            if cand is None:
                cand = i
            elif i - cand >= 3 and np.std(midi[cand:i + 1]) < 0.5:
                out.append(cand / fps)     # (b) a new pitch held for 3+ frames
                prev, cand = float(np.median(midi[cand:i + 1])), None
        else:
            cand = None
            prev = 0.9 * prev + 0.1 * midi[i]
    lr = np.log(rms + 1e-4)
    rise = np.maximum(0, np.diff(lr, prepend=lr[0]))
    rise = np.convolve(rise, np.ones(3) / 3, "same")
    for t in librosa.onset.onset_detect(onset_envelope=rise, sr=sr, hop_length=H, units="time", delta=0.08, wait=8):
        if voiced[min(int(t * fps) + 2, n - 1)]:
            out.append(float(t))           # (c) re-articulation
    out.sort()
    merged: List[float] = []
    for t in out:
        if not merged or t - merged[-1] > 0.09:
            merged.append(t)
    return merged


def align(rows: List[Tuple[Optional[float], str]], duration: float, words: Optional[List[Dict]] = None,
          vocals: Optional[np.ndarray] = None, sr: int = 22050, offset_span: float = 8.0,
          beats: Optional[List[float]] = None) -> Dict:
    """Give every unit of every line a start/end time."""
    rows = [(t, s) for t, s in rows if s.strip()]
    if not rows:
        return {"offset": 0.0, "lines": []}
    act, onsets, fps = None, [], 0.0
    if vocals is not None and len(vocals):
        import librosa
        H = 256
        rms = librosa.feature.rms(y=vocals, hop_length=H)[0]
        act = (rms > 0.25 * np.percentile(rms, 95)).astype(np.float32)
        fps = sr / H
        onsets = vocal_onsets(vocals, sr, H, rms)

    timed = all(t is not None for t, _ in rows)
    # ---- untimed text: place lines on vocal phrases (or spread evenly)
    if not timed:
        starts = _phrase_starts(act, fps, len(rows), duration) if act is not None else \
            list(np.linspace(0, duration * 0.95, len(rows), endpoint=False))
        rows = [(float(starts[k]), s) for k, (_, s) in enumerate(rows)]
    off = 0.0
    tok = _whisper_tokens(words) if words else []
    if tok:
        # offset from whisper matches is implicit; still fit a rough global shift for LRC
        pass
    elif act is not None and timed and offset_span > 0:
        off = fit_offset([t for t, _ in rows], act, fps, offset_span)
    lines = []
    for k, (t, txt) in enumerate(rows):
        t0 = max(0.0, t + off)
        t1 = (rows[k + 1][0] + off) if k + 1 < len(rows) else min(duration, t0 + 8)
        t1 = max(t1, t0 + 0.5)
        lines.append({"id": "l%03d" % (k + 1), "start": round(t0, 3), "end": round(t1, 3), "text": txt.strip(),
                      "chars": [{"c": u, "t": None, "end": None} for u in units(txt)]})

    if tok:
        flat = [(li, ci, _norm_token(c["c"])) for li, ln in enumerate(lines) for ci, c in enumerate(ln["chars"])]
        pairs = needleman_wunsch([f[2] for f in flat], [x[0] for x in tok])
        matched = 0
        for i, j in pairs:
            li, ci, _ = flat[i]
            lines[li]["chars"][ci]["t"], lines[li]["chars"][ci]["end"] = round(tok[j][1], 3), round(tok[j][2], 3)
            matched += 1
        # lines whose units were matched get their window from the matches
        for ln in lines:
            ts = [c["t"] for c in ln["chars"] if c["t"] is not None]
            if ts:
                ln["start"] = round(min(ts), 3)
    grid = _eighth_grid(beats) if beats else []
    for ln in lines:
        _fill_line(ln, onsets, grid)
    # keep lines ordered and non-overlapping
    for a, b in zip(lines, lines[1:]):
        if b["start"] < a["start"]:
            b["start"] = a["start"]
        a["end"] = round(min(a["end"], max(b["start"], a["chars"][-1]["end"] or a["end"])), 3)
    return {"offset": off, "lines": lines}


def _phrase_starts(act: np.ndarray, fps: float, n: int, duration: float) -> List[float]:
    """Starts of the n longest vocal phrases, in time order; evenly spaced fallback."""
    edges = np.flatnonzero(np.diff(np.concatenate([[0], act, [0]])))
    runs = [(edges[i] / fps, edges[i + 1] / fps) for i in range(0, len(edges) - 1, 2)]
    # merge runs separated by short gaps into phrases
    phrases = []
    for s, e in runs:
        if phrases and s - phrases[-1][1] < 0.6:
            phrases[-1][1] = e
        else:
            phrases.append([s, e])
    phrases = [p for p in phrases if p[1] - p[0] > 0.4]
    if len(phrases) < n:
        return list(np.linspace(0, duration * 0.95, n, endpoint=False))
    phrases = sorted(sorted(phrases, key=lambda p: p[0] - p[1])[:n])
    return [p[0] for p in phrases]


def _syllables(u: str) -> int:
    """Rough sung-syllable count of a unit: 1 per CJK char, vowel groups for Latin words."""
    u = u.strip().lower()
    if not u:
        return 1
    if is_cjk(u[0]):
        return 1
    groups = re.findall(r"[aeiouyàâäéèêëîïôöùûüœæ]+", u)
    n = len(groups)
    if n > 1 and u.endswith("e") and not u.endswith(("le", "ee", "ie")):
        n -= 1  # silent final e
    return max(1, n)


def _eighth_grid(beats: List[float]) -> List[float]:
    g = []
    for a, b in zip(beats, beats[1:]):
        g += [a, (a + b) / 2]
    if beats:
        g.append(beats[-1])
    return g


def _snap(t: float, grid: List[float], after: float) -> float:
    """Nearest grid time to t that is later than `after` (sung syllables sit on the beat grid)."""
    import bisect
    i = bisect.bisect_left(grid, t)
    cands = [g for g in grid[max(0, i - 1):i + 2] if g > after + 0.04]
    return min(cands, key=lambda g: abs(g - t)) if cands else max(t, after + 0.05)


def _fill_line(ln: Dict, onsets: List[float], grid: Optional[List[float]] = None) -> None:
    cs = ln["chars"]
    if not cs:
        return
    t0, t1 = ln["start"], ln["end"]
    known = [i for i, c in enumerate(cs) if c["t"] is not None]
    if not known:
        o = [x for x in onsets if t0 - 0.15 <= x < t1 - 0.05]
        n = len(cs)
        # expected start of each unit from cumulative syllables across the voiced span
        syl = [_syllables(c["c"]) for c in cs]
        cum = np.concatenate([[0], np.cumsum(syl)])[:-1] / max(sum(syl), 1)
        first = t0 if (not o or abs(o[0] - t0) > 0.4) else o[0]
        # a sung line usually fills ~85% of the gap to the next line
        span = max(0.2 * n, min(t1 - first, 0.6 * sum(syl) + 0.5) * 0.85)
        expect = first + cum * max(span, 0.2 * n)
        pick, j = [], 0
        for k, e in enumerate(expect):
            stop = len(o) - (n - k - 1) if len(o) >= n else len(o)
            best = None
            for m in range(j, max(j, stop)):
                if best is None or abs(o[m] - e) < abs(o[best] - e):
                    best = m
            prev = pick[-1] if pick else t0 - 0.2
            if best is not None and abs(o[best] - e) < 0.25:
                pick.append(o[best]); j = best + 1
            elif grid:
                pick.append(_snap(e, grid, prev))
            else:
                pick.append(max(e, prev + 0.05))
        for c, p in zip(cs, pick):
            c["t"] = round(float(p), 3)
    else:
        # interpolate missing units between known neighbours (or line edges)
        anchors = [(-1, t0)] + [(i, cs[i]["t"]) for i in known] + [(len(cs), max(t1, cs[known[-1]]["t"] + 0.3))]
        for (ia, ta), (ib, tb) in zip(anchors, anchors[1:]):
            for i in range(ia + 1, ib):
                cs[i]["t"] = round(ta + (tb - ta) * (i - ia) / (ib - ia), 3)
    for i, c in enumerate(cs):
        nxt = cs[i + 1]["t"] if i + 1 < len(cs) else None
        if c.get("end") is None:
            c["end"] = round(min(nxt, c["t"] + 0.8) if nxt is not None else min(t1, c["t"] + 0.6), 3)
        if nxt is not None and c["t"] > nxt:
            c["t"] = nxt
    ln["start"] = cs[0]["t"]
    ln["end"] = round(max(cs[-1]["end"], cs[-1]["t"] + 0.2), 3)
