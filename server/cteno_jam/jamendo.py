"""Jamendo free-music catalogue (optional): search, preview and import tracks whose artists allow downloads.

Jamendo (https://www.jamendo.com) hosts independent music under Creative Commons licenses and has a
public API (https://developer.jamendo.com/v3.0). The server talks to it with the client id from
JAM_JAMENDO_CLIENT_ID, so the id never reaches the browser; without it the whole feature is hidden.

Only tracks with ``audiodownload_allowed`` and a download URL are ever shown or imported, and every
imported song keeps its license (name + URL), the artist and the Jamendo page in its meta.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

UA = "CtenoJam/0.1 (self-hosted; jamendo)"
_preview: Dict[str, tuple] = {}   # track id -> (stream url, time) from recent searches


class JamendoError(RuntimeError):
    pass


def _get(cfg, path: str, params: Dict) -> Dict:
    q = {"client_id": cfg.jamendo_client_id, "format": "json", **{k: v for k, v in params.items() if v not in (None, "")}}
    url = cfg.jamendo_api_url.rstrip("/") + path + "?" + urllib.parse.urlencode(q)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15) as r:
            body = json.load(r)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise JamendoError("Jamendo is not reachable right now (%s)" % type(e).__name__)
    h = body.get("headers") or {}
    if h.get("status") not in (None, "success"):
        # never echo the request URL: it carries the client id
        raise JamendoError("Jamendo said: %s" % (h.get("error_message") or h.get("status")))
    return body


def license_name(url: str) -> str:
    """'http://creativecommons.org/licenses/by-nc-sa/3.0/' -> 'CC BY-NC-SA 3.0'."""
    u = (url or "").lower()
    if "publicdomain/zero" in u:
        return "CC0 1.0"
    m = re.search(r"creativecommons\.org/licenses/([a-z-]+)/([0-9.]+)", u)
    if m:
        return "CC %s %s" % (m.group(1).upper(), m.group(2))
    return "Jamendo license"


def downloadable(t: Dict) -> bool:
    return bool(t.get("audiodownload_allowed")) and bool(t.get("audiodownload"))


def view(t: Dict) -> Dict:
    """What the browser may see about a track (no URLs that carry the client id)."""
    lic = t.get("license_ccurl") or ""
    return {"id": str(t.get("id")), "title": t.get("name") or "", "artist": t.get("artist_name") or "",
            "album": t.get("album_name") or "", "duration": t.get("duration") or 0,
            "image": t.get("image") or t.get("album_image") or "", "license": license_name(lic),
            "license_url": lic, "page": t.get("shareurl") or "", "listens": listens(t)}


def listens(t: Dict) -> int:
    """Jamendo's all-time listen counter (include=stats -> stats.rate_listened_total); 0 when absent."""
    try:
        return max(0, int((t.get("stats") or {}).get("rate_listened_total") or 0))
    except (TypeError, ValueError):
        return 0


def search(cfg, q: str = "", offset: int = 0, limit: int = 20) -> Dict:
    # The API has no "downloadable only" filter; we drop the others below, so a page may hold fewer.
    # Most popular first, all time: the order the mixed search list keeps for Jamendo results.
    params = {"limit": max(1, min(limit, 50)), "offset": max(0, offset), "include": "licenses stats", "fullcount": "true",
              "audioformat": "mp31", "audiodlformat": "mp32", "imagesize": 100, "order": "popularity_total"}
    if q.strip():
        params["search"] = q.strip()[:100]
    body = _get(cfg, "/tracks/", params)
    out: List[Dict] = []
    now = time.time()
    for t in body.get("results") or []:
        if not downloadable(t):
            continue                     # only tracks the artist lets people download
        out.append(view(t))
        if t.get("audio"):
            _preview[str(t["id"])] = (t["audio"], now)
    if len(_preview) > 2000:
        for k in sorted(_preview, key=lambda k: _preview[k][1])[:1000]:
            _preview.pop(k, None)
    total = (body.get("headers") or {}).get("results_fullcount")
    return {"results": out, "offset": params["offset"], "next": params["offset"] + params["limit"]
            if len(body.get("results") or []) >= params["limit"] else None, "total": total}


def track(cfg, tid: str) -> Optional[Dict]:
    """Raw track record, or None when it does not exist or is not downloadable."""
    body = _get(cfg, "/tracks/", {"id": tid, "include": "licenses", "audioformat": "mp31", "audiodlformat": "mp32"})
    for t in body.get("results") or []:
        if str(t.get("id")) == str(tid) and downloadable(t):
            if t.get("audio"):
                _preview[str(tid)] = (t["audio"], time.time())
            return t
    return None


def preview_url(cfg, tid: str) -> Optional[str]:
    hit = _preview.get(tid)
    if hit and time.time() - hit[1] < 3600:
        return hit[0]
    t = track(cfg, tid)
    return t.get("audio") if t else None


def open_url(url: str, headers: Optional[Dict] = None, timeout: int = 30):
    h = {"User-Agent": UA, **(headers or {})}
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout)
