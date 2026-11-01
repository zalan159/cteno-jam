#!/usr/bin/env python3
"""Synthesise the bundled demo songs from scratch (numpy only), so the repository ships no
recorded or copyrighted audio. Everything this script writes is released under CC0 1.0.

Songs (melodies and lyrics are in the public domain):
  * "Twinkle, Twinkle, Little Star" — melody: French folk tune "Ah! vous dirai-je, maman"
    (published 1761); lyrics: Jane Taylor, "The Star" (1806).
  * "Frère Jacques" — French nursery round (18th century, traditional).

Each song is rendered as six instruments (lead "voice", strummed guitar, piano, bass, drums,
pad) so the separation, chord and lyric pipeline has something real to work on, and we know
the ground truth (chords, key, tempo, lyric times) to test against.

    python scripts/make_demo.py OUT_DIR        # writes <slug>.mp3, <slug>.lrc, <slug>.truth.json
"""
from __future__ import annotations

import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
rng = np.random.default_rng(7)
NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
CH = {"": (0, 4, 7), "m": (0, 3, 7), "7": (0, 4, 7, 10)}


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def midi(name, octave):
    return 12 * (octave + 1) + NOTE[name]


def env_adsr(n, a=0.01, d=0.08, s=0.7, r=0.08):
    e = np.ones(n) * s
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    na = min(na, n); e[:na] = np.linspace(0, 1, na)
    nd = min(nd, max(0, n - na)); e[na:na + nd] = np.linspace(1, s, nd)
    nr = min(nr, n); e[n - nr:] *= np.linspace(1, 0, nr)
    return e


def voice(f, n, vowel="a"):
    """Formant 'singing' voice: harmonic source with vibrato through vowel formants."""
    t = np.arange(n) / SR
    vib = 1 + 0.012 * np.sin(2 * np.pi * 5.5 * t) * np.clip(t / 0.25, 0, 1)
    ph = np.cumsum(2 * np.pi * f * vib / SR)
    src = np.zeros(n)
    for k in range(1, 40):
        if f * k > 7000:
            break
        src += np.sin(k * ph) / k ** 1.1
    F = {"a": [(800, 80, 1.0), (1150, 90, 0.5), (2900, 120, 0.25)],
         "i": [(300, 60, 1.0), (2300, 100, 0.4), (3000, 120, 0.25)],
         "u": [(350, 60, 1.0), (600, 80, 0.4), (2400, 120, 0.15)],
         "e": [(400, 70, 1.0), (2000, 100, 0.45), (2600, 120, 0.25)],
         "o": [(450, 70, 1.0), (800, 80, 0.5), (2830, 120, 0.15)]}[vowel]
    spec = np.fft.rfft(src)
    fr = np.fft.rfftfreq(n, 1 / SR)
    filt = sum(g / (1 + ((fr - c) / bw) ** 2) for c, bw, g in F)
    out = np.fft.irfft(spec * filt, n)
    out += 0.004 * rng.standard_normal(n) * env_adsr(n, 0.02, 0.05, 0.2, 0.05)  # breath
    return out / (np.abs(out).max() + 1e-9) * env_adsr(n, 0.04, 0.1, 0.85, 0.09)


def pluck(f, n, bright=0.5):
    """Plucked string: harmonics with faster decay for higher partials + a pick-noise click
    (vectorised stand-in for Karplus-Strong)."""
    t = np.arange(n) / SR
    s = np.zeros(n)
    for k in range(1, 16):
        if f * k > 9000:
            break
        amp = (1.0 / k) * (1 + bright * 0.5 * np.sin(k * 1.3)) * np.sin(np.pi * k * 0.18)
        s += amp * np.sin(2 * np.pi * f * k * t + rng.uniform(0, 6.28)) * np.exp(-t * (2.2 + 0.9 * k))
    click = rng.standard_normal(min(n, 300)) * np.linspace(1, 0, min(n, 300)) * 0.3
    s[:len(click)] += click
    return s * env_adsr(n, 0.001, 0.01, 1.0, 0.04)


def piano(f, n):
    t = np.arange(n) / SR
    s = sum(np.sin(2 * np.pi * f * k * t) * (0.6 ** (k - 1)) * np.exp(-t * (1.5 + k)) for k in range(1, 7))
    return s * env_adsr(n, 0.003, 0.05, 1.0, 0.05)


def bass_note(f, n):
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t) + 0.12 * np.sin(6 * np.pi * f * t)
    return s * env_adsr(n, 0.005, 0.1, 0.6, 0.06)


def kick(n):
    t = np.arange(n) / SR
    f = 50 + 90 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def snare(n):
    t = np.arange(n) / SR
    return (0.7 * rng.standard_normal(n) + 0.4 * np.sin(2 * np.pi * 190 * t)) * np.exp(-t * 18)


def hat(n):
    t = np.arange(n) / SR
    x = rng.standard_normal(n)
    x = np.diff(np.concatenate([[0], x]))  # crude high-pass
    return x * np.exp(-t * 60) * 0.5


def add(track, start_s, sig, gain=1.0):
    i = int(start_s * SR)
    j = min(len(track), i + len(sig))
    if i < len(track):
        track[i:j] += gain * sig[:j - i]


def chord_tones(sym, octave=3):
    root = sym.rstrip("m7") if sym not in ("Bm", "Em", "Am", "F#m") else sym[:-1]
    q = sym[len(root):]
    r = midi(root, octave)
    return [r + i for i in CH[q]]


def render(song):
    bpm, beats_per_bar = song["bpm"], 4
    spb = 60 / bpm
    bars = song["bars"]
    total = (len(bars) + 1) * beats_per_bar * spb
    n = int(total * SR)
    T = {k: np.zeros(n) for k in ("vocals", "guitar", "piano", "bass", "drums", "other")}
    chords_truth = []
    # harmony: one chord per half bar (2 beats) or full bar
    for b, bar in enumerate(bars):
        halves = bar if isinstance(bar, list) else [bar, bar]
        for h, sym in enumerate(halves):
            t0 = (b * 4 + h * 2) * spb
            if chords_truth and chords_truth[-1]["chord"] == sym:
                chords_truth[-1]["end"] = round(t0 + 2 * spb, 3); chords_truth[-1]["beats"] += 2
            else:
                chords_truth.append({"start": round(t0, 3), "end": round(t0 + 2 * spb, 3), "chord": sym, "beats": 2})
            tones = chord_tones(sym, 3)
            # guitar: D - D U - U D U strum on 8ths (two per beat), plucked strings with strum spread
            for k, (hit, up) in enumerate([(1, 0), (0, 0), (1, 0), (1, 1)]):
                if not hit:
                    continue
                ts = t0 + k * spb / 2
                order = tones + [tones[0] + 12, tones[1] + 12]
                order = order[::-1] if up else order
                for j, m in enumerate(order):
                    add(T["guitar"], ts + j * 0.012, pluck(hz(m), int(spb * SR), 0.6), 0.16 if not up else 0.1)
            # piano: block chord on beat 1 of each half
            for m in tones:
                add(T["piano"], t0, piano(hz(m + 12), int(2 * spb * SR)), 0.12)
            # bass: root on beats 1 and 2 (fifth on 2)
            add(T["bass"], t0, bass_note(hz(tones[0] - 12), int(spb * SR * 0.95)), 0.45)
            add(T["bass"], t0 + spb, bass_note(hz(tones[0] - 12 + 7), int(spb * SR * 0.95)), 0.35)
            # pad (other): soft sustained fifth
            t = np.arange(int(2 * spb * SR)) / SR
            pad = sum(np.sin(2 * np.pi * hz(m + 24) * t) for m in (tones[0], tones[2])) * env_adsr(len(t), 0.2, 0.1, 0.8, 0.2)
            add(T["other"], t0, pad, 0.03)
    # drums: kick 1 & 3, snare 2 & 4, hats on 8ths; skip the count-in bar
    for b in range(len(bars)):
        for beat in range(4):
            t0 = (b * 4 + beat) * spb
            add(T["drums"], t0, kick(int(0.35 * SR)) if beat in (0, 2) else snare(int(0.25 * SR)), 0.55 if beat in (0, 2) else 0.35)
            add(T["drums"], t0, hat(int(0.08 * SR)), 0.25)
            add(T["drums"], t0 + spb / 2, hat(int(0.06 * SR)), 0.18)
    # vocal melody with lyric syllables
    lrc, lines_truth = [], []
    for (bar0, phrase) in song["phrases"]:
        t = bar0 * 4 * spb
        line = {"start": round(t, 3), "units": []}
        text = []
        for syl, note, beats, vowel in phrase:
            dur = beats * spb
            if syl:
                add(T["vocals"], t, voice(hz(note), int(dur * SR * 0.92), vowel), 0.5)
                line["units"].append({"u": syl, "t": round(t, 3)})
                text.append(syl)
            t += dur
        line["text"] = song["join"](text)
        lines_truth.append(line)
        m, s = divmod(line["start"], 60)
        lrc.append("[%02d:%05.2f]%s" % (m, s, line["text"]))
    mix = sum(T.values())
    peak = np.abs(mix).max()
    mix = mix / peak * 0.9
    truth = {"title": song["title"], "key": song["key"], "tempo": bpm, "chords": chords_truth, "lines": lines_truth,
             "duration": round(total, 3), "license": "CC0-1.0", "credits": song["credits"]}
    return mix, T, truth, "\n".join(lrc) + "\n"


def save_wav(path, x):
    x = np.clip(x, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        st = np.stack([x, x], 1)
        w.writeframes((st * 32767).astype("<i2").tobytes())


def notes(spec, octave=4):
    """'D D A A B B A2' -> [(midi, beats)]"""
    out = []
    for tok in spec.split():
        beats = 1
        if tok[-1].isdigit() and tok[-2] not in "#":
            tok, beats = tok[:-1], int(tok[-1])
        o = octave
        if tok.endswith("'"):
            tok, o = tok[:-1], octave + 1
        out.append((midi(tok, o), beats))
    return out


def phrase(words, spec, vowels, octave=4):
    ns = notes(spec, octave)
    assert len(ns) == len(words), (words, spec)
    return [(w, m, b, v) for w, (m, b), v in zip(words, ns, vowels)]


def twinkle():
    # Key D major, 100 BPM. One count-in bar, then 12 bars, twice (24 bars) + outro bar.
    A = ["Twin", "kle ", "twin", "kle ", "lit", "tle ", "star "]
    p = [
        (A, "D D A A B B A2", "iiiiiia"),
        (["How ", "I ", "won", "der ", "what ", "you ", "are "], "G G F# F# E E D2", "aaueaua"),
        (["Up ", "a", "bove ", "the ", "world ", "so ", "high "], "A A G G F# F# E2", "uauaoaa"),
        (["Like ", "a ", "dia", "mond ", "in ", "the ", "sky "], "A A G G F# F# E2", "aaiaiaa"),
        (A, "D D A A B B A2", "iiiiiia"),
        (["How ", "I ", "won", "der ", "what ", "you ", "are "], "G G F# F# E E D2", "aaueaua"),
    ]
    p2 = [
        (["When ", "the ", "bla", "zing ", "sun ", "is ", "gone "], "D D A A B B A2", "eaaiuio"),
        (["When ", "he ", "noth", "ing ", "shines ", "up", "on "], "G G F# F# E E D2", "eiuiaao"),
        (["Then ", "you ", "show ", "your ", "lit", "tle ", "light "], "A A G G F# F# E2", "euooiia"),
        (["Twin", "kle ", "twin", "kle ", "all ", "the ", "night "], "A A G G F# F# E2", "iiiioaa"),
        (A, "D D A A B B A2", "iiiiiia"),
        (["How ", "I ", "won", "der ", "what ", "you ", "are "], "G G F# F# E E D2", "aaueaua"),
    ]
    phrases = []
    bar = 1
    for words, spec, vow in p + p2:
        phrases.append((bar, phrase(words, spec, vow)))
        bar += 2
    verse = [["D", "D"], ["G", "D"], ["G", "D"], ["A", "D"], ["D", "G"], ["D", "A"], ["D", "G"], ["D", "A"],
             ["D", "D"], ["G", "D"], ["G", "D"], ["A", "D"]]
    bars = [["D", "D"]] + verse + verse + [["D", "D"]]
    return {"slug": "twinkle", "title": "Twinkle, Twinkle, Little Star", "key": "D major", "bpm": 100, "bars": bars,
            "phrases": phrases, "join": lambda ws: "".join(ws).replace("  ", " ").strip(),
            "credits": "Melody: 'Ah! vous dirai-je, maman' (French folk tune, 1761). Lyrics: Jane Taylor, 'The Star' (1806). "
                       "Public domain. Arrangement and synthesis: Cteno Jam contributors, CC0 1.0."}


def jacques():
    # Key F major (flats, to exercise spelling), 96 BPM.
    lines = [
        (["Frè", "re ", "Jac", "ques "], "F G A F", "eeao"),
        (["Frè", "re ", "Jac", "ques "], "F G A F", "eeao"),
        (["Dor", "mez ", "vous "], "A Bb C'2", "oeu"),
        (["Dor", "mez ", "vous "], "A Bb C'2", "oeu"),
        (["Son", "nez ", "les ", "ma", "ti", "nes "], "C' D' C' Bb A F2", "oeeaii"),  # 8ths simplified to quarters
        (["Son", "nez ", "les ", "ma", "ti", "nes "], "C' D' C' Bb A F2", "oeeaii"),
        (["Ding ", "dang ", "dong "], "F C F2", "iao"),
        (["Ding ", "dang ", "dong "], "F C F2", "iao"),
    ]
    phrases = []
    bar = 1
    for _ in range(2):
        for words, spec, vow in lines:
            phrases.append((bar, phrase(words, spec.replace("Bb", "A#"), vow)))
            bar += 1 if sum(b for _, b in notes(spec.replace("Bb", "A#"))) <= 4 else 2
    n_bars = bar - 1
    prog = [["F", "F"], ["F", "F"], ["F", "C"], ["F", "C"], ["F", "Bb"], ["F", "C"], ["F", "C"], ["F", "F"]]
    if n_bars > 16:
        prog = prog + [["F", "C"]] * (n_bars // 2 - 8)
    bars = [["F", "F"]] + (prog * 4)[:n_bars] + [["F", "F"]]
    return {"slug": "frere-jacques", "title": "Frère Jacques", "key": "F major", "bpm": 96, "bars": bars,
            "phrases": phrases, "join": lambda ws: "".join(ws).replace("  ", " ").strip(),
            "credits": "Traditional French nursery round (18th century). Public domain. "
                       "Arrangement and synthesis: Cteno Jam contributors, CC0 1.0."}


CH.update({})
NOTE.update({"Bb": 10})


def main(out_dir: str, which=("twinkle", "frere-jacques")):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for song in (twinkle(), jacques()):
        if song["slug"] not in which:
            continue
        mix, tracks, truth, lrc = render(song)
        wav = out / (song["slug"] + ".wav")
        save_wav(wav, mix)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "160k",
                        "-metadata", "title=" + song["title"], "-metadata", "comment=CC0 1.0 - Cteno Jam demo",
                        str(out / (song["slug"] + ".mp3"))], check=True)
        wav.unlink()
        (out / (song["slug"] + ".lrc")).write_text(lrc, encoding="utf-8")
        (out / (song["slug"] + ".truth.json")).write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
        print("wrote", song["slug"], "%.1fs" % truth["duration"], len(truth["chords"]), "chord segments", len(truth["lines"]), "lines")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo/source")
