"""Revisions on top of the signal-level analysis.

The analysis produced by the DSP pipeline is the *base*. Every change after that — from
the AI review or from a person editing the sheet — is a small, typed patch with a reason.
The song people see is `replay(base, patches with status == "applied")`.

That gives us, for free:
  * per-patch undo/redo (flip status, replay),
  * "undo all AI changes" (flip every source == "ai"),
  * a model can never rewrite the song: it can only propose patches, and every patch is
    validated here against the state it applies to. Invalid ones are rejected with a reason.
"""
from __future__ import annotations

import copy
import time
from typing import Any, Dict, List, Optional, Tuple

from . import theory

SECTION_LABELS = ("intro", "verse", "prechorus", "chorus", "bridge", "interlude", "solo", "outro")
RHYTHM_KINDS = ("strum", "arpeggio")
# Strum pattern alphabet: D down, U up, x muted hit, - rest, space/| separators; arpeggio uses
# string numbers 1-6 or finger letters p i m a.
STRUM_CHARS = set("DUx-| ")
ARP_CHARS = set("123456pima-| ")
MAX_REASON = 300

AI_OPS = ("set_key", "respell_chord", "replace_chord", "merge_chord", "add_section", "set_capo",
          "simplify_chord", "set_rhythm", "split_line", "merge_lines", "flag_line")
USER_OPS = AI_OPS + ("insert_chord", "delete_chord", "remove_section", "set_line_text", "shift_line")


class PatchError(ValueError):
    pass


def _find(items: List[dict], pid: str) -> Tuple[int, Optional[dict]]:
    for i, it in enumerate(items):
        if it.get("id") == pid:
            return i, it
    return -1, None


def _need(p: dict, *fields):
    for f in fields:
        if f not in p or p[f] is None or p[f] == "":
            raise PatchError("missing field '%s'" % f)


def _next_id(items: List[dict], prefix: str) -> str:
    n = 0
    for it in items:
        s = str(it.get("id", ""))
        if s.startswith(prefix) and s[len(prefix):].isdigit():
            n = max(n, int(s[len(prefix):]))
    return "%s%03d" % (prefix, n + 1)


def validate(a: dict, p: dict, source: str = "ai") -> None:
    """Raise PatchError if patch `p` cannot apply to analysis `a`. Never mutates `a`."""
    if not isinstance(p, dict):
        raise PatchError("patch must be an object")
    op = p.get("op")
    allowed = AI_OPS if source == "ai" else USER_OPS
    if op not in allowed:
        raise PatchError("unknown or not allowed op '%s' (allowed: %s)" % (op, ", ".join(allowed)))
    reason = p.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise PatchError("every patch needs a one-sentence 'reason'")
    if len(reason) > MAX_REASON:
        raise PatchError("reason longer than %d characters" % MAX_REASON)
    chords = a.get("chords", [])
    lines = (a.get("lyrics") or {}).get("lines", [])
    key = theory.parse_key(a.get("key", ""))
    dur = float(a.get("duration") or (chords[-1]["end"] if chords else 0))

    if op == "set_key":
        _need(p, "key")
        if theory.parse_key(p["key"]) is None:
            raise PatchError("'%s' is not a key like 'E major' or 'C# minor'" % p["key"])
    elif op in ("respell_chord", "replace_chord", "simplify_chord", "merge_chord", "delete_chord"):
        _need(p, "id")
        i, seg = _find(chords, p["id"])
        if seg is None:
            raise PatchError("no chord segment with id '%s'" % p["id"])
        if op in ("respell_chord", "replace_chord", "simplify_chord"):
            _need(p, "chord")
            if not theory.is_valid_chord(p["chord"]):
                raise PatchError("'%s' is not a chord symbol this app understands" % p["chord"])
        if op == "respell_chord":
            if not theory.enharmonic_equal(seg["chord"], p["chord"]):
                raise PatchError("respell must sound the same: %s and %s are different chords (use replace_chord)"
                                 % (seg["chord"], p["chord"]))
            if seg["chord"] == p["chord"]:
                raise PatchError("chord is already spelled %s" % p["chord"])
        if op == "replace_chord" and seg["chord"] == p["chord"]:
            raise PatchError("chord is already %s" % p["chord"])
        if op == "simplify_chord" and not theory.is_simplification(seg["chord"], p["chord"]):
            raise PatchError("%s is not a simplification of %s (keep the root, use a triad)" % (p["chord"], seg["chord"]))
        if op == "merge_chord":
            into = p.get("into", "prev")
            if into not in ("prev", "next"):
                raise PatchError("'into' must be 'prev' or 'next'")
            j = i - 1 if into == "prev" else i + 1
            if j < 0 or j >= len(chords):
                raise PatchError("segment %s has no %s neighbour to merge into" % (p["id"], into))
            if source == "ai" and int(seg.get("beats", 99)) > 2:
                raise PatchError("only blips of 1-2 beats may be merged away; %s lasts %s beats"
                                 % (p["id"], seg.get("beats")))
        if op == "delete_chord" and len(chords) < 2:
            raise PatchError("cannot delete the only chord")
    elif op == "insert_chord":
        _need(p, "start", "chord")
        if not theory.is_valid_chord(p["chord"]):
            raise PatchError("'%s' is not a chord symbol" % p["chord"])
        t = float(p["start"])
        if not (0 <= t < dur):
            raise PatchError("start %.2f outside the song (0-%.2f)" % (t, dur))
        if any(abs(c["start"] - t) < 0.05 for c in chords):
            raise PatchError("a chord already starts at %.2f" % t)
    elif op == "add_section":
        _need(p, "start", "end", "label")
        if p["label"] not in SECTION_LABELS:
            raise PatchError("label must be one of %s" % ", ".join(SECTION_LABELS))
        s, e = float(p["start"]), float(p["end"])
        if not (0 <= s < e <= dur + 0.5):
            raise PatchError("section %.2f-%.2f is not inside the song (0-%.2f)" % (s, e, dur))
        for sec in a.get("sections", []):
            if s < sec["end"] - 0.25 and e > sec["start"] + 0.25:
                raise PatchError("overlaps section %s (%s %.1f-%.1f)" % (sec["id"], sec["label"], sec["start"], sec["end"]))
    elif op == "remove_section":
        _need(p, "id")
        if _find(a.get("sections", []), p["id"])[1] is None:
            raise PatchError("no section '%s'" % p["id"])
    elif op == "set_capo":
        if not isinstance(p.get("fret"), int) or not 0 <= p["fret"] <= 9:
            raise PatchError("fret must be an integer 0-9")
        if key is not None and p.get("shapes"):
            k = theory.parse_key(p["shapes"] + (" minor" if key.minor else " major"))
            if k is None or (k.tonic + p["fret"]) % 12 != key.tonic:
                raise PatchError("with capo %d the shapes of %s do not sound in %s" % (p["fret"], p["shapes"], key.name))
    elif op == "set_rhythm":
        _need(p, "kind", "pattern")
        if p["kind"] not in RHYTHM_KINDS:
            raise PatchError("kind must be strum or arpeggio")
        allowed_chars = STRUM_CHARS if p["kind"] == "strum" else ARP_CHARS
        pat = str(p["pattern"])
        if not (2 <= len(pat) <= 40) or not set(pat) <= allowed_chars:
            raise PatchError("pattern '%s' may only use %s" % (pat, "".join(sorted(allowed_chars)).strip()))
    elif op in ("set_line_text", "shift_line"):
        _need(p, "line")
        if _find(lines, p["line"])[1] is None:
            raise PatchError("no lyric line with id '%s'" % p["line"])
        if op == "set_line_text":
            if not isinstance(p.get("text"), str) or not p["text"].strip() or len(p["text"]) > 500:
                raise PatchError("text must be 1-500 characters")
        else:
            d = p.get("delta")
            if not isinstance(d, (int, float)) or not -10 <= d <= 10 or d == 0:
                raise PatchError("delta must be a non-zero number of seconds between -10 and 10")
    elif op in ("split_line", "merge_lines", "flag_line"):
        _need(p, "line")
        i, ln = _find(lines, p["line"])
        if ln is None:
            raise PatchError("no lyric line with id '%s'" % p["line"])
        if op == "split_line":
            at = p.get("at")
            if not isinstance(at, int) or not 0 < at < len(ln["chars"]):
                raise PatchError("'at' must be a character index inside the line (1-%d)" % (len(ln["chars"]) - 1))
        if op == "merge_lines" and i + 1 >= len(lines):
            raise PatchError("line %s is the last line; nothing to merge with" % p["line"])
        if op == "flag_line":
            _need(p, "issue")


def apply(a: dict, p: dict, source: str = "ai") -> dict:
    """Validate and apply one patch; returns a new analysis dict."""
    validate(a, p, source)
    a = copy.deepcopy(a)
    op = p["op"]
    chords = a.setdefault("chords", [])
    if op == "set_key":
        a["key"] = theory.parse_key(p["key"]).name
    elif op in ("respell_chord", "replace_chord"):
        _find(chords, p["id"])[1]["chord"] = p["chord"]
    elif op == "simplify_chord":
        a.setdefault("simplified", {})[p["id"]] = p["chord"]
    elif op in ("merge_chord", "delete_chord"):
        i, seg = _find(chords, p["id"])
        into = p.get("into", "prev") if op == "merge_chord" else ("prev" if i > 0 else "next")
        j = i - 1 if into == "prev" else i + 1
        nb = chords[j]
        nb["start"], nb["end"] = min(nb["start"], seg["start"]), max(nb["end"], seg["end"])
        nb["beats"] = int(nb.get("beats", 0)) + int(seg.get("beats", 0))
        del chords[i]
        a.get("simplified", {}).pop(p["id"], None)
        # neighbours that now hold the same chord collapse into one
        _collapse(chords)
    elif op == "insert_chord":
        t = float(p["start"])
        i = next((k for k, c in enumerate(chords) if c["start"] <= t < c["end"]), len(chords) - 1)
        old = chords[i]
        new = {"id": _next_id(chords, "c"), "start": round(t, 3), "end": old["end"], "chord": p["chord"],
               "beats": max(1, int(round(old.get("beats", 1) * (old["end"] - t) / max(old["end"] - old["start"], 1e-3))))}
        old["beats"] = max(1, int(old.get("beats", 1)) - new["beats"])
        old["end"] = round(t, 3)
        chords.insert(i + 1, new)
    elif op == "add_section":
        secs = a.setdefault("sections", [])
        secs.append({"id": _next_id(secs, "s"), "start": round(float(p["start"]), 3),
                     "end": round(float(p["end"]), 3), "label": p["label"]})
        secs.sort(key=lambda s: s["start"])
    elif op == "remove_section":
        a["sections"] = [s for s in a.get("sections", []) if s["id"] != p["id"]]
    elif op == "set_capo":
        a["capo"] = {"fret": p["fret"], "shapes": p.get("shapes") or ""}
    elif op == "set_rhythm":
        a["rhythm"] = {"kind": p["kind"], "pattern": p["pattern"], "note": str(p.get("note", ""))[:120]}
    elif op == "set_line_text":
        from .pipeline.text import units
        ln = _find(a["lyrics"]["lines"], p["line"])[1]
        us = units(p["text"])
        t0, t1 = ln["start"], ln["end"]
        old = [c.get("t") for c in ln["chars"] if c.get("t") is not None]
        if len(old) == len(us):
            times = old
        else:
            times = [t0 + (t1 - t0) * i / max(len(us), 1) for i in range(len(us))]
        ln["chars"] = [{"c": u, "t": round(t, 3), "end": round(times[i + 1] if i + 1 < len(times) else t1, 3)}
                       for i, (u, t) in enumerate(zip(us, times))]
        ln["text"] = p["text"].strip()
    elif op == "shift_line":
        ln = _find(a["lyrics"]["lines"], p["line"])[1]
        d = float(p["delta"])
        for c in ln["chars"]:
            if c.get("t") is not None:
                c["t"] = round(max(0.0, c["t"] + d), 3)
            if c.get("end") is not None:
                c["end"] = round(max(0.0, c["end"] + d), 3)
        ln["start"], ln["end"] = round(max(0.0, ln["start"] + d), 3), round(max(0.0, ln["end"] + d), 3)
    elif op in ("split_line", "merge_lines", "flag_line"):
        lines = a["lyrics"]["lines"]
        i, ln = _find(lines, p["line"])
        if op == "split_line":
            at = p["at"]
            a_chars, b_chars = ln["chars"][:at], ln["chars"][at:]
            nid = _next_id(lines, "l")
            first = dict(ln, chars=a_chars, text="".join(c["c"] for c in a_chars).strip(),
                         end=a_chars[-1].get("end", a_chars[-1].get("t")))
            second = {"id": nid, "chars": b_chars, "text": "".join(c["c"] for c in b_chars).strip(),
                      "start": b_chars[0].get("t", ln["start"]), "end": ln.get("end")}
            lines[i:i + 1] = [first, second]
        elif op == "merge_lines":
            nxt = lines[i + 1]
            sep = [] if _is_cjk(ln["text"]) else [{"c": " ", "t": None, "end": None}]
            merged = dict(ln, chars=ln["chars"] + sep + nxt["chars"], text=(ln["text"] + ("" if sep == [] else " ") + nxt["text"]),
                          end=nxt.get("end"))
            lines[i:i + 2] = [merged]
        else:
            a.setdefault("flags", []).append({"line": p["line"], "issue": str(p["issue"])[:200]})
    return a


def _is_cjk(s: str) -> bool:
    return any(ord(ch) > 0x2E80 for ch in s)


def _collapse(chords: List[dict]) -> None:
    k = 1
    while k < len(chords):
        if chords[k]["chord"] == chords[k - 1]["chord"]:
            chords[k - 1]["end"] = chords[k]["end"]
            chords[k - 1]["beats"] = int(chords[k - 1].get("beats", 0)) + int(chords[k].get("beats", 0))
            del chords[k]
        else:
            k += 1


def replay(base: dict, revisions: List[dict]) -> Tuple[dict, List[dict]]:
    """Apply every revision whose status is applied (or conflict, to retry) in order.

    Returns (analysis, revisions-with-updated-status). A revision that no longer applies —
    e.g. it edits a chord an earlier revision merged away — becomes status 'conflict' with the
    error, and is skipped; it is never silently dropped."""
    a = copy.deepcopy(base)
    out = []
    for r in revisions:
        r = dict(r)
        if r.get("status") in ("applied", "conflict"):
            try:
                a = apply(a, r["patch"], r.get("source", "ai"))
                r["status"] = "applied"
                r.pop("error", None)
            except PatchError as e:
                r["status"] = "conflict"
                r["error"] = str(e)
        out.append(r)
    return a, out


def make_revision(patch: dict, source: str, existing: List[dict], batch: Optional[str] = None) -> dict:
    n = len(existing) + 1
    return {"id": "r%03d" % n, "source": source, "batch": batch, "patch": patch, "reason": patch.get("reason", ""),
            "status": "applied", "ts": int(time.time())}


def add_patches(base: dict, revisions: List[dict], patches: List[dict], source: str,
                batch: Optional[str] = None) -> Tuple[dict, List[dict], List[dict]]:
    """Validate patches one at a time against the current state; keep the valid ones.

    Returns (analysis, revisions, rejected) where rejected = [{"patch", "error"}]."""
    a, revs = replay(base, revisions)
    rejected = []
    for p in patches:
        try:
            a = apply(a, p, source)
        except PatchError as e:
            rejected.append({"patch": p, "error": str(e)})
            continue
        revs.append(make_revision(p, source, revs, batch))
    return a, revs, rejected


def set_status(base: dict, revisions: List[dict], ids: List[str], status: str) -> Tuple[dict, List[dict]]:
    if status not in ("applied", "reverted"):
        raise PatchError("status must be applied or reverted")
    want = set(ids)
    revs = [dict(r, status=status) if r["id"] in want else r for r in revisions]
    return replay(base, revs)


def describe(p: dict, a: dict) -> str:
    """Short human label of a patch (used in logs and evidence; the UI has its own i18n)."""
    op = p.get("op")
    if op in ("respell_chord", "replace_chord", "simplify_chord", "merge_chord", "delete_chord"):
        _, seg = _find(a.get("chords", []), p.get("id"))
        old = seg["chord"] if seg else "?"
        if op == "merge_chord":
            return "%s %s(%s) -> merge %s" % (op, p["id"], old, p.get("into", "prev"))
        return "%s %s: %s -> %s" % (op, p.get("id"), old, p.get("chord"))
    if op == "add_section":
        return "add_section %s %.1f-%.1f" % (p.get("label"), float(p.get("start", 0)), float(p.get("end", 0)))
    if op == "set_capo":
        return "set_capo %s (%s shapes)" % (p.get("fret"), p.get("shapes"))
    if op == "set_rhythm":
        return "set_rhythm %s %s" % (p.get("kind"), p.get("pattern"))
    if op == "set_key":
        return "set_key %s -> %s" % (a.get("key"), p.get("key"))
    return "%s %s" % (op, p.get("line", p.get("id", "")))
