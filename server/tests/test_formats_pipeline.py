"""C2: every phone format goes through the REAL processing pipeline (ffmpeg decode -> Demucs -> analysis -> stems).

Runs only where the processing extras are installed (the test machine's venv; skipped on a bare checkout):
a 12 s two-note tone per format, Whisper and LRCLIB off, CPU. About 10-20 s per format on the test machine.
"""
import io
import importlib.util
import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from cteno_jam import app as appmod, config

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and importlib.util.find_spec("demucs") and importlib.util.find_spec("librosa")),
    reason="needs ffmpeg and the processing extras (demucs, librosa)")

FORMATS = {
    ".mp3": ["-c:a", "libmp3lame", "-b:a", "96k"],
    ".m4a": ["-c:a", "aac", "-b:a", "96k"],
    ".wav": ["-c:a", "pcm_s16le"],
    ".flac": ["-c:a", "flac"],
    ".amr": ["-ar", "8000", "-ac", "1", "-c:a", "libopencore_amrnb", "-b:a", "12.2k"],
}


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    d = tmp_path_factory.mktemp("pipeline")
    mp = pytest.MonkeyPatch()
    for k, v in {"JAM_DATA_DIR": str(d), "JAM_WHISPER_MODEL": "off", "JAM_LRCLIB": "0", "JAM_DEVICE": "cpu", "JAM_AI_API_KEY": "", "DEEPSEEK_API_KEY": ""}.items():
        mp.setenv(k, v)
    cfg = config.reset(data_dir=d, web_dir=d / "noweb", check_uploads=True, max_duration_s=600, workers=2)
    a = appmod.create_app(cfg, start_queue=True)       # the real worker: python -m cteno_jam.worker
    with TestClient(a) as c:
        yield c, d
    mp.undo()


def tone(path, ext):
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=6",
                        "-f", "lavfi", "-i", "sine=frequency=330:duration=6", "-filter_complex", "[0][1]concat=n=2:v=0:a=1",
                        *FORMATS[ext], str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("this ffmpeg cannot write %s: %s" % (ext, r.stderr.strip()[-200:]))
    return path.read_bytes()


@pytest.mark.parametrize("ext", sorted(FORMATS))
def test_format_is_processed_end_to_end(server, ext, tmp_path):
    c, _ = server
    data = tone(tmp_path / ("song" + ext), ext)
    r = c.post("/api/songs", files={"file": ("phone song" + ext, io.BytesIO(data), "application/octet-stream")}, data={"title": "fmt " + ext})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    t0, m = time.time(), None
    while time.time() - t0 < 600:
        m = c.get("/api/songs/%s" % sid).json()
        if m["status"] in ("ready", "failed"):
            break
        time.sleep(0.5)
    assert m["status"] == "ready", m.get("error")
    assert 11 < m["duration"] < 13
    assert c.get("/api/songs/%s/stems/mix.mp3" % sid).status_code == 200
    song = c.get("/api/songs/%s/song.json" % sid).json()
    assert song["analysis"]["chords"] and song["analysis"]["beats"] is not None
    print("%s processed in %.1f s (%s)" % (ext, time.time() - t0, m.get("timings")))
