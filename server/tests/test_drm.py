"""Encrypted music-app downloads (QQ Music mgg/mflac, NetEase ncm, Kugou kgm, Kuwo kwm, Apple m4p) are
recognised from the file itself and refused with a plain-language message, never decrypted."""
import os
import random
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from cteno_jam import config, store, worker
from cteno_jam.pipeline import drm

NOISE = b"," + random.Random(7).randbytes(4095)  # deterministic, never looks like an MPEG frame sync


def write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return p


# QQ Music's newer mgg/mflac files end with "<key>,<n>,<id>" + big-endian length + "STag"
QQ_TAIL = NOISE + b"5010487,2,004KannO2MlVCc" + struct.pack(">I", 26) + b"STag"


@pytest.mark.parametrize("name,data,want", [
    ("x.mp3", b"CTENFDAM" + NOISE, "netease"),
    ("x.mp3", bytes.fromhex("7CD532EB86027F4BA8AFA68E0FFF9914") + NOISE, "kugou"),
    ("x.mp3", bytes.fromhex("0528BC96E9E45A4391AABDD07AF53631") + NOISE, "kugou"),
    ("x.mp3", b"yeelion-kuwo-tme" + NOISE, "kuwo"),
    ("x.flac", QQ_TAIL, "qq"),
    ("x.flac", NOISE + b"QTag", "qq"),
    ("x.flac", NOISE + b"musicex\x00", "qq"),
    ("x.m4a", b"\x00\x00\x00\x20ftypM4P \x00\x00\x00\x00M4P mp42isom" + NOISE, "apple"),
    ("x.m4a", b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00" + NOISE[:64] + b"drms" + NOISE, "apple"),
    # the real report: the browser sent "...[mqms2].mgg2.flac", the content is unreadable noise
    ("B.o.B&Jessie J - Price Tag [mqms2].mgg2.flac", NOISE, "qq"),
    ("song.ncm.mp3", NOISE, "netease"),
    ("song.kgma", NOISE, "kugou"),
    ("song.m4p", NOISE, "apple"),
    ("song.tkm", NOISE, "qq"),
])
def test_sniff_encrypted(tmp_path, name, data, want):
    assert drm.sniff(write(tmp_path, "f", data), name) == want


@pytest.mark.parametrize("name,data", [
    ("ok.mp3", b"ID3\x04\x00" + NOISE),
    ("ok.mp3", b"\xff\xfb\x90\x00" + NOISE),
    ("ok.flac", b"fLaC" + NOISE),
    ("ok.wav", b"RIFF\x00\x00\x00\x00WAVE" + NOISE),
    ("ok.m4a", b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00" + NOISE),
    # a real FLAC that kept its old name after the user converted it is fine
    ("decoded.mgg2.flac", b"fLaC" + NOISE),
    ("random.mp3", NOISE),  # unknown junk is left to the decoder's own message
])
def test_sniff_plain(tmp_path, name, data):
    assert drm.sniff(write(tmp_path, "f", data), name) is None


def test_messages_bilingual():
    zh, en = drm.message("qq", "zh"), drm.message("qq", "en")
    assert "QQ 音乐" in zh and "加密" in zh and "mp3" in zh
    assert "QQ Music" in en and "encrypted" in en and "mp3" in en
    assert "Apple Music" in drm.message("apple", "en")
    assert drm.message("qq", None) == en  # default English
    for z in (drm.unreadable("zh"), drm.unreadable("en")):
        assert z and "/" not in z.replace("mp3/m4a/flac/wav", "")


def _run_worker(tmp_path, monkeypatch, data, name, lang):
    monkeypatch.setenv("JAM_DATA_DIR", str(tmp_path))
    cfg = config.reset(data_dir=tmp_path)
    st = store.Store(cfg.songs_dir)
    m = st.create("t", "", name, lang=lang)
    (st.dir(m["id"]) / ("original" + os.path.splitext(name)[1])).write_bytes(data)
    assert worker.main([m["id"]]) == 2
    return st.meta(m["id"])["error"]


@pytest.mark.skipif(not shutil.which("ffprobe"), reason="needs ffprobe")
@pytest.mark.parametrize("lang,needle", [("zh", "QQ 音乐"), ("en", "QQ Music")])
def test_worker_names_the_encryption(tmp_path, monkeypatch, lang, needle):
    err = _run_worker(tmp_path, monkeypatch, QQ_TAIL, "a.mgg2.flac", lang)
    assert needle in err


@pytest.mark.skipif(not shutil.which("ffprobe"), reason="needs ffprobe")
@pytest.mark.parametrize("lang,needles", [("zh", ("损坏", "加密", "不是音频")),
                                          ("en", ("damaged", "encrypted", "not an audio"))])
def test_worker_unreadable_is_plain_language(tmp_path, monkeypatch, lang, needles):
    err = _run_worker(tmp_path, monkeypatch, b"this is not audio", "x.mp3", lang)
    assert all(n in err for n in needles), err
    assert "duration" not in err and "ffprobe" not in err
