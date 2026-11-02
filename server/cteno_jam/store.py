"""Song library on disk. One directory per song:

    data/songs/<id>/
        meta.json        title, artist, status, stage, progress, error, timings, ai review state
        original.<ext>   the upload (kept so a failed job can be retried)
        lyrics.txt       optional lyrics/LRC the user pasted at upload time
        work/            intermediate WAVs (deleted when the job finishes)
        stems/*.mp3      mono 96 kbps stems for the player (+ mix.mp3)
        base.json        the signal-level analysis (never edited after processing)
        revisions.json   every AI / human patch with reason and status
        song.json        materialised view: base + applied revisions + revision list

Writes go through a temp file + rename so a reader never sees half a file.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import patches as P

_lock = threading.RLock()
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,40}$")
STAGES = ["queued", "decode", "separate", "analyze", "lyrics", "align", "encode", "review", "done"]


class NotFound(KeyError):
    pass


def write_json(path: Path, obj) -> None:
    tmp = path.with_name(".%s.%s.tmp" % (path.name, secrets.token_hex(3)))
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- paths
    def dir(self, sid: str) -> Path:
        if not ID_RE.match(sid or ""):
            raise NotFound(sid)
        d = self.root / sid
        if not (d / "meta.json").exists():
            raise NotFound(sid)
        return d

    def new_id(self) -> str:
        while True:
            sid = secrets.token_hex(5)
            if not (self.root / sid).exists():
                return sid

    # ---------------------------------------------------------------- meta
    def create(self, title: str, artist: str = "", filename: str = "", sid: Optional[str] = None,
               lyrics: str = "", demo: bool = False, lang: str = "") -> Dict:
        with _lock:
            sid = sid or self.new_id()
            d = self.root / sid
            d.mkdir(parents=True, exist_ok=False)
            meta = {"id": sid, "title": title.strip()[:120] or "Untitled", "artist": artist.strip()[:120],
                    "filename": filename[:200], "created": int(time.time()), "updated": int(time.time()),
                    "status": "uploading", "stage": "queued", "progress": 0.0, "error": None, "attempts": 0,
                    "demo": demo, "ai": {"status": "off"}}
            if lang in ("zh", "en"):
                meta["lang"] = lang      # uploader's UI language: AI review writes its reasons in it
            write_json(d / "meta.json", meta)
            if lyrics.strip():
                (d / "lyrics.txt").write_text(lyrics.strip()[:200_000], encoding="utf-8")
            return meta

    def meta(self, sid: str) -> Dict:
        return read_json(self.dir(sid) / "meta.json")

    def update(self, sid: str, **fields) -> Dict:
        with _lock:
            d = self.dir(sid)
            m = read_json(d / "meta.json")
            for k, v in fields.items():
                if k == "ai" and isinstance(v, dict):
                    m["ai"] = {**(m.get("ai") or {}), **v}
                else:
                    m[k] = v
            m["updated"] = int(time.time())
            write_json(d / "meta.json", m)
            if (d / "base.json").exists():
                self._materialise(sid, m)
            return m

    def list(self) -> List[Dict]:
        out = []
        for d in self.root.iterdir():
            m = read_json(d / "meta.json") if d.is_dir() else None
            if m:
                out.append(m)
        return sorted(out, key=lambda m: -m.get("created", 0))

    def delete(self, sid: str) -> None:
        with _lock:
            d = self.dir(sid)
            trash = self.root / (".trash-%s-%s" % (sid, secrets.token_hex(3)))
            os.replace(d, trash)
        shutil.rmtree(trash, ignore_errors=True)

    def original(self, sid: str) -> Optional[Path]:
        for p in self.dir(sid).glob("original.*"):
            return p
        return None

    # ---------------------------------------------------------------- analysis + revisions
    def base(self, sid: str) -> Optional[Dict]:
        return read_json(self.dir(sid) / "base.json")

    def revisions(self, sid: str) -> List[Dict]:
        return read_json(self.dir(sid) / "revisions.json", []) or []

    def set_base(self, sid: str, base: Dict) -> None:
        with _lock:
            d = self.dir(sid)
            write_json(d / "base.json", base)
            write_json(d / "revisions.json", [])
            self._materialise(sid)

    def song(self, sid: str) -> Dict:
        d = self.dir(sid)
        s = read_json(d / "song.json")
        if s is None:
            return {"meta": self.meta(sid), "analysis": None, "revisions": []}
        return s

    def _materialise(self, sid: str, meta: Optional[Dict] = None) -> Dict:
        d = self.dir(sid)
        base = read_json(d / "base.json")
        revs = read_json(d / "revisions.json", []) or []
        analysis, revs = P.replay(base, revs)
        write_json(d / "revisions.json", revs)
        meta = meta or read_json(d / "meta.json")
        analysis["title"], analysis["artist"] = meta.get("title"), meta.get("artist")
        song = {"format": "cteno-jam/song@1", "meta": public_meta(meta), "analysis": analysis, "revisions": revs}
        write_json(d / "song.json", song)
        return song

    def add_patches(self, sid: str, patches: List[Dict], source: str, batch: Optional[str] = None):
        with _lock:
            d = self.dir(sid)
            base = read_json(d / "base.json")
            if base is None:
                raise P.PatchError("the song has not been analysed yet")
            _, revs, rejected = P.add_patches(base, self.revisions(sid), patches, source, batch)
            write_json(d / "revisions.json", revs)
            return self._materialise(sid), rejected

    def set_revision_status(self, sid: str, ids: List[str], status: str) -> Dict:
        with _lock:
            d = self.dir(sid)
            _, revs = P.set_status(read_json(d / "base.json"), self.revisions(sid), ids, status)
            write_json(d / "revisions.json", revs)
            return self._materialise(sid)

    def drop_revisions(self, sid: str, source: str) -> None:
        """Before a new AI review: forget previous AI revisions (keeps human edits)."""
        with _lock:
            d = self.dir(sid)
            revs = [r for r in self.revisions(sid) if r.get("source") != source]
            write_json(d / "revisions.json", revs)
            self._materialise(sid)


def public_meta(m: Dict) -> Dict:
    keep = ("id", "title", "artist", "created", "updated", "status", "stage", "progress", "error", "duration",
            "demo", "ai", "lyrics_source", "attempts", "timings", "stems", "device", "license", "lang")
    return {k: m.get(k) for k in keep if k in m}
