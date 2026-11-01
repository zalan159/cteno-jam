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
