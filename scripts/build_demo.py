#!/usr/bin/env python3
"""Package processed songs as bundled demo songs (demo/songs/<slug>/), and build the static
player (dist/static/) that needs no backend.

    python scripts/build_demo.py pack DATA_DIR slug [slug...]   # data/songs/<slug> -> demo/songs/<slug>
    python scripts/build_demo.py static OUT_DIR [--sync-url wss://...]
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CREDITS = {
    "twinkle": "Melody: 'Ah! vous dirai-je, maman' (French folk tune, 1761). Lyrics: Jane Taylor, 'The Star' (1806). "
               "Public domain. Arrangement, synthesis and stems: Cteno Jam contributors, CC0 1.0.",
    "frere-jacques": "Traditional French nursery round (18th century). Public domain. "
                     "Arrangement, synthesis and stems: Cteno Jam contributors, CC0 1.0.",
}


def pack(data, slugs):
    for slug in slugs:
        src = Path(data) / "songs" / slug
        dst = ROOT / "demo" / "songs" / slug
        shutil.rmtree(dst, ignore_errors=True)
        (dst / "stems").mkdir(parents=True)
        for p in (src / "stems").glob("*.mp3"):
            if p.stem != "mix":
                shutil.copy(p, dst / "stems" / p.name)
        shutil.copy(src / "base.json", dst / "base.json")
        song = json.loads((src / "song.json").read_text())
        meta = json.loads((src / "meta.json").read_text())
        song["meta"] = {k: meta.get(k) for k in ("title", "artist", "duration", "stems", "timings", "device", "lyrics_source")}
        song["meta"]["artist"] = song["meta"].get("artist") or "Traditional"
        song["meta"]["license"] = "CC0-1.0"
        song["meta"]["credits"] = CREDITS.get(slug, "")
        ai = meta.get("ai") or {}
        song["meta"]["ai"] = {k: ai.get(k) for k in ("status", "summary", "model", "accepted", "rejected", "seconds") if k in ai}
        song["analysis"]["artist"] = song["meta"]["artist"]
        (dst / "song.json").write_text(json.dumps(song, ensure_ascii=False, indent=1))
        print("packed", slug, sum(p.stat().st_size for p in dst.rglob("*")) // 1024, "KB")


def static(out, sync_url=""):
    out = Path(out)
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(ROOT / "web", out, ignore=shutil.ignore_patterns("test"))
    songs = []
    for d in sorted((ROOT / "demo" / "songs").iterdir()):
        song = json.loads((d / "song.json").read_text())
        sid = "demo-" + d.name
        shutil.copytree(d, out / "demo" / sid)
        m = song["meta"]
        songs.append({"id": sid, "title": m["title"], "artist": m.get("artist"), "duration": m.get("duration"),
                      "status": "ready", "demo": True, "ai": m.get("ai"), "stems": m.get("stems"), "license": "CC0-1.0"})
    (out / "demo" / "index.json").write_text(json.dumps({"songs": songs}, ensure_ascii=False, indent=1))
    cfg = {"static": True, "base": "demo/"}
    if sync_url:
        cfg["syncUrl"] = sync_url
    (out / "config.js").write_text("window.JAM_CONFIG = %s;\n" % json.dumps(cfg))
    print("static site in", out, len(songs), "songs")


if __name__ == "__main__":
    if sys.argv[1] == "pack":
        pack(sys.argv[2], sys.argv[3:])
    elif sys.argv[1] == "static":
        su = sys.argv[sys.argv.index("--sync-url") + 1] if "--sync-url" in sys.argv else ""
        static(sys.argv[2], su)
