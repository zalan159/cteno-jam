"""Signal-level analysis: tempo, beats, downbeats, key, beat-synchronous chords.

Ported from the prototype (analyze.py): harmony chroma from guitar+piano+other, bass chroma
weights the root, template matching + Viterbi smoothing. Works on the full mix when stems
are not available (e.g. tests)."""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from .. import theory

SR = 22050
HOP = 512
NOTES = theory.SHARP
Q = {"": [0, 4, 7], "m": [0, 3, 7], "7": [0, 4, 7, 10], "maj7": [0, 4, 7, 11],
     "m7": [0, 3, 7, 10], "sus4": [0, 5, 7], "dim": [0, 3, 6]}
PRIOR = {"": 1.0, "m": 1.0, "7": 0.85, "maj7": 0.8, "m7": 0.85, "sus4": 0.6, "dim": 0.5}
KK_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def _norm(x):
    return x / (np.linalg.norm(x, axis=0, keepdims=True) + 1e-9)


def detect_key(y: np.ndarray, sr: int = SR) -> str:
    import librosa
    c = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=2048).mean(1)
    best = max([(np.corrcoef(np.roll(KK_MAJ, k), c)[0, 1], k, False) for k in range(12)] +
               [(np.corrcoef(np.roll(KK_MIN, k), c)[0, 1], k, True) for k in range(12)])
    return theory.Key(best[1], best[2]).name


def beats(perc: np.ndarray, sr: int = SR):
    import librosa
    tempo, bf = librosa.beat.beat_track(y=perc, sr=sr, hop_length=HOP, units="frames")
    tempo = float(np.atleast_1d(tempo)[0])
    return tempo, bf


def downbeat_phase(onset_env: np.ndarray, beat_frames: np.ndarray, meter: int = 4) -> int:
    """Pick which beat (0..meter-1) is the bar's first by accent strength."""
    if len(beat_frames) < meter * 2:
        return 0
    s = [float(np.mean(onset_env[beat_frames[k::meter].clip(0, len(onset_env) - 1)])) for k in range(meter)]
    return int(np.argmax(s))


def chords(harm: np.ndarray, bass: Optional[np.ndarray], beat_frames: np.ndarray, length: int,
           sr: int = SR, switch: float = -0.35) -> List[Dict]:
    import librosa
    ch = librosa.feature.chroma_cqt(y=harm, sr=sr, hop_length=HOP, bins_per_octave=36)
    chs = librosa.util.sync(ch, beat_frames, aggregate=np.median)
    if bass is not None:
        bch = librosa.feature.chroma_cqt(y=bass, sr=sr, hop_length=HOP, fmin=librosa.note_to_hz("E1"), n_octaves=4)
        bchs = librosa.util.sync(bch, beat_frames, aggregate=np.median)
    else:
        bchs = np.zeros_like(chs)
    times = librosa.frames_to_time(np.concatenate([[0], beat_frames]), sr=sr, hop_length=HOP)
    labels, T, B = [], [], []
    for r in range(12):
        for q, iv in Q.items():
            t = np.zeros(12); t[[(r + i) % 12 for i in iv]] = 1; t[r] += 0.5
            labels.append(NOTES[r] + q); T.append(t / np.linalg.norm(t) * PRIOR[q])
            b = np.zeros(12); b[r] = 1; B.append(b)
    T, B = np.array(T), np.array(B)
    S = T @ _norm(chs) + 0.35 * (B @ _norm(bchs))
    # "no chord" when the harmony is silent
    energy = chs.sum(0)
    silent = energy < 0.05 * (np.percentile(energy, 95) + 1e-9)
    n = len(labels)
    P = np.full((n, n), switch); np.fill_diagonal(P, 0.0)
    score = S[:, 0].copy(); back = np.zeros(S.shape, int)
    for t in range(1, S.shape[1]):
        cand = score[:, None] + P
        back[:, t] = cand.argmax(0); score = cand.max(0) + S[:, t]
    path = [int(score.argmax())]
    for t in range(S.shape[1] - 1, 0, -1):
        path.append(back[path[-1], t])
    path = path[::-1]
    segs: List[Dict] = []
    for i, p in enumerate(path):
        lab = "N" if silent[i] else labels[p]
        t0 = float(times[i]); t1 = float(times[i + 1]) if i + 1 < len(times) else length / sr
        if t1 <= t0:
            continue
        if segs and segs[-1]["chord"] == lab:
            segs[-1]["end"] = t1; segs[-1]["beats"] += 1
        else:
            segs.append({"start": t0, "end": t1, "chord": lab, "beats": 1})
    # a leading "N" before the music starts is kept; trailing silence too (UI shows "–")
    segs = [s for s in segs if s["chord"] != "N" or s["end"] - s["start"] > 0.3]
    for k, s in enumerate(segs):
        s["id"] = "c%03d" % (k + 1)
        s["start"], s["end"] = round(s["start"], 3), round(s["end"], 3)
    return segs


def analyze(stems: Dict[str, np.ndarray], sr: int = SR) -> Dict:
    """`stems` maps names to mono float arrays at `sr`; needs at least 'mix' or the 6 stems."""
    import librosa
    L = min(len(v) for v in stems.values())
    st = {k: v[:L] for k, v in stems.items()}
    full = st.get("mix")
    if full is None:
        full = sum(st[k] for k in st)
    perc = (st["drums"] + st["bass"]) if "drums" in st and "bass" in st else full
    harm = sum(st[k] for k in ("guitar", "piano", "other") if k in st) if any(k in st for k in ("guitar", "piano", "other")) else full
    bass = st.get("bass")
    tempo, bf = beats(perc, sr)
    if len(bf) < 4:  # beatless audio: fall back to a fixed grid at 90 BPM
        tempo = 90.0
        bf = librosa.time_to_frames(np.arange(0, L / sr, 60 / tempo), sr=sr, hop_length=HOP)
    onset = librosa.onset.onset_strength(y=perc, sr=sr, hop_length=HOP)
    phase = downbeat_phase(onset, bf)
    beat_times = [round(float(t), 3) for t in librosa.frames_to_time(bf, sr=sr, hop_length=HOP)]
    key = detect_key(full, sr)
    segs = chords(harm, bass, bf, L, sr)
    rms = {k: float(np.sqrt(np.mean(v ** 2))) for k, v in st.items() if k != "mix"}
    return {"tempo": round(tempo, 1), "meter": 4, "key": key, "beats": beat_times,
            "downbeats": beat_times[phase::4], "chords": segs, "stem_energy": rms,
            "duration": round(L / sr, 3)}
