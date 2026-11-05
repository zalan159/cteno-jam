"""HTTP API + static web app.

    GET    /api/info                         mode, AI configured?, limits, version
    GET    /api/songs?q=                     library (search by title/artist)
    POST   /api/songs                        multipart: file, title, artist, lyrics  -> queued song
    GET    /api/songs/{id}                   meta (status, stage, progress, error, ai)
    PATCH  /api/songs/{id}                   {"title","artist"} rename
    DELETE /api/songs/{id}
    POST   /api/songs/{id}/retry             re-run a failed job from the original upload
    GET    /api/songs/{id}/song.json         materialised analysis + revisions
    GET    /api/songs/{id}/stems/{name}.mp3  stems (Range supported)
    POST   /api/songs/{id}/edits             {"patches":[...]} human edits (validated like AI patches)
    POST   /api/songs/{id}/revisions         {"ids":[...]|"all", "source":"ai", "status":"applied|reverted"}
    POST   /api/songs/{id}/review            (re)run AI review
    GET    /api/events                       Server-Sent Events: library changes (progress)
    WS     /ws/room/{code}                   sync rooms (see rooms.py)
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config, patches as P, store
from .jobs import JobQueue
from .pipeline import drm
from .pipeline.audio import ALLOWED_EXT
from .rooms import Rooms, new_code

log = logging.getLogger("cteno_jam.app")
STEM_RE = re.compile(r"^(vocals|guitar|piano|bass|drums|other|mix)$")


def create_app(cfg: Optional[config.Config] = None, start_queue: bool = True) -> FastAPI:
    cfg = cfg or config.get()
    cfg.songs_dir.mkdir(parents=True, exist_ok=True)
    st = store.Store(cfg.songs_dir)
    jobs = JobQueue(st, cfg)
    rooms = Rooms()
    app = FastAPI(title="Cteno Jam", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.store, app.state.jobs, app.state.rooms, app.state.cfg = st, jobs, rooms, cfg

    @app.on_event("startup")
    async def _startup():
        if start_queue and cfg.processing:
            jobs.start()

    def guard(key: Optional[str]):
        if cfg.admin_key and key != cfg.admin_key:
            raise HTTPException(401, "this server needs the upload passphrase (JAM_ADMIN_KEY)")

    hits: dict = {}  # client ip -> [upload timestamps], for JAM_UPLOADS_PER_IP_HOUR

    def client_ip(request: Request) -> str:
        # Behind Caddy/frp the TCP peer is the proxy; the real client is the first X-Forwarded-For entry.
        xff = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        return xff or (request.client.host if request.client else "?")

    def is_private(ip: str) -> bool:
        try:
            a = ipaddress.ip_address(ip)
            return a.is_private or a.is_loopback or a.is_link_local
        except ValueError:
            return False

    def upload_guards(request: Request):
        """Raise 429/507 when an upload should be refused (queue full, rate limit, disk almost full)."""
        if cfg.max_disk_percent:
            du = shutil.disk_usage(cfg.data_dir)
            if du.used * 100 > du.total * cfg.max_disk_percent:
                raise HTTPException(507, "磁盘空间不足，暂时无法上传 (disk is more than %d%% full)" % cfg.max_disk_percent)
        if cfg.max_queue:
            busy = sum(1 for m in st.list() if m.get("status") in ("queued", "processing"))
            if busy >= cfg.max_queue:
                raise HTTPException(429, "队列已满，稍后再试 (queue is full: %d songs)" % cfg.max_queue)
        if cfg.uploads_per_ip_hour:
            ip = client_ip(request)
            if cfg.rate_limit_private or not is_private(ip):
                now = time.time()
                recent = [t for t in hits.get(ip, []) if now - t < 3600]
                if len(recent) >= cfg.uploads_per_ip_hour:
                    hits[ip] = recent
                    raise HTTPException(429, "上传太频繁，每小时最多 %d 首，稍后再试 (rate limit)" % cfg.uploads_per_ip_hour)
                recent.append(now)
                hits[ip] = recent

    def refund(request: Request):
        """A refused upload should not count against the uploader's hourly limit."""
        recent = hits.get(client_ip(request))
        if recent:
            recent.pop()

    def meta_or_404(sid: str):
        try:
            return st.meta(sid)
        except store.NotFound:
            raise HTTPException(404, "no such song")

    @app.get("/api/info")
    def info():
        return {"name": "Cteno Jam", "version": __version__, "mode": cfg.mode, "upload": cfg.processing,
                "needs_key": bool(cfg.admin_key), "public_url": cfg.public_url, "max_upload_mb": cfg.max_upload_mb,
                "max_duration_s": cfg.max_duration_s, "formats": sorted(ALLOWED_EXT),
                "encrypted_ext": drm.ENCRYPTED_EXT,
                "ai": {"configured": cfg.ai_configured, "model": cfg.ai_model if cfg.ai_configured else None},
                "room": new_code()}

    @app.get("/api/songs")
    def list_songs(q: str = ""):
        q = q.strip().lower()
        out = [store.public_meta(m) for m in st.list()]
        if q:
            out = [m for m in out if q in (m.get("title") or "").lower() or q in (m.get("artist") or "").lower()]
        for m in out:
            if m["status"] == "queued":
                m["queue_position"] = jobs.position(m["id"])
        return {"songs": out}

    @app.post("/api/songs", status_code=201)
    async def upload(request: Request, file: UploadFile = File(...), title: str = Form(""), artist: str = Form(""),
                     lyrics: str = Form(""), lang: str = Form(""), x_jam_key: Optional[str] = Header(None),
                     key: Optional[str] = Query(None)):
        guard(x_jam_key or key)
        if not cfg.processing:
            raise HTTPException(403, "this server is player-only (JAM_MODE=player); uploads are disabled")
        name = os.path.basename(file.filename or "upload")
        ext = os.path.splitext(name)[1].lower()
        from .review import norm_lang
        fam = drm.family_from_name(ext)  # a .mgg2/.ncm/... ending; "x.mgg2.flac" is judged by its content below
        if fam:
            raise HTTPException(415, drm.message(fam, norm_lang(lang)))
        if ext not in ALLOWED_EXT:
            raise HTTPException(415, "unsupported file type '%s'; use mp3, m4a, wav or flac" % (ext or "?"))
        upload_guards(request)
        title = title.strip() or os.path.splitext(name)[0]
        m = st.create(title, artist, name, lyrics=lyrics, lang=norm_lang(lang) or "")
        dest = st.dir(m["id"]) / ("original" + ext)
        limit = cfg.max_upload_mb * 1024 * 1024
        size = 0
        try:
            with open(dest, "wb") as f:
                while True:
                    chunk = await file.read(1 << 20)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, "file larger than %d MB" % cfg.max_upload_mb)
                    f.write(chunk)
        except HTTPException:
            st.delete(m["id"])
            raise
        if size == 0:
            st.delete(m["id"])
            raise HTTPException(400, "empty file")
        fam = drm.sniff(dest, name)
        if fam:  # encrypted music-app download renamed to .mp3/.flac: refuse it now, not after queueing
            st.delete(m["id"])
            refund(request)
            raise HTTPException(415, drm.message(fam, norm_lang(lang)))
        st.update(m["id"], size=size)
        pos = jobs.submit(m["id"])
        return {**store.public_meta(st.meta(m["id"])), "queue_position": pos}

    @app.get("/api/songs/{sid}")
    def get_song_meta(sid: str):
        m = store.public_meta(meta_or_404(sid))
        if m["status"] == "queued":
            m["queue_position"] = jobs.position(sid)
        return m

    @app.patch("/api/songs/{sid}")
    async def rename(sid: str, request: Request, x_jam_key: Optional[str] = Header(None)):
        guard(x_jam_key)
        meta_or_404(sid)
        body = await request.json()
        fields = {k: str(body[k]).strip()[:120] for k in ("title", "artist") if k in body}
        if "title" in fields and not fields["title"]:
            raise HTTPException(400, "title cannot be empty")
        return store.public_meta(st.update(sid, **fields))

    @app.delete("/api/songs/{sid}", status_code=204)
    def delete(sid: str, x_jam_key: Optional[str] = Header(None)):
        guard(x_jam_key)
        m = meta_or_404(sid)
        if m.get("demo") and os.environ.get("JAM_PROTECT_DEMO", "1") == "1":
            raise HTTPException(403, "the bundled demo song cannot be deleted")
        jobs.cancel(sid)
        st.delete(sid)

    @app.post("/api/songs/{sid}/retry")
    def retry(sid: str, x_jam_key: Optional[str] = Header(None)):
        guard(x_jam_key)
        m = meta_or_404(sid)
        if m["status"] in ("queued", "processing"):
            raise HTTPException(409, "the song is already being processed")
        if st.original(sid) is None:
            raise HTTPException(409, "the original upload is gone; upload the file again")
        return {"queue_position": jobs.submit(sid)}

    @app.get("/api/songs/{sid}/song.json")
    def song_json(sid: str):
        meta_or_404(sid)
        return JSONResponse(st.song(sid), headers={"Cache-Control": "no-cache"})

    @app.get("/api/songs/{sid}/stems/{name}.mp3")
    def stem(sid: str, name: str):
        if not STEM_RE.match(name):
            raise HTTPException(404)
        meta_or_404(sid)
        p = st.dir(sid) / "stems" / ("%s.mp3" % name)
        if not p.exists():
            raise HTTPException(404, "stem not ready")
        return FileResponse(p, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=86400"})

    @app.post("/api/songs/{sid}/edits")
    async def edits(sid: str, request: Request, x_jam_key: Optional[str] = Header(None)):
        guard(x_jam_key)
        meta_or_404(sid)
        body = await request.json()
        ps = body.get("patches")
        if not isinstance(ps, list) or not ps or len(ps) > 200:
            raise HTTPException(400, "send 1-200 patches")
        for p in ps:
            if isinstance(p, dict) and not p.get("reason"):
                p["reason"] = "manual edit"
        try:
            song, rejected = st.add_patches(sid, ps, "user")
        except P.PatchError as e:
            raise HTTPException(409, str(e))
        if rejected and len(rejected) == len(ps):
            return JSONResponse({"error": rejected[0]["error"], "rejected": rejected, "song": song}, status_code=422)
        return {"song": song, "rejected": rejected}

    @app.post("/api/songs/{sid}/revisions")
    async def revisions(sid: str, request: Request, x_jam_key: Optional[str] = Header(None)):
        guard(x_jam_key)
        meta_or_404(sid)
        body = await request.json()
        status = body.get("status")
        ids = body.get("ids")
        if ids == "all":
            src = body.get("source")
            ids = [r["id"] for r in st.revisions(sid) if src is None or r.get("source") == src]
        if not isinstance(ids, list):
            raise HTTPException(400, "ids must be a list or 'all'")
        try:
            return {"song": st.set_revision_status(sid, [str(i) for i in ids], status)}
        except P.PatchError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/songs/{sid}/review")
    def review(sid: str, x_jam_key: Optional[str] = Header(None), lang: Optional[str] = Query(None)):
        guard(x_jam_key)
        m = meta_or_404(sid)
        from .review import norm_lang
        if norm_lang(lang):                 # re-run in the language the user is looking at now
            st.update(sid, lang=norm_lang(lang))
        if not cfg.ai_configured:
            raise HTTPException(409, "AI review is not configured: set JAM_AI_API_KEY (or DEEPSEEK_API_KEY)")
        if m["status"] != "ready":
            raise HTTPException(409, "the song is not ready yet")
        return {"queue_position": jobs.submit(sid, "review")}

    @app.get("/api/events")
    async def events(request: Request):
        """Library snapshot every second while something changes (cheap: a directory scan)."""
        async def gen():
            last = None
            idle = 0
            while not await request.is_disconnected():
                snap = [(m["id"], m.get("updated"), m.get("status"), m.get("progress"), (m.get("ai") or {}).get("status"),
                         jobs.position(m["id"]) if m.get("status") == "queued" else 0) for m in st.list()]
                if snap != last:
                    last = snap
                    songs = [store.public_meta(m) for m in st.list()]
                    for m in songs:
                        if m["status"] == "queued":
                            m["queue_position"] = jobs.position(m["id"])
                    yield "data: %s\n\n" % json.dumps({"songs": songs}, ensure_ascii=False)
                    idle = 0
                else:
                    idle += 1
                    if idle % 15 == 0:
                        yield ": keepalive\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.websocket("/ws/room/{code}")
    async def ws_room(ws: WebSocket, code: str):
        if not re.match(r"^[a-z0-9]{4,12}$", code):
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            await rooms.handle(ws, code)
        except OverflowError:
            await ws.close(code=1013)

    # static web app last, so /api wins. Revalidate on every load (ETag/Last-Modified make
    # that a cheap 304) so an upgraded server never runs with a stale cached module.
    @app.middleware("http")
    async def _no_stale_assets(request: Request, call_next):
        resp = await call_next(request)
        if not request.url.path.startswith("/api/") and "cache-control" not in resp.headers:
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    if cfg.web_dir.exists():
        app.mount("/", StaticFiles(directory=str(cfg.web_dir), html=True), name="web")
    return app


def main():
    import uvicorn
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = config.get()
    from .seed import seed_demo
    seed_demo(cfg)
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, proxy_headers=True, forwarded_allow_ips="*",
                ws_ping_interval=20)


if __name__ == "__main__":
    main()
