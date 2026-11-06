"""Phone audio sources: in-browser recordings / picker files without an extension, and the optional
Jamendo free catalogue (search, preview proxy, import with license) against a fake Jamendo API."""
import io
import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from cteno_jam import app as appmod, config
from cteno_jam.pipeline import audio

from test_api import wait_status

HERE = Path(__file__).resolve().parent
CLIENT_ID = "test-client-id-123"
MP3 = b"ID3\x04\x00" + b"\x00" * 2048

TRACKS = [
    {"id": "1001", "name": "Open Road", "artist_name": "Free Band", "album_name": "Roads", "duration": 185,
     "image": "", "shareurl": "https://www.jamendo.com/track/1001", "audiodownload_allowed": True,
     "license_ccurl": "http://creativecommons.org/licenses/by-sa/3.0/"},
    {"id": "1002", "name": "Locked Song", "artist_name": "Closed Band", "album_name": "", "duration": 200,
     "image": "", "shareurl": "https://www.jamendo.com/track/1002", "audiodownload_allowed": False,
     "license_ccurl": "http://creativecommons.org/licenses/by-nc-nd/3.0/"},
]


class FakeJamendo(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        FakeJamendo.seen.append((u.path, q, self.headers.get("Range")))
        base = "http://127.0.0.1:%d" % self.server.server_address[1]
        if u.path == "/v3.0/tracks/":
            if q.get("client_id") != CLIENT_ID:
                return self.reply(200, {"headers": {"status": "failed", "error_message": "invalid client id"}, "results": []})
            rows = [t for t in TRACKS if not q.get("id") or t["id"] == q["id"]]
            if q.get("search"):
                rows = [t for t in rows if q["search"].lower() in (t["name"] + t["artist_name"]).lower()]
            res = []
            for t in rows:
                r = dict(t, audio="%s/stream/%s.mp3?client_id=%s" % (base, t["id"], CLIENT_ID))
                r["audiodownload"] = "%s/dl/%s.mp3?client_id=%s" % (base, t["id"], CLIENT_ID) if t["audiodownload_allowed"] else ""
                res.append(r)
            return self.reply(200, {"headers": {"status": "success", "results_count": len(res), "results_fullcount": len(res)},
                                    "results": res})
        if u.path.startswith(("/stream/", "/dl/")):
            body = MP3
            if self.headers.get("Range") == "bytes=0-9":
                self.send_response(206)
                self.send_header("Content-Range", "bytes 0-9/%d" % len(body))
                body = body[:10]
            else:
                self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(body)
            return
        self.reply(404, {})

    def reply(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


@pytest.fixture()
def fake_jamendo():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeJamendo)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    FakeJamendo.seen = []
    yield "http://127.0.0.1:%d/v3.0" % srv.server_address[1]
    srv.shutdown()


def make_client(tmp_path, monkeypatch, **over):
    monkeypatch.setenv("JAM_AI_API_KEY", "")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    cfg = config.reset(data_dir=tmp_path, web_dir=tmp_path / "noweb", **over)
    a = appmod.create_app(cfg, start_queue=False)
    a.state.jobs.kind_cmd["process"] = lambda sid: [sys.executable, str(HERE / "fake_worker.py"), str(cfg.songs_dir), sid]
    a.state.jobs.start()
    return TestClient(a)


# ------------------------------------------------------------------ recordings / picker files

@pytest.mark.parametrize("name,mime,want", [
    ("recording", "audio/mp4", ".m4a"),            # iOS Safari MediaRecorder (AAC in MP4)
    ("recording", "audio/webm;codecs=opus", ".webm"),  # Chrome / Android MediaRecorder
    ("1730871234567", "audio/mpeg", ".mp3"),       # WeChat file picker: numeric name, no extension
    ("voice", "audio/amr", ".amr"),                # Android voice memo
    ("Voice 11.06", "audio/x-m4a", ".m4a"),        # a dot in the name that is not an extension
])
def test_upload_without_extension_uses_mime_type(tmp_path, monkeypatch, name, mime, want):
    with make_client(tmp_path, monkeypatch) as c:
        r = c.post("/api/songs", files={"file": (name, io.BytesIO(MP3), mime)}, data={"title": "rec"})
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
        assert (Path(tmp_path) / "songs" / sid / ("original" + want)).exists()
        wait_status(c, sid, ("ready",))


def test_upload_without_extension_or_type_is_sniffed(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as c:
        # WeChat on Android: no extension, application/octet-stream — the first bytes decide
        r = c.post("/api/songs", files={"file": ("1730871234567", io.BytesIO(MP3), "application/octet-stream")})
        assert r.status_code == 201, r.text
        assert (Path(tmp_path) / "songs" / r.json()["id"] / "original.mp3").exists()
        flac = b"fLaC" + b"\0" * 64
        r = c.post("/api/songs", files={"file": ("audio", io.BytesIO(flac), "")})
        assert r.status_code == 201 and (Path(tmp_path) / "songs" / r.json()["id"] / "original.flac").exists()
        r = c.post("/api/songs", files={"file": ("blob", io.BytesIO(b"%PDF-1.4 hello"), "application/octet-stream")})
        assert r.status_code == 415
        r = c.post("/api/songs", files={"file": ("x.exe", io.BytesIO(MP3), "application/x-msdownload")})
        assert r.status_code == 415
        r = c.post("/api/songs", files={"file": ("x.exe", io.BytesIO(MP3), "audio/mpeg")})   # a real non-audio extension wins
        assert r.status_code == 415
        r = c.post("/api/songs", files={"file": ("Song.Remix", io.BytesIO(MP3), "audio/mpeg")})
        assert r.status_code == 201


def test_encrypted_name_still_refused_even_with_audio_mime(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as c:
        r = c.post("/api/songs", files={"file": ("Song.ncm", io.BytesIO(b"CTENFDAM" + b"\0" * 64), "audio/mpeg")},
                   data={"lang": "zh"})
        assert r.status_code == 415 and "网易云音乐" in r.json()["detail"]


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")
def test_streamed_webm_without_duration_header_is_measured(tmp_path):
    # MediaRecorder writes webm as a live stream: no duration in the header. ffmpeg to a pipe does the same.
    out = tmp_path / "rec.webm"
    with open(out, "wb") as f:
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=6", "-c:a", "libopus",
                        "-f", "webm", "-live", "1", "pipe:1"], stdout=f, check=True)
    assert 5.5 < audio.probe_duration(out) < 6.5


# ------------------------------------------------------------------ Jamendo

def test_jamendo_hidden_without_client_id(tmp_path, monkeypatch):
    monkeypatch.delenv("JAM_JAMENDO_CLIENT_ID", raising=False)
    with make_client(tmp_path, monkeypatch) as c:
        assert c.get("/api/info").json()["jamendo"] is False
        assert c.get("/api/jamendo/search?q=x").status_code == 404
        assert c.post("/api/jamendo/import", json={"id": "1001"}).status_code == 404


def test_jamendo_search_only_downloadable_and_never_leaks_client_id(tmp_path, monkeypatch, fake_jamendo):
    with make_client(tmp_path, monkeypatch, jamendo_client_id=CLIENT_ID, jamendo_api_url=fake_jamendo) as c:
        assert c.get("/api/info").json()["jamendo"] is True
        r = c.get("/api/jamendo/search?q=")
        assert r.status_code == 200, r.text
        res = r.json()["results"]
        assert [t["id"] for t in res] == ["1001"]                       # the locked track is dropped
        assert res[0]["license"] == "CC BY-SA 3.0" and res[0]["license_url"].startswith("http://creativecommons.org/")
        assert CLIENT_ID not in r.text
        assert c.get("/api/jamendo/search?q=locked").json()["results"] == []
        path, q, _ = FakeJamendo.seen[0]
        assert q["include"] == "licenses" and q["client_id"] == CLIENT_ID


def test_jamendo_preview_is_proxied_with_range(tmp_path, monkeypatch, fake_jamendo):
    with make_client(tmp_path, monkeypatch, jamendo_client_id=CLIENT_ID, jamendo_api_url=fake_jamendo) as c:
        c.get("/api/jamendo/search")
        r = c.get("/api/jamendo/preview/1001.mp3", headers={"Range": "bytes=0-9"})
        assert r.status_code == 206 and r.content == MP3[:10] and r.headers["content-type"] == "audio/mpeg"
        assert c.get("/api/jamendo/preview/1001.mp3").content == MP3
        assert c.get("/api/jamendo/preview/1002.mp3").status_code == 404   # not downloadable: no preview either
        assert c.get("/api/jamendo/preview/..%2Fx.mp3").status_code == 404


def test_jamendo_import_keeps_license_and_refuses_locked(tmp_path, monkeypatch, fake_jamendo):
    with make_client(tmp_path, monkeypatch, jamendo_client_id=CLIENT_ID, jamendo_api_url=fake_jamendo) as c:
        r = c.post("/api/jamendo/import", json={"id": "1001", "lang": "zh"})
        assert r.status_code == 201, r.text
        m = r.json()
        assert m["title"] == "Open Road" and m["artist"] == "Free Band" and m["license"] == "CC BY-SA 3.0"
        assert m["source"] == {"kind": "jamendo", "id": "1001", "page": "https://www.jamendo.com/track/1001",
                               "artist": "Free Band", "album": "Roads"}
        assert (Path(tmp_path) / "songs" / m["id"] / "original.mp3").read_bytes() == MP3
        done = wait_status(c, m["id"], ("ready",))
        assert done["license_url"] == "http://creativecommons.org/licenses/by-sa/3.0/"
        assert c.get("/api/songs/%s/song.json" % m["id"]).json()["meta"]["license"] == "CC BY-SA 3.0"
        assert c.post("/api/jamendo/import", json={"id": "1002"}).status_code == 404
        assert c.post("/api/jamendo/import", json={"id": "../1"}).status_code == 400


def test_jamendo_import_respects_passphrase(tmp_path, monkeypatch, fake_jamendo):
    with make_client(tmp_path, monkeypatch, jamendo_client_id=CLIENT_ID, jamendo_api_url=fake_jamendo, admin_key="pw") as c:
        assert c.post("/api/jamendo/import", json={"id": "1001"}).status_code == 401
        assert c.post("/api/jamendo/import", json={"id": "1001"}, headers={"X-Jam-Key": "pw"}).status_code == 201


def test_jamendo_bad_client_id_is_reported_without_echoing_it(tmp_path, monkeypatch, fake_jamendo):
    with make_client(tmp_path, monkeypatch, jamendo_client_id="wrong-id", jamendo_api_url=fake_jamendo) as c:
        r = c.get("/api/jamendo/search?q=x")
        assert r.status_code == 502 and "invalid client id" in r.json()["detail"] and "wrong-id" not in r.text


def test_license_names():
    from cteno_jam.jamendo import license_name
    assert license_name("http://creativecommons.org/licenses/by-nc-sa/3.0/") == "CC BY-NC-SA 3.0"
    assert license_name("https://creativecommons.org/publicdomain/zero/1.0/") == "CC0 1.0"
    assert license_name("") == "Jamendo license"
