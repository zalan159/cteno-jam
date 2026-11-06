"""Process one song end to end. Run as a subprocess by the queue:

    python -m cteno_jam.worker <song-id>

Running each job in its own process means a crash, an out-of-memory kill or a stuck model
cannot take the web server down, and all model memory is returned to the OS afterwards.
Progress is written to meta.json, which the API streams to the browser.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

from . import config, store, theory
from .pipeline import audio

log = logging.getLogger("cteno_jam.worker")

# Share of the progress bar per stage (sums to 1.0)
WEIGHTS = {"decode": 0.03, "separate": 0.55, "analyze": 0.12, "lyrics": 0.15, "align": 0.05, "encode": 0.05, "review": 0.05}


class JobError(RuntimeError):
    """A failure with a message meant for the user."""


class Progress:
    def __init__(self, st: store.Store, sid: str):
        self.st, self.sid, self.done, self.t = st, sid, 0.0, {}
        self._stage, self._t0, self._last = None, time.time(), 0.0

    def stage(self, name: str):
        if self._stage:
            self.done += WEIGHTS.get(self._stage, 0)
            self.t[self._stage] = round(time.time() - self._t0, 1)
        self._stage, self._t0 = name, time.time()
        self.st.update(self.sid, stage=name, progress=round(self.done, 3), timings=self.t)
        log.info("[%s] stage %s", self.sid, name)

    def sub(self, frac: float):
        now = time.time()
        if now - self._last < 1.0 and frac < 1:
            return
        self._last = now
        self.st.update(self.sid, progress=round(self.done + WEIGHTS.get(self._stage, 0) * min(1, frac), 3))

    def finish(self):
        self.stage("done")
        return self.t


def unreadable_message(src: Path, filename: str, lang: str) -> str:
    """ffmpeg could not read the upload: name the music app when it is an encrypted download."""
    from .pipeline import drm
    fam = drm.sniff(src, filename)
    return drm.message(fam, lang) if fam else drm.unreadable(lang)


def process(sid: str, cfg: config.Config) -> None:
    st = store.Store(cfg.songs_dir)
    meta = st.meta(sid)
    d = st.dir(sid)
    work = d / "work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    pr = Progress(st, sid)
    st.update(sid, status="processing", error=None, attempts=int(meta.get("attempts", 0)) + 1, started=int(time.time()))
    src = st.original(sid)
    if src is None:
        raise JobError("the uploaded file is missing; please upload it again")

    # ---- decode
    pr.stage("decode")
    lang = meta.get("lang") or ""
    marker = os.environ.get("JAM_TEST_FAIL_TITLE", "")   # e2e only: a title containing this marker fails here
    if marker and marker in (st.meta(sid).get("title") or ""):
        raise JobError("测试：标题里有 JAM_TEST_FAIL_TITLE 标记，按要求处理失败 (test failure on request)")
    try:
        dur = audio.probe_duration(src)
    except audio.AudioError as e:
        log.info("[%s] probe failed: %s", sid, e)
        raise JobError(unreadable_message(src, meta.get("filename") or "", lang))
    if dur < 5:
        raise JobError("the recording is too short (%.1f s); upload at least 5 seconds" % dur)
    if dur > cfg.max_duration_s:
        raise JobError("the recording is %d min long; the limit is %d min (JAM_MAX_DURATION_S)" % (dur // 60, cfg.max_duration_s // 60))
    mix = work / "mix.wav"
    try:
        audio.decode(src, mix, sr=44100, channels=2)
    except audio.AudioError as e:
        log.info("[%s] decode failed: %s", sid, e)
        raise JobError(unreadable_message(src, meta.get("filename") or "", lang))
    st.update(sid, duration=round(dur, 2))

    # ---- separate
    pr.stage("separate")
    from .pipeline import separate as sep
    device = sep.pick_device(cfg.device)
    st.update(sid, device=device)
    try:
        stem_wavs = sep.separate(mix, work / "stems", cfg.demucs_model, device, cfg.threads, progress=pr.sub)
    except RuntimeError as e:
        if "out of memory" in str(e).lower():
            raise JobError("ran out of memory while separating stems; try JAM_DEVICE=cpu or a shorter file")
        raise

    # ---- analyze
    pr.stage("analyze")
    from .pipeline import analyze as an
    mono = {k: audio.load_mono(p, an.SR) for k, p in stem_wavs.items()}
    mono["mix"] = audio.load_mono(mix, an.SR)
    base = an.analyze(mono)
    base["duration"] = round(min(base["duration"], dur), 3)

    # ---- lyrics
    pr.stage("lyrics")
    from .pipeline import lyrics as ly
    rows, source, extra = None, "none", {}
    user_txt = (d / "lyrics.txt").read_text(encoding="utf-8") if (d / "lyrics.txt").exists() else ""
    if user_txt.strip():
        rows, source = ly.parse_lrc(user_txt), "user"
    if rows is None and cfg.lrclib and meta.get("title"):
        hit = ly.lrclib_lookup(meta["title"], meta.get("artist", ""), dur, cfg.lrclib_url)
        if hit:
            rows, source, extra = ly.parse_lrc(hit["lrc"]), "lrclib", {"lrclib_id": hit["id"]}
    words, lang = [], None
    vocal_energy = mono["vocals"].std() if "vocals" in mono else 0
    if vocal_energy > 1e-3 and cfg.whisper_model not in ("", "off", "none"):
        try:
            words, lang = ly.transcribe(str(stem_wavs["vocals"]), cfg.whisper_model, device)
        except Exception as e:  # noqa: BLE001 — lyrics are optional; the chart still works
            log.warning("whisper failed: %s", e)
            extra["whisper_error"] = str(e)[:200]
    if rows is None and words:
        rows, source = [(t, s) for t, s in ly.words_to_lines(words)], "whisper"
    pr.sub(1)

    # ---- align
    pr.stage("align")
    lyr = ly.align(rows or [], base["duration"], words=words if source != "whisper" else words,
                   vocals=mono.get("vocals"), sr=an.SR,
                   offset_span=0.0 if source == "user" else 8.0, beats=base["beats"]) if rows else {"offset": 0.0, "lines": []}
    lyr["source"], lyr["language"] = source, lang
    lyr.update(extra)
    base["lyrics"] = lyr
    key = theory.parse_key(base["key"])
    fret, share = theory.best_capo([(c["chord"], c["end"] - c["start"]) for c in base["chords"]])
    base["capo_rule"] = {"fret": fret, "easy_share": round(share, 2)}
    base["sections"], base["simplified"] = [], {}
    base["analyzer"] = {"separation": cfg.demucs_model, "chords": "chroma-template+viterbi", "lyrics": source,
                        "whisper": cfg.whisper_model if words else None, "device": device,
                        "key_spelling": "sharps" if key and not key.uses_flats else "flats"}

    # ---- encode
    pr.stage("encode")
    out = d / "stems"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    for k, p in stem_wavs.items():
        audio.encode_mp3_mono(p, out / ("%s.mp3" % k))
    audio.encode_mp3_mono(mix, out / "mix.mp3", "128k")
    st.set_base(sid, base)
    sizes = {p.stem: p.stat().st_size for p in out.glob("*.mp3")}
    st.update(sid, stems=sorted(k for k in sizes if k != "mix"), stem_bytes=sizes, lyrics_source=source)
    shutil.rmtree(work, ignore_errors=True)

    # ---- AI review (optional; never fails the job)
    pr.stage("review")
    if cfg.ai_configured:
        from . import review_job
        review_job.review(st, sid, cfg)
    else:
        st.update(sid, ai={"status": "not_configured"})
    t = pr.finish()
    st.update(sid, status="ready", progress=1.0, timings=t, finished=int(time.time()))


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sid = argv[0]
    cfg = config.get()
    st = store.Store(cfg.songs_dir)
    try:
        process(sid, cfg)
        return 0
    except JobError as e:
        st.update(sid, status="failed", error=str(e))
        log.error("[%s] failed: %s", sid, e)
        return 2
    except Exception as e:  # noqa: BLE001
        log.error("[%s] crashed:\n%s", sid, traceback.format_exc())
        msg = str(e).replace(str(cfg.data_dir), "<data>")[:300]
        st.update(sid, status="failed", error="processing crashed: %s: %s (details in the server log)" % (type(e).__name__, msg))
        return 1
    finally:
        try:
            shutil.rmtree(st.dir(sid) / "work", ignore_errors=True)
        except store.NotFound:
            pass


if __name__ == "__main__":
    sys.exit(main())
