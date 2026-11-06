// Data access. Two backends with the same shape:
//  * server: the FastAPI app (/api/...)
//  * static: a folder of pre-processed songs (demo/index.json + demo/<id>/song.json, stems/*.mp3),
//    for hosting the player on any static file server (GitHub Pages, a CDN, nginx).
// The static build sets window.JAM_CONFIG = { static: true, base: "demo/" } in config.js.
import { getLang } from "./i18n.js";
const CFG = window.JAM_CONFIG || {};
export const isStatic = !!CFG.static;
const KEY = () => localStorage.getItem("jam.key") || "";
// Management tokens of the songs this browser uploaded or imported: { songId: token }. The server returns a song's
// token once (upload / import response) and keeps only its hash; rename/delete/retry/edit send it as X-Jam-Owner.
// Another browser (or cleared site data) has no token, so the song is "someone else's" there.
const OWNED = "jam.owned";
const owned = () => { try { return JSON.parse(localStorage.getItem(OWNED)) || {}; } catch (e) { return {}; } };
const remember = m => {
  if (!m || !m.id || !m.owner_token) return m;
  const o = owned(); o[m.id] = m.owner_token;
  try { localStorage.setItem(OWNED, JSON.stringify(o)); } catch (e) {}
  const { owner_token, ...rest } = m;
  return rest;
};
const forget = id => { const o = owned(); if (id in o) { delete o[id]; localStorage.setItem(OWNED, JSON.stringify(o)); } };
const OWN = id => { const tk = owned()[id]; return tk ? { "X-Jam-Owner": tk } : {}; };

async function j(url, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (KEY()) headers["X-Jam-Key"] = KEY();
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
  const r = await fetch(url, { ...opts, headers });
  let body = null;
  try { body = r.status === 204 ? null : await r.json(); } catch (e) {}
  if (!r.ok) {
    const msg = body && (body.detail || body.error) ? (body.detail || body.error) : `HTTP ${r.status}`;
    const err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg)); err.status = r.status; err.body = body; throw err;
  }
  return body;
}

export const api = {
  async info() {
    if (isStatic) return { mode: "static", upload: false, ai: { configured: false }, static: true };
    return j("/api/info");
  },
  async list(q = "") {
    if (isStatic) {
      const idx = await j(`${CFG.base}index.json`);
      const ql = q.trim().toLowerCase();
      return idx.songs.filter(s => !ql || (s.title || "").toLowerCase().includes(ql) || (s.artist || "").toLowerCase().includes(ql));
    }
    return (await j(`/api/songs?q=${encodeURIComponent(q)}`)).songs;
  },
  song(id) { return isStatic ? j(`${CFG.base}${id}/song.json`) : j(`/api/songs/${id}/song.json`); },
  meta(id) { return j(`/api/songs/${id}`); },
  stemBase(id) { return isStatic ? `${CFG.base}${id}/stems/` : `/api/songs/${id}/stems/`; },
  upload(file, fields, onProgress) {
    return new Promise((resolve, reject) => {
      const fd = new FormData();
      fd.append("file", file, file.name || "recording");
      Object.entries(fields).forEach(([k, v]) => v && fd.append(k, v));
      const x = new XMLHttpRequest();
      x.open("POST", "/api/songs");
      if (KEY()) x.setRequestHeader("X-Jam-Key", KEY());
      x.upload.onprogress = e => e.lengthComputable && onProgress && onProgress(e.loaded / e.total);
      x.onload = () => {
        let b = null; try { b = JSON.parse(x.responseText); } catch (e) {}
        if (x.status >= 200 && x.status < 300) resolve(remember(b));
        else { const err = new Error((b && b.detail) || `HTTP ${x.status}`); err.status = x.status; reject(err); }
      };
      x.onerror = () => reject(new Error("network error"));
      x.send(fd);
    });
  },
  // may this browser manage the song? (its token, or the server passphrase on a passphrase-protected server)
  canManage(m, info) {
    if (isStatic || !m) return false;
    if (info && info.needs_key && KEY()) return true;
    return !!owned()[m.id];
  },
  rename(id, fields) { return j(`/api/songs/${id}`, { method: "PATCH", json: fields, headers: OWN(id) }); },
  async remove(id) {
    try { await j(`/api/songs/${id}`, { method: "DELETE", headers: OWN(id) }); }
    catch (e) { if (e.status !== 404) throw e; }
    forget(id);
  },
  retry(id) { return j(`/api/songs/${id}/retry`, { method: "POST", headers: OWN(id) }); },
  review(id) { return j(`/api/songs/${id}/review?lang=${getLang()}`, { method: "POST", headers: OWN(id) }); },
  edits(id, patches) { return j(`/api/songs/${id}/edits`, { method: "POST", json: { patches }, headers: OWN(id) }); },
  revisions(id, ids, status, source) { return j(`/api/songs/${id}/revisions`, { method: "POST", json: { ids, status, source }, headers: OWN(id) }); },
  events(onSongs) {
    if (isStatic || !window.EventSource) return () => {};
    const es = new EventSource("/api/events");
    es.onmessage = e => { try { onSongs(JSON.parse(e.data).songs); } catch (_) {} };
    return () => es.close();
  },
  // 热度: tell the server a play/jam started. The session id is per browser tab, so the server can
  // ignore the same listener restarting the same song within 30 s.
  play(id) {
    if (isStatic) return Promise.resolve(null);
    let s = sessionStorage.getItem("jam.session");
    if (!s) { s = Array.from(crypto.getRandomValues(new Uint8Array(12)), b => b.toString(16).padStart(2, "0")).join(""); sessionStorage.setItem("jam.session", s); }
    return j(`/api/songs/${id}/play`, { method: "POST", json: { session: s } });
  },
  jamendoSearch(q, offset = 0) { return j(`/api/jamendo/search?q=${encodeURIComponent(q || "")}&offset=${offset || 0}`); },
  jamendoChart(kind) { return j(`/api/jamendo/charts/${encodeURIComponent(kind)}`); },
  jamendoPreview(id) { return `/api/jamendo/preview/${encodeURIComponent(id)}.mp3`; },
  async jamendoImport(id, lang) { return remember(await j("/api/jamendo/import", { method: "POST", json: { id, lang } })); },
  setKey(k) { localStorage.setItem("jam.key", k || ""); },
};
