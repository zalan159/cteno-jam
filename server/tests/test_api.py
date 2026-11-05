"""API tests with the processing step stubbed (a fake worker that writes a known analysis)."""
import io
import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cteno_jam import app as appmod, config, store

from test_patches import song

HERE = Path(__file__).resolve().parent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JAM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JAM_AI_API_KEY", "")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    cfg = config.reset(data_dir=tmp_path, web_dir=tmp_path / "noweb")
    a = appmod.create_app(cfg, start_queue=False)
    jobs = a.state.jobs
    # fake worker: python tests/fake_worker.py <dir> <id>
    jobs.kind_cmd["process"] = lambda sid: [sys.executable, str(HERE / "fake_worker.py"), str(cfg.songs_dir), sid]
    jobs.start()
    with TestClient(a) as c:
        yield c


def wait_status(c, sid, want, t=20):
    end = time.time() + t
    while time.time() < end:
        m = c.get("/api/songs/%s" % sid).json()
        if m["status"] in want:
            return m
        time.sleep(0.1)
    raise AssertionError("status stayed %s" % m["status"])


def upload(c, name="demo.mp3", data=b"ID3fake", **form):
    return c.post("/api/songs", files={"file": (name, io.BytesIO(data), "audio/mpeg")}, data=form)


def test_info_reports_ai_not_configured(client):
    i = client.get("/api/info").json()
    assert i["upload"] is True and i["ai"]["configured"] is False and len(i["room"]) == 6


def test_upload_process_list_search_rename_delete(client):
    r = upload(client, title="Twinkle", artist="Trad.")
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    m = wait_status(client, sid, ("ready", "failed"))
    assert m["status"] == "ready" and m["progress"] == 1.0
    s = client.get("/api/songs/%s/song.json" % sid).json()
    assert s["analysis"]["key"] == "E major" and s["meta"]["title"] == "Twinkle"
    assert client.get("/api/songs?q=twink").json()["songs"][0]["id"] == sid
    assert client.get("/api/songs?q=zzz").json()["songs"] == []
    assert client.patch("/api/songs/%s" % sid, json={"title": "Little Star"}).json()["title"] == "Little Star"
    assert client.get("/api/songs/%s/song.json" % sid).json()["analysis"]["title"] == "Little Star"
    assert client.get("/api/songs/%s/stems/vocals.mp3" % sid).status_code == 200
    assert client.get("/api/songs/%s/stems/../../x.mp3" % sid).status_code == 404
    assert client.delete("/api/songs/%s" % sid).status_code == 204
    assert client.get("/api/songs/%s" % sid).status_code == 404


def test_bad_type_and_failure_and_retry(client):
    assert upload(client, name="x.exe").status_code == 415
    r = upload(client, name="broken.wav", data=b"FAIL")  # fake worker fails on this content
    sid = r.json()["id"]
    m = wait_status(client, sid, ("ready", "failed"))
    assert m["status"] == "failed" and "not a readable audio file" in m["error"]
    # replace the content, then retry
    orig = Path(client.app.state.cfg.songs_dir) / sid / "original.wav"
    orig.write_bytes(b"OK now")
    assert client.post("/api/songs/%s/retry" % sid).status_code == 200
    m = wait_status(client, sid, ("ready",))
    assert m["attempts"] == 2


def test_edits_and_revisions_api(client):
    sid = upload(client).json()["id"]
    wait_status(client, sid, ("ready",))
    r = client.post("/api/songs/%s/edits" % sid, json={"patches": [{"op": "replace_chord", "id": "c002", "chord": "C#m"}]})
    assert r.status_code == 200, r.text
    s = r.json()["song"]
    assert s["analysis"]["chords"][1]["chord"] == "C#m" and s["revisions"][0]["source"] == "user"
    bad = client.post("/api/songs/%s/edits" % sid, json={"patches": [{"op": "replace_chord", "id": "zz", "chord": "C"}]})
    assert bad.status_code == 422 and "no chord segment" in bad.json()["error"]
    r = client.post("/api/songs/%s/revisions" % sid, json={"ids": "all", "status": "reverted"})
    assert r.json()["song"]["analysis"]["chords"][1]["chord"] == "Abm"


def test_upload_records_ui_language_and_review_can_override(client):
    sid = upload(client, title="阳光宅男", lang="zh-CN").json()["id"]
    assert client.get("/api/songs/%s" % sid).json()["lang"] == "zh"
    wait_status(client, sid, ("ready",))
    client.post("/api/songs/%s/review?lang=en" % sid)          # 409 (no key) but the language is recorded first
    assert client.get("/api/songs/%s" % sid).json()["lang"] == "en"
    other = upload(client, title="x", lang="klingon").json()["id"]
    assert "lang" not in client.get("/api/songs/%s" % other).json()


def test_review_requires_key(client):
    sid = upload(client).json()["id"]
    wait_status(client, sid, ("ready",))
    r = client.post("/api/songs/%s/review" % sid)
    assert r.status_code == 409 and "not configured" in r.json()["detail"]
    assert client.get("/api/songs/%s" % sid).json()["ai"]["status"] == "not_configured"


def test_sync_room_relay():
    """Rooms logic in one event loop (TestClient gives every websocket its own loop)."""
    import asyncio
    from cteno_jam.rooms import Rooms

    class FakeWS:
        def __init__(self):
            self.inbox, self.out = asyncio.Queue(), []

        async def receive_text(self):
            m = await self.inbox.get()
            if m is None:
                raise RuntimeError("closed")
            return m

        async def send_text(self, s):
            self.out.append(json.loads(s))

    async def main():
        rooms = Rooms()
        host, remote, viewer = FakeWS(), FakeWS(), FakeWS()
        tasks = [asyncio.ensure_future(rooms.handle(w, "abc234")) for w in (host, remote, viewer)]
        send = lambda w, **m: w.inbox.put_nowait(json.dumps(m))
        send(host, t="hello", role="host"); await asyncio.sleep(0.05)
        send(remote, t="hello", role="remote"); send(viewer, t="hello", role="viewer"); await asyncio.sleep(0.05)
        assert [m["t"] for m in host.out][0] == "welcome"
        assert next(m for m in viewer.out if m["t"] == "welcome")["n"] == 3
        send(host, t="state", song="x", playing=True, pos=12.5, rate=1, tr=2); await asyncio.sleep(0.05)
        st = [m for m in viewer.out if m["t"] == "state"][-1]
        assert st["pos"] == 12.5 and st["tr"] == 2 and "at" in st
        send(remote, t="cmd", cmd="pause"); await asyncio.sleep(0.05)
        assert [m for m in host.out if m["t"] == "cmd"][-1]["cmd"] == "pause"
        assert not [m for m in viewer.out if m["t"] == "cmd"], "commands go to hosts only"
        send(viewer, t="state", pos=99); await asyncio.sleep(0.05)
        assert rooms.rooms["abc234"].state["pos"] == 12.5, "only a host may set state"
        late = FakeWS(); tasks.append(asyncio.ensure_future(rooms.handle(late, "abc234")))
        send(late, t="hello", role="viewer"); await asyncio.sleep(0.05)
        assert late.out[0]["state"]["pos"] == 12.5, "late joiners get the current state"
        send(viewer, t="ping", c=5); await asyncio.sleep(0.05)
        assert [m for m in viewer.out if m["t"] == "pong"][-1]["c"] == 5
        for w in (host, remote, viewer, late):
            w.inbox.put_nowait(None)
        await asyncio.gather(*tasks)
        assert not rooms.rooms["abc234"].peers

    asyncio.run(main())


def test_ws_endpoint_handshake(client):
    with client.websocket_connect("/ws/room/abc234") as ws:
        ws.send_text(json.dumps({"t": "hello", "role": "host"}))
        assert json.loads(ws.receive_text())["t"] == "welcome"


def test_player_mode_refuses_upload(tmp_path, monkeypatch):
    cfg = config.reset(data_dir=tmp_path, web_dir=tmp_path / "noweb", mode="player")
    with TestClient(appmod.create_app(cfg, start_queue=False)) as c:
        assert c.get("/api/info").json()["upload"] is False
        assert upload(c).status_code == 403


def test_admin_key(tmp_path):
    cfg = config.reset(data_dir=tmp_path, web_dir=tmp_path / "noweb", admin_key="s3cret")
    with TestClient(appmod.create_app(cfg, start_queue=False)) as c:
        assert upload(c).status_code == 401
        assert c.post("/api/songs", files={"file": ("a.mp3", io.BytesIO(b"x"))}, headers={"X-Jam-Key": "s3cret"}).status_code == 201


def test_audio_errors_hide_server_paths(tmp_path):
    from cteno_jam.pipeline import audio
    bad = tmp_path / "secret-dir" / "original.mp3"
    bad.parent.mkdir()
    bad.write_bytes(b"not audio at all")
    try:
        audio.probe_duration(bad)
    except audio.AudioError as e:
        assert "secret-dir" not in str(e) and "not a readable audio file" in str(e)
    else:
        raise AssertionError("expected AudioError")


def _guarded_client(tmp_path, **over):
    cfg = config.reset(data_dir=tmp_path, web_dir=tmp_path / "noweb", **over)
    a = appmod.create_app(cfg, start_queue=False)  # nothing consumes the queue: songs stay "queued"
    return TestClient(a)


def test_queue_limit_rejects_when_full(tmp_path):
    with _guarded_client(tmp_path, max_queue=2) as c:
        assert upload(c, title="a").status_code == 201
        r2 = upload(c, title="b")
        assert r2.status_code == 201 and r2.json()["queue_position"] == 2
        r3 = upload(c, title="c")
        assert r3.status_code == 429 and "队列已满" in r3.json()["detail"]


def test_per_ip_hourly_limit_uses_forwarded_for(tmp_path):
    with _guarded_client(tmp_path, uploads_per_ip_hour=2) as c:
        a, b = {"X-Forwarded-For": "8.8.8.8"}, {"X-Forwarded-For": "1.1.1.1, 10.0.0.1"}
        for i in range(2):
            assert c.post("/api/songs", files={"file": ("x.mp3", io.BytesIO(b"ID3x"), "audio/mpeg")}, headers=a).status_code == 201
        r = c.post("/api/songs", files={"file": ("x.mp3", io.BytesIO(b"ID3x"), "audio/mpeg")}, headers=a)
        assert r.status_code == 429
        # another client is unaffected; a private (LAN) client is exempt by default
        assert c.post("/api/songs", files={"file": ("x.mp3", io.BytesIO(b"ID3x"), "audio/mpeg")}, headers=b).status_code == 201
        lan = {"X-Forwarded-For": "192.168.8.20"}
        for _ in range(4):
            assert c.post("/api/songs", files={"file": ("x.mp3", io.BytesIO(b"ID3x"), "audio/mpeg")}, headers=lan).status_code == 201


def test_disk_guard(tmp_path):
    with _guarded_client(tmp_path, max_disk_percent=1) as c:  # any real disk is >1% full
        assert upload(c).status_code == 507


def test_events_stream_carries_queue_position(tmp_path):
    with _guarded_client(tmp_path) as c:
        upload(c, title="a"); upload(c, title="b")
        with c.stream("GET", "/api/events") as r:
            line = next(l for l in r.iter_lines() if l.startswith("data:"))
        songs = json.loads(line[5:])["songs"]
        assert sorted(s["queue_position"] for s in songs if s["status"] == "queued") == [1, 2]


def test_encrypted_upload_refused_with_friendly_message(client):
    tail = b"\x8a\x13" * 2048 + b"5010487,2,004KannO2MlVCc" + (26).to_bytes(4, "big") + b"STag"
    for name in ("Price Tag [mqms2].mgg2.flac", "Price Tag.mgg2", "Price Tag.mflac"):
        r = upload(client, name=name, data=tail, lang="zh")
        assert r.status_code == 415, (name, r.text)
        assert "QQ 音乐" in r.json()["detail"] and "加密" in r.json()["detail"]
    r = upload(client, name="x.ncm", data=b"CTENFDAM" + b"\0" * 64, lang="en")
    assert r.status_code == 415 and "NetEase" in r.json()["detail"]
    r = upload(client, name="x.mp3", data=b"CTENFDAM" + b"\0" * 64)  # renamed, no lang -> English
    assert r.status_code == 415 and "NetEase" in r.json()["detail"]
    assert client.get("/api/songs").json()["songs"] == []  # nothing left behind


def test_info_lists_encrypted_extensions(client):
    enc = client.get("/api/info").json()["encrypted_ext"]
    assert ".mgg" in enc and ".ncm" in enc and ".m4p" in enc
