"""In-process job queue: a few threads, each running `python -m cteno_jam.worker <id>` as a subprocess.

Jobs survive restarts: on startup every song whose status is queued/processing is re-queued
(a job that was killed mid-way starts again from its original upload)."""
from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict, Optional

from . import config, store

log = logging.getLogger("cteno_jam.queue")


class JobQueue:
    def __init__(self, st: store.Store, cfg: config.Config, kind_cmd=None):
        self.st, self.cfg = st, cfg
        self.q: "queue.Queue[tuple]" = queue.Queue()
        self.running: Dict[str, subprocess.Popen] = {}
        self.pending: set = set()
        self._lock = threading.Lock()
        self._threads = []
        self.kind_cmd = kind_cmd or {
            "process": lambda sid: [sys.executable, "-m", "cteno_jam.worker", sid],
            "review": lambda sid: [sys.executable, "-m", "cteno_jam.review_cli", sid],
        }

    def start(self):
        for i in range(self.cfg.workers):
            t = threading.Thread(target=self._loop, name="jam-worker-%d" % i, daemon=True)
            t.start()
            self._threads.append(t)
        for m in reversed(self.st.list()):
            if m.get("status") in ("queued", "processing"):
                self.submit(m["id"])
            elif (m.get("ai") or {}).get("status") in ("queued", "running"):
                self.submit(m["id"], "review")

    def submit(self, sid: str, kind: str = "process") -> int:
        with self._lock:
            if (sid, kind) in self.pending:
                return self.position(sid)
            self.pending.add((sid, kind))
        if kind == "process":
            self.st.update(sid, status="queued", stage="queued", progress=0.0, error=None)
        else:
            self.st.update(sid, ai={"status": "queued", "error": None})
        self.q.put((sid, kind))
        return self.position(sid)

    def position(self, sid: str) -> int:
        with self.q.mutex:
            items = list(self.q.queue)
        busy = len(self.running)  # jobs currently being processed are ahead of everything waiting
        for i, (s, _) in enumerate(items):
            if s == sid:
                return i + 1 + busy
        return 0

    def cancel(self, sid: str) -> None:
        p = self.running.get(sid)
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()

    def _loop(self):
        while True:
            sid, kind = self.q.get()
            try:
                self._run(sid, kind)
            except Exception:  # noqa: BLE001
                log.exception("job %s %s", kind, sid)
            finally:
                with self._lock:
                    self.pending.discard((sid, kind))
                self.q.task_done()

    def _run(self, sid: str, kind: str):
        try:
            self.st.dir(sid)
        except store.NotFound:
            return  # deleted while queued
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
        logf = self.st.dir(sid) / ("%s.log" % kind)
        with open(logf, "ab") as lf:
            p = subprocess.Popen(self.kind_cmd[kind](sid), stdout=lf, stderr=subprocess.STDOUT, env=env)
            self.running[sid] = p
            rc = p.wait()
        self.running.pop(sid, None)
        try:
            m = self.st.meta(sid)
        except store.NotFound:
            return
        if kind == "process" and m.get("status") not in ("ready", "failed"):
            self.st.update(sid, status="failed", error="the processing job stopped unexpectedly (exit %s); see %s.log" % (rc, kind))
        if kind == "review" and (m.get("ai") or {}).get("status") in ("queued", "running"):
            self.st.update(sid, ai={"status": "failed", "error": "review job stopped (exit %s)" % rc})
