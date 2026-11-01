#!/usr/bin/env python3
"""Run the real processing pipeline on one file without the web server, then score it against
the synthetic ground truth (*.truth.json from make_demo.py).

    python scripts/process_file.py IN.mp3 OUT_DIR [--lyrics IN.lrc] [--truth IN.truth.json] [--title T]
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from cteno_jam import config, store, theory, worker  # noqa: E402


def score(song, truth):
    a = song["analysis"]
    out = {"key_detected": a["key"], "key_truth": truth["key"], "tempo_detected": a["tempo"], "tempo_truth": truth["tempo"]}
    # chord accuracy by time (enharmonic-insensitive; N excluded), over the truth timeline
    step, hit, tot = 0.1, 0, 0
    t = truth["chords"][0]["start"]
    end = truth["chords"][-1]["end"]
    while t < end:
        tc = next((c["chord"] for c in truth["chords"] if c["start"] <= t < c["end"]), None)
        dc = next((c["chord"] for c in a["chords"] if c["start"] <= t < c["end"]), None)
        if tc:
            tot += 1
            pt, pd = theory.parse_chord(tc), theory.parse_chord(dc or "N")
            if pd and pt.root == pd.root and theory.SIMPLE[pt.quality] == theory.SIMPLE[pd.quality]:
                hit += 1
        t += step
    out["chord_accuracy_triad"] = round(hit / max(tot, 1), 3)
    # lyric unit onset error (median, seconds)
    errs = []
    lines = a["lyrics"]["lines"]
    for tl, dl in zip(truth["lines"], lines):
        # truth units are syllables ("Twin", "kle "); the app highlights words: group them
        words, cur = [], None
        for u in tl["units"]:
            if cur is None:
                cur = u["t"]
            if u["u"].endswith(" ") or any(ord(ch) > 0x2E80 for ch in u["u"]):
                words.append(cur); cur = None
        if cur is not None:
            words.append(cur)
        for tw, du in zip(words, dl["chars"]):
            if du.get("t") is not None:
                errs.append(abs(du["t"] - tw))
    errs.sort()
    out["lyric_lines"] = [len(truth["lines"]), len(lines)]
    out["lyric_onset_median_err_s"] = round(errs[len(errs) // 2], 3) if errs else None
    out["lyric_onset_p90_err_s"] = round(errs[int(len(errs) * 0.9)], 3) if errs else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("out")
    ap.add_argument("--lyrics")
    ap.add_argument("--truth")
    ap.add_argument("--title", default="")
    ap.add_argument("--sid", default="")
    ap.add_argument("--review", action="store_true", help="also run the AI review (needs JAM_AI_API_KEY)")
    args = ap.parse_args()
    out = Path(args.out)
    cfg = config.reset(data_dir=out)
    if not args.review:
        cfg.ai_api_key = ""
    st = store.Store(cfg.songs_dir)
    src = Path(args.audio)
    sid = args.sid or src.stem.replace("_", "-").lower()
    if (cfg.songs_dir / sid).exists():
        shutil.rmtree(cfg.songs_dir / sid)
    st.create(args.title or src.stem, "", src.name, sid=sid,
              lyrics=Path(args.lyrics).read_text() if args.lyrics else "")
    shutil.copy(src, st.dir(sid) / ("original" + src.suffix.lower()))
    t = time.time()
    rc = worker.main([sid])
    meta = st.meta(sid)
    print(json.dumps({"rc": rc, "status": meta["status"], "error": meta.get("error"), "device": meta.get("device"),
                      "seconds": round(time.time() - t, 1), "timings": meta.get("timings"), "ai": meta.get("ai", {}).get("status")}))
    if args.truth and meta["status"] == "ready":
        print(json.dumps(score(st.song(sid), json.loads(Path(args.truth).read_text()))))
    return rc


if __name__ == "__main__":
    sys.exit(main())
