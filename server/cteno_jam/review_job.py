"""Run the AI review for a stored song and record the result. Used by the worker and the API."""
from __future__ import annotations

import logging
import time

from . import config, store

log = logging.getLogger("cteno_jam.review")


def review(st: store.Store, sid: str, cfg: config.Config) -> dict:
    if not cfg.ai_configured:
        st.update(sid, ai={"status": "not_configured"})
        return {"ok": False, "error": "not configured"}
    from . import review as rv
    st.update(sid, ai={"status": "running", "started": int(time.time()), "error": None})
    song = st.song(sid)
    try:
        res = rv.run_review_sync(song["analysis"], base_url=cfg.ai_base_url, model=cfg.ai_model,
                                 api_key=cfg.ai_api_key, api_format=cfg.ai_api_format,
                                 timeout_s=cfg.ai_timeout_s, sdk_home=cfg.ai_sdk_home or None,
                                 lang=st.meta(sid).get("lang"))
    except Exception as e:  # noqa: BLE001 — the review is optional and never fails the song
        log.exception("[%s] review crashed", sid)
        msg = "%s: %s" % (type(e).__name__, str(e)[:300])
        st.update(sid, ai={"status": "failed", "error": msg})
        return {"ok": False, "error": msg}
    if not res.ok:
        st.update(sid, ai={"status": "failed", "error": res.error, "seconds": round(res.seconds, 1), "model": res.model})
        return res.to_dict()
    batch = "ai-%d" % int(time.time())
    st.drop_revisions(sid, "ai")
    _, rejected_late = st.add_patches(sid, res.accepted, "ai", batch)
    info = res.to_dict()
    info["rejected"] = res.rejected + [dict(x, late=True) for x in rejected_late]
    st.update(sid, ai={"status": "done", "summary": res.summary, "batch": batch, "model": res.model,
                       "seconds": round(res.seconds, 1), "accepted": len(res.accepted) - len(rejected_late),
                       "rejected": info["rejected"], "tool_calls": res.tool_calls, "finished": int(time.time())})
    log.info("[%s] AI review: %d accepted, %d rejected in %.1fs", sid, len(res.accepted), len(info["rejected"]), res.seconds)
    return info
