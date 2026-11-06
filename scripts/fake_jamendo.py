#!/usr/bin/env python3
"""A stand-in for the Jamendo API for end-to-end tests (no network, no client id needed).

    python3 scripts/fake_jamendo.py <port> [demo-dir]

Serves /v3.0/tracks/ with the bundled CC0 demo songs as "downloadable" tracks plus one track whose
artist does not allow downloads (it must never show up in Jam), and the audio behind /stream and /dl.
Start the Jam server with JAM_JAMENDO_CLIENT_ID=e2e JAM_JAMENDO_API_URL=http://127.0.0.1:<port>/v3.0.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8782
DEMO = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "..", "demo", "source")
TRACKS = [
    {"id": "900001", "name": "Twinkle Twinkle (e2e)", "artist_name": "Cteno Demo Band", "album_name": "Nursery", "file": "twinkle.mp3",
     "duration": 65, "audiodownload_allowed": True, "license_ccurl": "http://creativecommons.org/licenses/by-sa/3.0/"},
    {"id": "900002", "name": "Frère Jacques (e2e)", "artist_name": "Cteno Demo Band", "album_name": "Nursery", "file": "frere-jacques.mp3",
     "duration": 60, "audiodownload_allowed": True, "license_ccurl": "http://creativecommons.org/licenses/by-nc/3.0/"},
    {"id": "900003", "name": "Locked Track (must not appear)", "artist_name": "No Downloads", "album_name": "", "file": "twinkle.mp3",
     "duration": 65, "audiodownload_allowed": False, "license_ccurl": "http://creativecommons.org/licenses/by-nc-nd/3.0/"},
]


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        sys.stderr.write("fake-jamendo %s\n" % (fmt % a))

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        base = "http://127.0.0.1:%d" % PORT
        if u.path == "/v3.0/tracks/":
            rows = [t for t in TRACKS if not q.get("id") or t["id"] == q["id"]]
            if q.get("search"):
                s = q["search"].lower()
                rows = [t for t in rows if s in (t["name"] + " " + t["artist_name"]).lower()]
            res = []
            for t in rows:
                r = {k: v for k, v in t.items() if k != "file"}
                r.update(image="", shareurl="https://www.jamendo.com/track/%s" % t["id"],
                         audio="%s/stream/%s.mp3?client_id=%s" % (base, t["id"], q.get("client_id", "")),
                         audiodownload=("%s/dl/%s.mp3?client_id=%s" % (base, t["id"], q.get("client_id", "")))
                         if t["audiodownload_allowed"] else "")
                res.append(r)
            b = json.dumps({"headers": {"status": "success", "code": 0, "error_message": "", "results_count": len(res),
                                        "results_fullcount": len(res)}, "results": res}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        if u.path.startswith(("/stream/", "/dl/")):
            tid = u.path.rsplit("/", 1)[-1].split(".")[0]
            t = next((t for t in TRACKS if t["id"] == tid), None)
            if not t or (u.path.startswith("/dl/") and not t["audiodownload_allowed"]):
                self.send_error(404)
                return
            data = open(os.path.join(DEMO, t["file"]), "rb").read()
            rng = self.headers.get("Range", "")
            if rng.startswith("bytes="):
                a, _, b = rng[6:].partition("-")
                a = int(a or 0)
                b = min(int(b) if b else len(data) - 1, len(data) - 1)
                self.send_response(206)
                self.send_header("Content-Range", "bytes %d-%d/%d" % (a, b, len(data)))
                data = data[a:b + 1]
            else:
                self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
