"""Upload-time checks with the real ffprobe (scenarios C2, C3 in docs/acceptance-scenarios.md).

Every format a phone hands over is accepted; broken, too short, too long and too big files are refused while
uploading, in plain Chinese, with nothing queued and no failed record left behind.
"""
import io
import shutil
import subprocess

import pytest

from cteno_jam import app as appmod, config
from test_audio_sources import make_client

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg/ffprobe")

FORMATS = {  # extension -> ffmpeg output options
    ".mp3": ["-c:a", "libmp3lame", "-b:a", "64k"],
    ".m4a": ["-c:a", "aac", "-b:a", "64k"],
    ".wav": ["-c:a", "pcm_s16le"],
    ".flac": ["-c:a", "flac"],
    ".amr": ["-ar", "8000", "-ac", "1", "-c:a", "libopencore_amrnb", "-b:a", "12.2k"],
}


def tone(tmp_path, ext, seconds=6.0, opts=None):
    out = tmp_path / ("tone" + ext)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=%s" % seconds,
                        *(opts if opts is not None else FORMATS[ext]), str(out)], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("this ffmpeg cannot write %s: %s" % (ext, r.stderr.strip()[-200:]))
    return out.read_bytes()


def checked(tmp_path, monkeypatch, **over):
    return make_client(tmp_path / "srv", monkeypatch, check_uploads=True, max_duration_s=600, **over)


def nothing_left(c):
    songs = c.get("/api/songs").json()["songs"]
    assert songs == [], songs
    assert not [p for p in c.app.state.cfg.songs_dir.iterdir() if not p.name.startswith(".")]


@pytest.mark.parametrize("ext", sorted(FORMATS))
def test_every_phone_format_is_accepted_and_measured(tmp_path, monkeypatch, ext):
    data = tone(tmp_path, ext)
    with checked(tmp_path, monkeypatch) as c:
        r = c.post("/api/songs", files={"file": ("song" + ext, io.BytesIO(data), "application/octet-stream")}, data={"lang": "zh"})
        assert r.status_code == 201, r.text
        assert 5.5 < r.json()["duration"] < 6.6
        assert r.json()["owner_token"]


@pytest.mark.parametrize("data,name", [(b"this is not audio", "x.mp3"), (b"ID3\x04\0" + b"\0" * 4096, "fake.mp3"),
                                       (b"RIFF\x24\0\0\0WAVEfmt " + b"\0" * 64, "cut.wav")],
                         ids=["text-as-mp3", "id3-header-only", "truncated-wav"])
def test_broken_file_is_refused_at_upload(tmp_path, monkeypatch, data, name):
    with checked(tmp_path, monkeypatch) as c:
        r = c.post("/api/songs", files={"file": (name, io.BytesIO(data), "audio/mpeg")}, data={"lang": "zh"})
        assert r.status_code in (400, 415), r.text
        assert "读不出这个文件里的音频" in r.json()["detail"] or "太短" in r.json()["detail"]
        nothing_left(c)


def test_too_short_is_refused(tmp_path, monkeypatch):
    data = tone(tmp_path, ".mp3", seconds=2)
    with checked(tmp_path, monkeypatch) as c:
        r = c.post("/api/songs", files={"file": ("short.mp3", io.BytesIO(data), "audio/mpeg")}, data={"lang": "zh"})
        assert r.status_code == 400 and "太短" in r.json()["detail"]
        nothing_left(c)


def test_longer_than_600_s_is_refused(tmp_path, monkeypatch):
    data = tone(tmp_path, ".mp3", seconds=601, opts=["-ac", "1", "-c:a", "libmp3lame", "-b:a", "8k"])
    with checked(tmp_path, monkeypatch) as c:
        r = c.post("/api/songs", files={"file": ("long.mp3", io.BytesIO(data), "audio/mpeg")}, data={"lang": "zh"})
        assert r.status_code == 413, r.text
        assert "10 分 01 秒" in r.json()["detail"] and "10 分钟的上限" in r.json()["detail"]
        nothing_left(c)
        # English for an English page
        r = c.post("/api/songs", files={"file": ("long.mp3", io.BytesIO(data), "audio/mpeg")}, data={"lang": "en"})
        assert r.status_code == 413 and "limit is 10 minutes" in r.json()["detail"]


def test_bigger_than_the_limit_is_refused_in_chinese(tmp_path, monkeypatch):
    with checked(tmp_path, monkeypatch, max_upload_mb=1) as c:
        big = b"ID3\x04\0" + b"\0" * (1024 * 1024 + 10)
        r = c.post("/api/songs", files={"file": ("big.mp3", io.BytesIO(big), "audio/mpeg")}, data={"lang": "zh"})
        assert r.status_code == 413 and "超过 1 MB 上限" in r.json()["detail"]
        nothing_left(c)


def test_refused_uploads_do_not_count_against_the_hourly_limit(tmp_path, monkeypatch):
    good = tone(tmp_path, ".mp3")
    with checked(tmp_path, monkeypatch, uploads_per_ip_hour=1) as c:
        ip = {"X-Forwarded-For": "8.8.4.4"}
        for _ in range(3):
            assert c.post("/api/songs", files={"file": ("x.mp3", io.BytesIO(b"not audio"), "audio/mpeg")}, headers=ip).status_code == 415
        assert c.post("/api/songs", files={"file": ("x.mp3", io.BytesIO(good), "audio/mpeg")}, headers=ip).status_code == 201
        r = c.post("/api/songs", files={"file": ("x.mp3", io.BytesIO(good), "audio/mpeg")}, headers=ip)
        assert r.status_code == 429 and "每小时最多 1 首" in r.json()["detail"]
