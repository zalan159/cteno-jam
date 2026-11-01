"""AI review: pure parts always; the full Cteno SDK path against a local fake model when
cteno-sdk (with its bundled daemon) is installed. No network, no key."""
import copy
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from cteno_jam import review as R
from cteno_jam import store

from test_patches import song

HERE = Path(__file__).resolve().parent


def test_overview_finds_out_of_key_and_blips():
    ov = R.overview(song())
    assert "Abm" not in ov["out_of_key_chords"]  # Abm == G#m is diatonic in E
    assert "F" in ov["out_of_key_chords"]
    assert ov["segments_by_length_beats"]["1"] == 1
    assert ov["chord_segments"] == 7


def test_dry_run_reports_each_patch():
    res = R.dry_run(song(), [
        {"op": "respell_chord", "id": "c002", "chord": "G#m", "reason": "key"},
        {"op": "respell_chord", "id": "c002", "chord": "G#m", "reason": "again"},  # already spelled now
        {"op": "nope", "reason": "x"},
    ])
    assert [a["index"] for a in res["accepted"]] == [0]
    assert [r["index"] for r in res["rejected"]] == [1, 2]


def test_chord_page_links_lines():
    p = R.chord_page(song(), 0, 3)
    assert p["has_more"] and p["chords"][1]["line"] == "l001" and p["chords"][0]["line"] is None


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _sdk_available():
    try:
        import cteno_sdk  # noqa: F401
        from cteno_sdk.daemon import instance_layout  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return os.environ.get("JAM_SKIP_SDK_TESTS") != "1"


@pytest.fixture(scope="module")
def fake_model():
    port = _free_port()
    log = tempfile.mktemp(suffix=".jsonl")
    p = subprocess.Popen([sys.executable, str(HERE / "fake_model.py")], env={**os.environ, "MOCK_PORT": str(port), "MOCK_LOG": log})
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield "http://127.0.0.1:%d/v1" % port, log
    p.terminate()


@pytest.fixture(scope="module")
def sdk_home():
    # short path: the daemon's unix socket path is limited to ~104 bytes
    d = tempfile.mkdtemp(prefix="jsdk", dir="/tmp")
    # The daemon inherits our environment. Behind an HTTP(S)_PROXY it sends even 127.0.0.1
    # through the proxy (NO_PROXY is not honoured for loopback in 2.10.16), so the fake model
    # would be unreachable. Clear proxy variables for this test daemon only.
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.lower() in ("http_proxy", "https_proxy", "all_proxy")}
    yield d
    os.environ.update(saved)
    try:
        import asyncio
        from cteno_sdk import stop_daemon
        asyncio.run(stop_daemon(d))
    except Exception:  # noqa: BLE001
        pass


@pytest.mark.skipif(not _sdk_available(), reason="cteno-sdk with bundled daemon not installed")
def test_review_through_cteno_sdk_with_fake_model(fake_model, sdk_home, tmp_path):
    base_url, log = fake_model
    a = song()
    before = copy.deepcopy(a)
    res = R.run_review_sync(a, base_url=base_url, model="fake-reviewer", api_key="test-not-a-key",
                            timeout_s=120, sdk_home=sdk_home)
    assert res.ok, res.error
    assert a == before, "the review must not touch the state it was given"
    # the model really went through the client tools in our process
    assert res.tool_calls[:3] == ["get_overview", "get_chords", "check_patches"]
    ops = [p["op"] for p in res.accepted]
    assert "respell_chord" in ops and "merge_chord" in ops and "add_section" in ops
    errs = " | ".join(r["error"] for r in res.rejected)
    assert "unknown or not allowed op 'rewrite_song'" in errs
    assert "must sound the same" in errs
    assert "no chord segment with id 'c999'" in errs

    # store it the way the worker does, then undo it all
    st = store.Store(tmp_path)
    m = st.create("t")
    st.set_base(m["id"], a)
    s, late = st.add_patches(m["id"], res.accepted, "ai", "b1")
    assert not late
    chords = [c["chord"] for c in s["analysis"]["chords"]]
    assert "G#m" in chords and "C#m" in chords and "Abm" not in chords
    assert all(r["reason"] and r["source"] == "ai" for r in s["revisions"])
    s = st.set_revision_status(m["id"], [r["id"] for r in s["revisions"]], "reverted")
    assert s["analysis"]["chords"] == a["chords"]
