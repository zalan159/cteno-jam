"""Per-song management tokens (scenarios D1-D4 in docs/acceptance-scenarios.md).

The upload / import response carries `owner_token` once; the server keeps only its hash. Rename, delete, retry,
edits, revisions and AI review need that token in X-Jam-Owner (or the server passphrase); anything else is 403
with a Chinese reason. `python -m cteno_jam.admin` deletes any song on the server itself.
"""
import io
import json
import sys

import pytest

from cteno_jam import admin, app as appmod, config, store
from conftest import owner
from test_api import client, upload, wait_status  # noqa: F401  (client is a fixture)
from test_audio_sources import fake_jamendo  # noqa: F401  (fixture)

WRITES = [  # (method, path suffix, json body) — every song write endpoint except "count a play"
    ("PATCH", "", {"title": "hijacked"}),
    ("POST", "/retry", None),
    ("POST", "/edits", {"patches": [{"op": "replace_chord", "id": "c002", "chord": "C#m"}]}),
    ("POST", "/revisions", {"ids": "all", "status": "reverted"}),
    ("POST", "/review", None),
    ("DELETE", "", None),
]


def call(c, method, sid, suffix, body, headers=None):
    return c.request(method, "/api/songs/%s%s" % (sid, suffix), json=body, headers=headers or {})


def ready(c, title="mine"):
    r = upload(c, title=title)
    assert r.status_code == 201, r.text
    wait_status(c, r.json()["id"], ("ready",))
    return r


def test_upload_returns_a_token_once_and_stores_only_its_hash(client):
    r = ready(client)
    sid, tok = r.json()["id"], r.json()["owner_token"]
    assert len(tok) >= 40
    meta_file = client.app.state.cfg.songs_dir / sid / "meta.json"
    raw = meta_file.read_text(encoding="utf-8")
    assert tok not in raw and json.loads(raw)["owner_hash"] == store.token_hash(tok)
    # never handed out again: not in the song, the list, the event stream or song.json
    for url in ("/api/songs/%s" % sid, "/api/songs", "/api/songs/%s/song.json" % sid):
        body = client.get(url).text
        assert tok not in body and "owner_hash" not in body, url
    # two uploads get different tokens
    assert upload(client).json()["owner_token"] != tok


def test_owner_can_rename_edit_retry_and_delete(client):
    r = ready(client)
    sid, own = r.json()["id"], owner(r)
    assert call(client, "PATCH", sid, "", {"title": "Renamed"}, own).json()["title"] == "Renamed"
    assert call(client, "POST", sid, "/edits", WRITES[2][2], own).status_code == 200
    assert call(client, "POST", sid, "/revisions", WRITES[3][2], own).status_code == 200
    assert call(client, "POST", sid, "/review", None, own).status_code == 409   # allowed; AI just is not configured
    assert call(client, "POST", sid, "/retry", None, own).status_code == 200
    wait_status(client, sid, ("ready",))
    assert call(client, "DELETE", sid, "", None, own).status_code == 204
    assert client.get("/api/songs/%s" % sid).status_code == 404


@pytest.mark.parametrize("method,suffix,body", WRITES)
@pytest.mark.parametrize("hdr", [None, {"X-Jam-Owner": ""}, {"X-Jam-Owner": "wrong-token"}, {"X-Jam-Key": "anything"}],
                         ids=["no-token", "empty", "wrong", "random-passphrase"])
def test_without_the_right_token_every_write_is_403_in_chinese(client, method, suffix, body, hdr):
    r = ready(client)
    sid = r.json()["id"]
    res = call(client, method, sid, suffix, body, hdr)
    assert res.status_code == 403, res.text
    assert "只有上传这首歌的浏览器" in res.json()["detail"]
    m = client.get("/api/songs/%s" % sid).json()
    assert m["title"] == "mine" and m["status"] == "ready"          # nothing changed


def test_a_token_cannot_manage_another_song(client):
    a, b = ready(client, "A"), ready(client, "B")
    tok_a = owner(a)
    for method, suffix, body in WRITES:
        assert call(client, method, b.json()["id"], suffix, body, tok_a).status_code == 403, (method, suffix)
    assert client.get("/api/songs/%s" % b.json()["id"]).json()["title"] == "B"
    assert call(client, "DELETE", a.json()["id"], "", None, tok_a).status_code == 204


def test_old_songs_without_a_token_cannot_be_managed_over_http(client):
    """Songs uploaded before tokens existed have no owner_hash: 403 for everyone (expected), admin CLI still works."""
    st = client.app.state.store
    m = st.create("old song", filename="old.mp3")
    st.update(m["id"], status="failed", error="x")
    assert "owner_hash" not in st.meta(m["id"])
    for hdr in (None, {"X-Jam-Owner": "x"}, {"X-Jam-Owner": store.token_hash("")}):
        assert client.delete("/api/songs/%s" % m["id"], headers=hdr or {}).status_code == 403


def test_demo_song_cannot_be_deleted_even_with_a_token_guess(client):
    st = client.app.state.store
    st.create("Twinkle demo", sid="demo-twinkle", demo=True)
    r = client.delete("/api/songs/demo-twinkle", headers={"X-Jam-Owner": "x"})
    assert r.status_code == 403 and "演示歌" in r.json()["detail"]


def test_jamendo_import_returns_a_token(tmp_path, monkeypatch, fake_jamendo):
    from test_audio_sources import CLIENT_ID, make_client
    with make_client(tmp_path, monkeypatch, jamendo_client_id=CLIENT_ID, jamendo_api_url=fake_jamendo) as c:
        r = c.post("/api/jamendo/import", json={"id": "1001"})
        assert r.status_code == 201, r.text
        sid, tok = r.json()["id"], r.json()["owner_token"]
        wait_status(c, sid, ("ready",))
        # importing the same track again opens the library copy, without handing out its token
        again = c.post("/api/jamendo/import", json={"id": "1001"})
        assert again.status_code == 200 and "owner_token" not in again.json()
        assert c.delete("/api/songs/%s" % sid).status_code == 403
        assert c.delete("/api/songs/%s" % sid, headers={"X-Jam-Owner": tok}).status_code == 204


def test_server_passphrase_manages_every_song(tmp_path, monkeypatch):
    monkeypatch.setenv("JAM_AI_API_KEY", "")
    cfg = config.reset(data_dir=tmp_path, web_dir=tmp_path / "noweb", admin_key="s3cret")
    from fastapi.testclient import TestClient
    with TestClient(appmod.create_app(cfg, start_queue=False)) as c:
        sid = c.post("/api/songs", files={"file": ("a.mp3", io.BytesIO(b"x"))}, headers={"X-Jam-Key": "s3cret"}).json()["id"]
        assert c.delete("/api/songs/%s" % sid, headers={"X-Jam-Key": "nope"}).status_code == 403
        assert c.delete("/api/songs/%s" % sid, headers={"X-Jam-Key": "s3cret"}).status_code == 204


# ------------------------------------------------------------------ D4 admin CLI

def test_admin_cli_lists_and_deletes_any_song(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("JAM_DATA_DIR", str(tmp_path))
    config.reset(data_dir=tmp_path)
    st = store.Store(tmp_path / "songs")
    old = st.create("old failed upload", filename="x.mp3")
    st.update(old["id"], status="failed", error="unreadable")
    new = st.create("new upload", owner_token=store.new_owner_token())
    st.create("demo", sid="demo-twinkle", demo=True)
    assert admin.main(["list", "--no-owner", "--failed"]) == 0
    out = capsys.readouterr().out
    assert old["id"] in out and new["id"] not in out and "demo-twinkle" not in out
    assert admin.main(["show", new["id"]]) == 0
    shown = capsys.readouterr().out
    assert "owner_hash" not in shown and '"has_owner_token": true' in shown
    assert admin.main(["delete", old["id"], new["id"], "--yes"]) == 0
    assert "deleted %s" % old["id"] in capsys.readouterr().out
    assert [m["id"] for m in st.list()] == ["demo-twinkle"]
    assert admin.main(["delete", "demo-twinkle", "--yes"]) == 1          # demo needs --force-demo
    assert admin.main(["delete", "nosuchsong", "--yes"]) == 1
    assert admin.main(["delete", "demo-twinkle", "--yes", "--force-demo"]) == 0
    assert st.list() == []


def test_admin_cli_runs_as_a_module(tmp_path):
    import subprocess
    st = store.Store(tmp_path / "songs")
    sid = st.create("cli song")["id"]
    env = {"JAM_DATA_DIR": str(tmp_path), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(appmod.Path(appmod.__file__).parents[1])}
    r = subprocess.run([sys.executable, "-m", "cteno_jam.admin", "delete", sid, "--yes"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and ("deleted " + sid) in r.stdout, r.stderr
    assert st.list() == []
