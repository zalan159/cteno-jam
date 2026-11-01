"""Seed the library with the bundled CC0 demo songs (already processed, under demo/songs/)."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from . import config, store

log = logging.getLogger("cteno_jam.seed")
def _default_demo_dir() -> Path:
    import os
    env = os.environ.get("JAM_DEMO_DIR")
    if env:
        return Path(env)
    # source checkout: <repo>/server/cteno_jam/seed.py -> <repo>/demo/songs
    return Path(__file__).resolve().parents[2] / "demo" / "songs"


DEMO_DIR = _default_demo_dir()


def seed_demo(cfg: config.Config, demo_dir: Path = DEMO_DIR) -> int:
    import os
    if os.environ.get("JAM_SEED_DEMO", "1") != "1" or not demo_dir.exists():
        return 0
    st = store.Store(cfg.songs_dir)
    n = 0
    for src in sorted(demo_dir.iterdir()):
        song = store.read_json(src / "song.json")
        if not song:
            continue
        sid = "demo-" + src.name
        if (cfg.songs_dir / sid).exists():
            continue
        meta = song["meta"]
        m = st.create(meta.get("title") or src.name, meta.get("artist", ""), sid=sid, demo=True)
        d = st.dir(sid)
        shutil.copytree(src / "stems", d / "stems")
        base = store.read_json(src / "base.json")
        st.set_base(sid, base)
        revs = song.get("revisions") or []
        if revs:
            store.write_json(d / "revisions.json", revs)
        st.update(sid, status="ready", stage="done", progress=1.0, duration=base.get("duration"),
                  stems=sorted(p.stem for p in (d / "stems").glob("*.mp3") if p.stem != "mix"),
                  lyrics_source=(base.get("lyrics") or {}).get("source"), ai=meta.get("ai") or {"status": "off"},
                  license=meta.get("license"), timings=meta.get("timings"), device=meta.get("device"))
        n += 1
        log.info("seeded demo song %s", sid)
    return n
