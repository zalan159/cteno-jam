"""Chord symbols, keys, enharmonic spelling, capo and simplification.

Pure functions, no heavy dependencies. The browser has a mirror in web/js/theory.js;
tests/test_theory.py and web/test/theory.test.mjs pin both to the same behaviour.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
PC = {n: i for i, n in enumerate(SHARP)}
PC.update({n: i for i, n in enumerate(FLAT)})
PC.update({"Cb": 11, "B#": 0, "E#": 5, "Fb": 4})

# Chord qualities we recognise, as intervals above the root.
QUALITIES = {
    "": (0, 4, 7), "m": (0, 3, 7), "7": (0, 4, 7, 10), "maj7": (0, 4, 7, 11), "m7": (0, 3, 7, 10),
    "sus4": (0, 5, 7), "sus2": (0, 2, 7), "dim": (0, 3, 6), "aug": (0, 4, 8), "6": (0, 4, 7, 9),
    "m6": (0, 3, 7, 9), "add9": (0, 2, 4, 7), "9": (0, 4, 7, 10, 2), "m9": (0, 3, 7, 10, 2),
    "7sus4": (0, 5, 7, 10), "dim7": (0, 3, 6, 9), "m7b5": (0, 3, 6, 10), "mmaj7": (0, 3, 7, 11),
}
QUALITY_ALIASES = {"M": "", "maj": "", "min": "m", "-": "m", "M7": "maj7", "Maj7": "maj7", "min7": "m7",
                   "-7": "m7", "sus": "sus4", "o": "dim", "+": "aug", "ø": "m7b5", "°": "dim"}
# Beginner simplification: quality -> triad quality with the same root.
SIMPLE = {"": "", "m": "m", "7": "", "maj7": "", "m7": "m", "sus4": "", "sus2": "", "dim": "m", "aug": "",
          "6": "", "m6": "m", "add9": "", "9": "", "m9": "m", "7sus4": "", "dim7": "m", "m7b5": "m", "mmaj7": "m"}

CHORD_RE = re.compile(r"^([A-G])([#b]?)([^/]*)(?:/([A-G])([#b]?))?$")
# Open-position shape families a beginner can play with a capo.
CAPO_SHAPES_MAJOR = ["C", "G", "D", "A", "E"]
CAPO_SHAPES_MINOR = ["Am", "Em", "Dm"]

# Keys that are conventionally written with flats.
FLAT_MAJOR = {"F", "Bb", "Eb", "Ab", "Db", "Gb"}
FLAT_MINOR = {"D", "G", "C", "F", "Bb", "Eb"}
KEY_NAMES_MAJOR = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
KEY_NAMES_MINOR = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]


@dataclass(frozen=True)
class Chord:
    root: int
    quality: str
    bass: Optional[int] = None
    root_name: str = ""
    bass_name: str = ""

    @property
    def pcs(self) -> frozenset:
        s = {(self.root + i) % 12 for i in QUALITIES[self.quality]}
        if self.bass is not None:
            s.add(self.bass)
        return frozenset(s)


def parse_chord(sym: str) -> Optional[Chord]:
    """Parse 'G#m7', 'Bb/D', 'Cmaj7'. Returns None for 'N' or anything unknown."""
    if not isinstance(sym, str):
        return None
    m = CHORD_RE.match(sym.strip())
    if not m:
        return None
    r, acc, q, b, bacc = m.groups()
    q = QUALITY_ALIASES.get(q, q)
    if q not in QUALITIES:
        return None
    root_name = r + acc
    bass_name = (b + bacc) if b else ""
    return Chord(PC[root_name], q, PC[bass_name] if b else None, root_name, bass_name)


def is_valid_chord(sym: str) -> bool:
    return parse_chord(sym) is not None


@dataclass(frozen=True)
class Key:
    tonic: int
    minor: bool

    @property
    def name(self) -> str:
        return (KEY_NAMES_MINOR if self.minor else KEY_NAMES_MAJOR)[self.tonic] + (" minor" if self.minor else " major")

    @property
    def uses_flats(self) -> bool:
        t = (KEY_NAMES_MINOR if self.minor else KEY_NAMES_MAJOR)[self.tonic]
        return t in (FLAT_MINOR if self.minor else FLAT_MAJOR) or "b" in t


def parse_key(name: str) -> Optional[Key]:
    if not isinstance(name, str):
        return None
    m = re.match(r"^\s*([A-G][#b]?)\s*(major|minor|maj|min|m)?\s*$", name)
    if not m or m[1] not in PC:
        return None
    return Key(PC[m[1]], (m[2] or "major").startswith("min") or m[2] == "m")


# Diatonic spelling: in a major key every scale degree gets its own letter.
_LETTERS = "CDEFGAB"
_LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_MAJOR_STEPS = (0, 2, 4, 5, 7, 9, 11)
_MINOR_STEPS = (0, 2, 3, 5, 7, 8, 10)


def _scale_names(key: Key) -> dict:
    tonic_name = (KEY_NAMES_MINOR if key.minor else KEY_NAMES_MAJOR)[key.tonic]
    li = _LETTERS.index(tonic_name[0])
    out = {}
    for deg, step in enumerate(_MINOR_STEPS if key.minor else _MAJOR_STEPS):
        letter = _LETTERS[(li + deg) % 7]
        pc = (key.tonic + step) % 12
        diff = (pc - _LETTER_PC[letter] + 6) % 12 - 6
        out[pc] = letter + {0: "", 1: "#", -1: "b", 2: "##", -2: "bb"}[diff]
    return out


def note_name(pc: int, key: Optional[Key] = None) -> str:
    """Name a pitch class in the context of a key (diatonic letters first, then sharps/flats by key)."""
    pc %= 12
    if key is not None:
        names = _scale_names(key)
        n = names.get(pc)
        if n and "##" not in n and "bb" not in n and n not in ("Cb", "Fb", "E#", "B#"):
            return n
        if key.minor and pc == (key.tonic + 11) % 12:  # raised 7th in minor (harmonic minor)
            return SHARP[pc] if not key.uses_flats or SHARP[pc] in ("B", "E") else FLAT[pc]
        return (FLAT if key.uses_flats else SHARP)[pc]
    return SHARP[pc]


def spell(sym: str, key: Optional[Key]) -> str:
    """Respell a chord's root/bass for the key without changing what it sounds like."""
    c = parse_chord(sym)
    if c is None:
        return sym
    out = note_name(c.root, key) + c.quality
    if c.bass is not None:
        out += "/" + note_name(c.bass, key)
    return out


def enharmonic_equal(a: str, b: str) -> bool:
    ca, cb = parse_chord(a), parse_chord(b)
    return bool(ca and cb and ca.root == cb.root and ca.quality == cb.quality and ca.bass == cb.bass)


def transpose(sym: str, semitones: int, key: Optional[Key] = None) -> str:
    c = parse_chord(sym)
    if c is None:
        return sym
    nk = Key((key.tonic + semitones) % 12, key.minor) if key else None
    out = note_name(c.root + semitones, nk) + c.quality
    if c.bass is not None:
        out += "/" + note_name(c.bass + semitones, nk)
    return out


def simplify(sym: str) -> str:
    """Beginner version: same root, plain major/minor triad, no slash bass."""
    c = parse_chord(sym)
    if c is None:
        return sym
    return c.root_name + SIMPLE[c.quality]


def is_simplification(original: str, simple: str) -> bool:
    """A valid simplification keeps the root and uses a triad whose notes are in the original chord
    (or is the beginner triad of it)."""
    co, cs = parse_chord(original), parse_chord(simple)
    if not co or not cs or cs.bass is not None or cs.root != co.root:
        return False
    if cs.quality not in ("", "m", "sus4", "sus2", "7", "m7"):
        return False
    if SIMPLE[co.quality] == SIMPLE[cs.quality] or cs.pcs <= co.pcs:
        return True
    return False


def chord_in_key(sym: str, key: Key) -> bool:
    c = parse_chord(sym)
    if c is None:
        return False
    scale = {(key.tonic + s) % 12 for s in (_MINOR_STEPS if key.minor else _MAJOR_STEPS)}
    if key.minor:
        scale.add((key.tonic + 11) % 12)
    return set((c.root + i) % 12 for i in QUALITIES[c.quality][:3]) <= scale


EASY_OPEN = {"C", "G", "D", "A", "E", "Am", "Em", "Dm", "A7", "D7", "E7", "G7", "C7", "B7", "Am7", "Em7", "Dm7",
             "Cmaj7", "Fmaj7", "Asus4", "Dsus4", "Esus4", "Asus2", "Dsus2"}


def best_capo(chords, max_capo: int = 7):
    """Pick the capo fret that makes the most chord time playable with open shapes.

    `chords` is a list of (symbol, duration). Returns (capo, shape_key_name, easy_share)."""
    best = None
    total = sum(d for _, d in chords) or 1.0
    for capo in range(0, max_capo + 1):
        easy = 0.0
        for sym, d in chords:
            c = parse_chord(sym)
            if c is None:
                easy += d
                continue
            shape = SHARP[(c.root - capo) % 12] + c.quality
            shape_s = SHARP[(c.root - capo) % 12] + SIMPLE[c.quality]
            if shape in EASY_OPEN:
                easy += d
            elif shape_s in EASY_OPEN:
                easy += 0.85 * d
        score = easy / total - 0.015 * capo  # prefer lower frets on ties
        if best is None or score > best[0]:
            best = (score, capo, easy / total)
    return best[1], best[2]
