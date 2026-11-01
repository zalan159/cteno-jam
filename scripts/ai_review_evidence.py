#!/usr/bin/env python3
"""AI review evidence: run the review on an analysed song and write a before/after report.

    JAM_AI_API_KEY=... python scripts/ai_review_evidence.py DATA_DIR SONG_ID OUT_DIR

Writes OUT_DIR/<id>-before.json (base analysis), <id>-after.json (with AI revisions applied),
<id>-ai-diff.md (unified diff of the chord chart + every revision with its reason, plus the
patches the checker rejected) and <id>-ai-result.json. The key is read from the environment
and never written anywhere.
"""
import difflib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from cteno_jam import config, patches as P, review_job, store  # noqa: E402


def chart_lines(an):
    out = ["key: %s  tempo: %s" % (an.get("key"), an.get("tempo"))]
    if an.get("capo"):
        out.append("capo: %s" % json.dumps(an["capo"], ensure_ascii=False))
    if an.get("rhythm"):
        out.append("rhythm: %s %s" % (an["rhythm"]["kind"], an["rhythm"]["pattern"]))
    for s in an.get("sections", []):
        out.append("section %-10s %6.2f-%6.2f" % (s["label"], s["start"], s["end"]))
    for c in an.get("chords", []):
        simple = (an.get("simplified") or {}).get(c["id"])
        out.append("%s %6.2f-%6.2f %2s beats  %-6s%s" % (c["id"], c["start"], c["end"], c.get("beats"), c["chord"],
                                                        "  (easy: %s)" % simple if simple else ""))
    for ln in (an.get("lyrics") or {}).get("lines", []):
        out.append("%s %6.2f  %s" % (ln["id"], ln["start"], ln["text"]))
    for f in an.get("flags", []):
        out.append("flag %s: %s" % (f["line"], f["issue"]))
    return out


def main():
    data, sid, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    cfg = config.reset(data_dir=data)
    if not cfg.ai_configured:
        sys.exit("JAM_AI_API_KEY (or DEEPSEEK_API_KEY) is not set")
    st = store.Store(cfg.songs_dir)
    base = st.base(sid)
    t = time.time()
    res = review_job.review(st, sid, cfg)
    song = st.song(sid)
    after = song["analysis"]
    meta = st.meta(sid)
    (out / ("%s-before.json" % sid)).write_text(json.dumps(base, ensure_ascii=False, indent=1))
    (out / ("%s-after.json" % sid)).write_text(json.dumps(after, ensure_ascii=False, indent=1))
    ai = meta.get("ai") or {}
    result = {"model": ai.get("model"), "status": ai.get("status"), "seconds": round(time.time() - t, 1),
              "accepted": ai.get("accepted"), "rejected": ai.get("rejected"), "tool_calls": ai.get("tool_calls"),
              "summary": ai.get("summary"), "error": ai.get("error")}
    (out / ("%s-ai-result.json" % sid)).write_text(json.dumps(result, ensure_ascii=False, indent=1))
    md = ["# AI review of `%s` (%s)" % (after.get("title"), sid), "",
          "- model: `%s` via Cteno Agent SDK (cteno-sdk), status **%s**, %s s" % (result["model"], result["status"], result["seconds"]),
          "- client tool calls: %s" % ", ".join(result["tool_calls"] or []),
          "- accepted patches: %s, rejected by the server-side checker: %d" % (result["accepted"], len(result["rejected"] or [])),
          "", "> The model cannot hear the audio. It only read the analysis through tools and proposed patches; "
          "every patch was validated before it was applied.", "",
          "## Summary from the model", "", result["summary"] or "(none)", "",
          "## Revisions (each with its reason)", ""]
    for r in song["revisions"]:
        if r["source"] != "ai":
            continue
        md.append("- `%s` **%s** — %s  _(status: %s)_" % (r["id"], P.describe(r["patch"], base), r["reason"], r["status"]))
    md += ["", "## Rejected by the checker", ""]
    for x in result["rejected"] or []:
        md.append("- `%s` — %s" % (json.dumps(x.get("patch"), ensure_ascii=False), x.get("error")))
    if not result["rejected"]:
        md.append("(none)")
    md += ["", "## Chart diff (before → after)", "", "```diff"]
    md += list(difflib.unified_diff(chart_lines(base), chart_lines(after), "before", "after", lineterm="", n=1))
    md += ["```", ""]
    (out / ("%s-ai-diff.md" % sid)).write_text("\n".join(md))
    print(json.dumps({k: result[k] for k in ("model", "status", "seconds", "accepted", "error")}, ensure_ascii=False))
    print("rejected:", len(result["rejected"] or []))
    return 0 if result["status"] == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
