"""AI review of the signal-level analysis, driven by the Cteno Agent SDK (cteno-sdk).

What the model can and cannot do
--------------------------------
The model never hears the audio. It only sees the numbers the DSP pipeline produced
(key, tempo, beat-synchronous chord segments, lyric line timings) through read-only client
tools, and it answers with a list of typed patches. Every patch is validated here
(`patches.validate`) against the state it applies to; invalid ones are rejected and recorded,
valid ones are stored as revisions with the model's one-sentence reason. Nothing the model
says can rewrite song.json directly, and every applied patch can be undone.

Flow (one SDK session per review):
    get_overview / get_chords / get_lyrics   -> read the analysis
    check_patches(patches)                   -> dry-run validation, so the model can fix mistakes
    final_result {summary, patches}          -> outputSchema; the server validates + applies
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
from collections import Counter
from typing import Any, Callable, Dict, List, Optional

from . import patches as P
from . import theory

log = logging.getLogger("cteno_jam.review")

SYSTEM_PROMPT = """You are the proofreader of an automatic guitar chord chart ("Cteno Jam").
A signal-processing pipeline (Demucs stem separation, beat tracking, chroma template matching,
lyric alignment) already analysed a recording. You CANNOT hear the audio. You only see the
analysis numbers through tools, so you reason about consistency, music theory and readability.
Never invent chords the data does not support; when unsure, leave it alone.

Your jobs, in this order:
1. Key and spelling: check the detected key against the chord histogram (set_key only when the
   chords clearly contradict it). Then respell chords enharmonically to fit the key
   (respell_chord), e.g. in E major write G#m not Abm, C#m not Dbm; in F major write Bb not A#.
2. Blips: a chord lasting 1 beat (sometimes 2) between two longer chords is usually a
   misdetection. Merge it into the neighbour it most likely belongs to (merge_chord, into
   prev|next). Do not merge chords that repeat as part of a pattern.
3. Sections: label the form with add_section (intro, verse, prechorus, chorus, bridge,
   interlude, solo, outro) using chord-pattern repetition, lyric lines and repeated lyric text.
   Sections must not overlap. Cover the sung parts at least.
4. Beginners and kids: set_capo with the fret and open-chord shape family that makes the song
   easiest (e.g. key E -> capo 4, C shapes; key F -> capo 1, E shapes or capo 5 C shapes);
   simplify_chord for hard chords (keep the root, plain triad: F#m7 -> F#m, Bsus4 -> B, B/D# -> B).
5. Rhythm: set_rhythm once: a strum pattern for 4/4 like "D-DU-UDU" (D down, U up, - rest,
   eight slots per bar) or kind arpeggio like "p-i-m-a-m-i-" for slow songs, with a short note.
6. Lyrics: look for obvious line-break problems (one line that is far too long or two halves of a
   sentence split across lines) and fix them with split_line (character index) or merge_lines;
   flag_line for timing that looks wrong (units squeezed into <0.05 s, or a line sung over a long
   instrumental gap). Do not rewrite lyric text.

Every patch needs a short, specific "reason" (one sentence, in the language of the lyrics if the
lyrics are Chinese, otherwise English) that a musician can verify, citing ids, beats or times.
Use check_patches before you finish and fix rejected patches. Prefer fewer, high-confidence
patches over many guesses. Finish by returning final_result with a one-paragraph summary and
the final list of patches (only ones check_patches accepted)."""

PATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": list(P.AI_OPS)},
        "id": {"type": "string", "description": "chord segment id (c###) for chord ops"},
        "chord": {"type": "string", "description": "new chord symbol, e.g. G#m, F#m7, B/D#"},
        "into": {"type": "string", "enum": ["prev", "next"]},
        "key": {"type": "string", "description": "for set_key, e.g. 'E major'"},
        "start": {"type": "number"}, "end": {"type": "number"},
        "label": {"type": "string", "enum": list(P.SECTION_LABELS)},
        "fret": {"type": "integer"}, "shapes": {"type": "string", "description": "open shape key, e.g. C, G, D, A, E, Am, Em"},
        "kind": {"type": "string", "enum": list(P.RHYTHM_KINDS)},
        "pattern": {"type": "string"}, "note": {"type": "string"},
        "line": {"type": "string", "description": "lyric line id (l###)"},
        "at": {"type": "integer", "description": "split_line: unit index where the new line starts"},
        "issue": {"type": "string"},
        "reason": {"type": "string", "description": "one sentence: why"},
    },
    "required": ["op", "reason"],
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}, "patches": {"type": "array", "items": PATCH_SCHEMA}},
    "required": ["summary", "patches"],
}


# ------------------------------------------------------------------ read tools (pure)
def overview(a: Dict) -> Dict:
    key = theory.parse_key(a.get("key", ""))
    chords = a.get("chords", [])
    hist = Counter()
    for c in chords:
        hist[c["chord"]] += int(c.get("beats", 1))
    beats_hist = Counter(min(int(c.get("beats", 1)), 9) for c in chords)
    lines = (a.get("lyrics") or {}).get("lines", [])
    return {
        "key": a.get("key"), "tempo_bpm": a.get("tempo"), "meter": a.get("meter", 4), "duration_s": a.get("duration"),
        "chord_segments": len(chords), "lyric_lines": len(lines),
        "lyrics_source": (a.get("lyrics") or {}).get("source"),
        "chord_beats_histogram": dict(hist.most_common(24)),
        "segments_by_length_beats": {("%d" % k if k < 9 else "9+"): v for k, v in sorted(beats_hist.items())},
        "out_of_key_chords": sorted({c["chord"] for c in chords if key and c["chord"] != "N" and not theory.chord_in_key(c["chord"], key)}),
        "sections": a.get("sections", []), "capo": a.get("capo"), "rhythm": a.get("rhythm"),
        "suggested_capo_by_rule": dict(zip(("fret", "easy_share"), theory.best_capo([(c["chord"], c["end"] - c["start"]) for c in chords]))),
    }


def chord_page(a: Dict, offset: int = 0, limit: int = 80) -> Dict:
    chords = a.get("chords", [])
    lines = (a.get("lyrics") or {}).get("lines", [])
    page = []
    for c in chords[offset:offset + limit]:
        ln = next((l for l in lines if l["start"] - 0.3 <= c["start"] < l["end"]), None)
        page.append({"id": c["id"], "start": round(c["start"], 2), "end": round(c["end"], 2), "beats": c.get("beats"),
                     "chord": c["chord"], "line": ln["id"] if ln else None})
    return {"total": len(chords), "offset": offset, "chords": page, "has_more": offset + limit < len(chords)}


def lyric_page(a: Dict, offset: int = 0, limit: int = 60) -> Dict:
    lines = (a.get("lyrics") or {}).get("lines", [])
    out = []
    for ln in lines[offset:offset + limit]:
        cs = ln["chars"]
        durs = [max(0.0, (c.get("end") or c["t"]) - c["t"]) for c in cs if c.get("t") is not None]
        out.append({"id": ln["id"], "start": round(ln["start"], 2), "end": round(ln["end"], 2), "text": ln["text"],
                    "units": len(cs), "min_unit_s": round(min(durs), 3) if durs else None,
                    "unit_texts": [c["c"] for c in cs] if len(cs) <= 40 else None})
    return {"total": len(lines), "offset": offset, "lines": out, "has_more": offset + limit < len(lines)}


# ------------------------------------------------------------------ the agent
class ReviewResult:
    def __init__(self, ok: bool, summary: str = "", accepted: Optional[List[Dict]] = None,
                 rejected: Optional[List[Dict]] = None, error: Optional[str] = None,
                 tool_calls: Optional[List[str]] = None, seconds: float = 0.0, model: str = ""):
        self.ok, self.summary, self.error = ok, summary, error
        self.accepted, self.rejected = accepted or [], rejected or []
        self.tool_calls, self.seconds, self.model = tool_calls or [], seconds, model

    def to_dict(self) -> Dict:
        return {"ok": self.ok, "summary": self.summary, "accepted": len(self.accepted), "rejected": self.rejected,
                "error": self.error, "tool_calls": self.tool_calls, "seconds": round(self.seconds, 1), "model": self.model}


def build_tools(get_state: Callable[[], Dict], calls: List[str]):
    """Client tools exposed to the model. They only read, or dry-run validate."""
    from cteno_sdk import ClientTool

    async def t_overview(args, ctx):
        calls.append("get_overview")
        return overview(get_state())

    async def t_chords(args, ctx):
        calls.append("get_chords")
        return chord_page(get_state(), int(args.get("offset") or 0), min(int(args.get("limit") or 80), 120))

    async def t_lyrics(args, ctx):
        calls.append("get_lyrics")
        return lyric_page(get_state(), int(args.get("offset") or 0), min(int(args.get("limit") or 60), 100))

    async def t_check(args, ctx):
        calls.append("check_patches")
        return dry_run(get_state(), args.get("patches") or [])

    page = {"type": "object", "properties": {"offset": {"type": "integer"}, "limit": {"type": "integer"}}}
    return [
        ClientTool("get_overview", "Key, tempo, duration, chord histogram (beats per chord), out-of-key chords, "
                   "segment-length histogram, sections, capo, rhythm.", {"type": "object", "properties": {}}, handler=t_overview),
        ClientTool("get_chords", "Chord segments in time order: id, start/end seconds, beats, chord, lyric line id. Paged.",
                   page, handler=t_chords),
        ClientTool("get_lyrics", "Lyric lines: id, start/end, text, number of units, shortest unit duration. Paged.",
                   page, handler=t_lyrics),
        ClientTool("check_patches", "Dry-run: validate a list of patches in order against the analysis WITHOUT saving. "
                   "Returns accepted and rejected (with the error).",
                   {"type": "object", "properties": {"patches": {"type": "array", "items": PATCH_SCHEMA}}, "required": ["patches"]},
                   handler=t_check),
    ]


def dry_run(state: Dict, patches: List[Dict]) -> Dict:
    a = copy.deepcopy(state)
    acc, rej = [], []
    for i, p in enumerate(patches):
        try:
            a = P.apply(a, p, "ai")
            acc.append({"index": i, "op": p.get("op"), "what": P.describe(p, state)})
        except P.PatchError as e:
            rej.append({"index": i, "op": p.get("op") if isinstance(p, dict) else None, "error": str(e)})
    return {"accepted": acc, "rejected": rej}


def user_prompt(a: Dict) -> str:
    lang = "Chinese" if any(P._is_cjk(l["text"]) for l in (a.get("lyrics") or {}).get("lines", [])[:20]) else "English"
    return ("Proofread this analysis. Start with get_overview, read every chord page and the lyrics, "
            "then check_patches, then final_result. Lyrics language: %s. Title: %s." % (lang, a.get("title") or "(untitled)"))


async def run_review(state: Dict, *, base_url: str, model: str, api_key: str, api_format: str = "openai",
                     timeout_s: int = 300, sdk_home: Optional[str] = None, profile_id: str = "cteno-jam-review") -> ReviewResult:
    """One review session. Returns validated patches; does not save anything."""
    from cteno_sdk import AGENT_SPEC_CAPABILITY, AgentSpec, CtenoSession

    t0 = time.time()
    calls: List[str] = []
    snapshot = copy.deepcopy(state)
    async with await CtenoSession.open(home=sdk_home or None) as cteno:
        if AGENT_SPEC_CAPABILITY not in await cteno.capabilities():
            return ReviewResult(False, error="Cteno daemon lacks %s" % AGENT_SPEC_CAPABILITY)
        pid = await cteno.configure_model(base_url=base_url, model=model, api_key=api_key, api_format=api_format,
                                          id=profile_id, name="Cteno Jam review", make_default=False)
        sid = await cteno.create(model=pid, title="cteno-jam review", spec=AgentSpec(
            system_prompt=SYSTEM_PROMPT,
            context={"datetime": False},
            tools={"allow": []},  # no Cteno built-ins: the model can only use our tools
            client_tools=build_tools(lambda: snapshot, calls),
            output_schema=OUTPUT_SCHEMA,
            limits={"maxIterations": 24, "maxToolCalls": 30, "turnTimeoutMs": timeout_s * 1000, "maxOutputTokens": 8192},
            metadata={"app": "cteno-jam"},
        ))
        try:
            r = await cteno.run(sid, user_prompt(snapshot), timeout=timeout_s + 30)
        finally:
            await cteno.close_session(sid)
    secs = time.time() - t0
    if not r.ok:
        return ReviewResult(False, error="%s: %s" % (r.error_kind or "error", (r.error or "")[:500]),
                            tool_calls=calls, seconds=secs, model=model)
    out = r.output if isinstance(r.output, dict) else None
    if out is None:
        try:
            out = json.loads(r.text)
        except (ValueError, TypeError):
            return ReviewResult(False, error="model did not return the structured result", tool_calls=calls,
                                seconds=secs, model=model)
    patches = out.get("patches") if isinstance(out.get("patches"), list) else []
    res = dry_run(snapshot, patches)
    acc_idx = {x["index"] for x in res["accepted"]}
    return ReviewResult(True, summary=str(out.get("summary", ""))[:2000],
                        accepted=[patches[i] for i in sorted(acc_idx)],
                        rejected=[dict(x, patch=patches[x["index"]] if x["index"] < len(patches) else None) for x in res["rejected"]],
                        tool_calls=calls, seconds=secs, model=model)


def run_review_sync(state: Dict, **kw) -> ReviewResult:
    return asyncio.run(run_review(state, **kw))
