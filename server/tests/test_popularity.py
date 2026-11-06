"""Popularity (热度): server-side play counts, the 30 s per-session dedup, and the library sorted by plays."""
from fastapi.testclient import TestClient

from cteno_jam import app as appmod
from test_api import client, upload, wait_status  # noqa: F401  (client is a fixture)


TOKENS = {}


def ready_song(c, title):
    r = upload(c, title=title)
    sid = r.json()["id"]
    TOKENS[sid] = r.json()["owner_token"]
    wait_status(c, sid, ("ready",))
    return sid


def test_play_is_counted_once_per_session_within_30s(client, monkeypatch):
    sid = ready_song(client, "Song A")
    assert client.get("/api/songs/%s" % sid).json()["plays"] == 0
    r = client.post("/api/songs/%s/play" % sid, json={"session": "sess-aaaaaaaa"})
    assert r.status_code == 200 and r.json() == {"plays": 1, "counted": True}
    # same session again (reload, pause/play, jam start right after play): not counted
    assert client.post("/api/songs/%s/play" % sid, json={"session": "sess-aaaaaaaa"}).json() == {"plays": 1, "counted": False}
    # another listener counts
    assert client.post("/api/songs/%s/play" % sid, json={"session": "sess-bbbbbbbb"}).json()["plays"] == 2
    # 31 s later the first session counts again
    real = appmod.time.time
    monkeypatch.setattr(appmod.time, "time", lambda: real() + 31)
    assert client.post("/api/songs/%s/play" % sid, json={"session": "sess-aaaaaaaa"}).json() == {"plays": 3, "counted": True}
    assert client.get("/api/songs/%s" % sid).json()["plays"] == 3


def test_no_session_falls_back_to_ip_and_bad_ids(client):
    sid = ready_song(client, "Song B")
    h = {"X-Forwarded-For": "203.0.113.9"}
    assert client.post("/api/songs/%s/play" % sid, headers=h).json()["counted"] is True
    assert client.post("/api/songs/%s/play" % sid, headers=h, json={"session": "x"}).json()["counted"] is False  # too short: IP
    assert client.post("/api/songs/%s/play" % sid, headers={"X-Forwarded-For": "203.0.113.10"}).json()["plays"] == 2
    assert client.post("/api/songs/nosuchsong/play").status_code == 404


def test_play_needs_a_ready_song(client):
    sid = upload(client, title="Busy").json()["id"]
    r = client.post("/api/songs/%s/play" % sid, json={"session": "sess-cccccccc"})
    assert r.status_code in (200, 409)        # the fake worker may already be done; when not, it is refused
    if r.status_code == 409:
        assert client.get("/api/songs/%s" % sid).json().get("plays", 0) == 0


def test_play_does_not_touch_meta_and_survives_restart(client, tmp_path):
    sid = ready_song(client, "Song C")
    before = client.get("/api/songs/%s" % sid).json()["updated"]
    client.post("/api/songs/%s/play" % sid, json={"session": "sess-dddddddd"})
    assert client.get("/api/songs/%s" % sid).json()["updated"] == before
    # a new app on the same data dir still knows the count
    st = client.app.state.store
    assert st.plays()[sid] == 1
    a2 = appmod.create_app(client.app.state.cfg, start_queue=False)
    with TestClient(a2) as c2:
        assert [m["plays"] for m in c2.get("/api/songs").json()["songs"] if m["id"] == sid] == [1]


def test_library_is_sorted_by_plays_then_newest(client):
    a = ready_song(client, "Alpha")
    b = ready_song(client, "Bravo")
    c = ready_song(client, "Charlie")
    for i, n in ((a, 3), (c, 1)):
        for k in range(n):
            client.post("/api/songs/%s/play" % i, json={"session": "sess-%08d" % k})
    songs = client.get("/api/songs").json()["songs"]
    assert [(m["title"], m["plays"]) for m in songs] == [("Alpha", 3), ("Charlie", 1), ("Bravo", 0)]
    # search results keep the same order
    assert [m["title"] for m in client.get("/api/songs?q=a").json()["songs"]] == ["Alpha", "Charlie", "Bravo"]


def test_delete_forgets_the_count(client):
    sid = ready_song(client, "Gone")
    client.post("/api/songs/%s/play" % sid, json={"session": "sess-eeeeeeee"})
    assert client.delete("/api/songs/%s" % sid, headers={"X-Jam-Owner": TOKENS[sid]}).status_code == 204
    assert sid not in client.app.state.store.plays()
