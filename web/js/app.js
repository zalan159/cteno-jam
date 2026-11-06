// Cteno Jam web app: library, player/chart, big screen, remote, print, editor, AI review panel.
import { api, isStatic } from "./api.js";
import { t, getLang, setLang } from "./i18n.js";
import { Player, STEMS } from "./player.js";
import { Sync, randomRoom } from "./sync.js";
import { buildChart, chartOptions, aiTouched, sectionAt, chordAt } from "./chart.js";
import { diagramSVG } from "./diagrams.js";
import { parseChord, transpose } from "./theory.js";
import { mixResults, sortLocal, playsLabel } from "./popularity.js";
import { encryptedFamily, acceptFor, isWeChat, checkPicked, pickRecordingType, extForType, micErrorKey } from "./upload_check.js";
import qrcode from "../vendor/qrcode.mjs";

const $ = (s, el = document) => el.querySelector(s);
const app = $("#app");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const errors = [];
window.addEventListener("error", e => errors.push(String(e.message)));
window.addEventListener("unhandledrejection", e => errors.push(String(e.reason && e.reason.message || e.reason)));

let INFO = { upload: false, ai: { configured: false } };
let cleanup = [];
const onCleanup = f => cleanup.push(f);
function teardown() { cleanup.forEach(f => { try { f(); } catch (e) {} }); cleanup = []; }

function toast(msg, ms = 2200) {
  const d = document.createElement("div"); d.className = "toast"; d.textContent = msg; document.body.appendChild(d);
  setTimeout(() => d.remove(), ms);
}
function qrSVG(text) {
  const q = qrcode(0, "M"); q.addData(text); q.make();
  return q.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
}
function publicBase() {
  const b = (INFO.public_url || "").replace(/\/$/, "");
  return b || location.origin + location.pathname.replace(/index\.html$/, "").replace(/\/$/, "");
}
const hue = s => [...String(s)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7);

// ------------------------------------------------------------------ routing
function parseRoute() {
  const h = location.hash.replace(/^#\/?/, "");
  const [path, qs] = h.split("?");
  const q = new URLSearchParams(qs || "");
  const p = path.split("/").filter(Boolean);
  return { p, q };
}
function go(hash) { if (location.hash !== hash) location.hash = hash; else route(); }
window.addEventListener("hashchange", route);

async function route() {
  teardown();
  const { p, q } = parseRoute();
  window.scrollTo(0, 0);
  if (p[0] === "s" && p[1]) {
    const view = p[2] || "sheet";
    if (view === "print") return printView(p[1], q);
    return playerView(p[1], view, q);
  }
  if (p[0] === "r" && p[1]) return remoteView(p[1], q);
  return libraryView(q);
}

// ------------------------------------------------------------------ library
function topBar(inner) {
  return `<div class="top">${inner}<button class="ghost" id="langBtn" aria-label="language">${t("lang")}</button></div>`;
}
function bindLang(rerender) {
  const b = $("#langBtn"); if (b) b.onclick = () => { setLang(getLang() === "zh" ? "en" : "zh"); rerender(); };
}

function stageLabel(m) {
  if (m.status === "ready") return t("st_ready");
  if (m.status === "failed") return t("st_failed");
  if (m.status === "queued") return t("st_queued") + (m.queue_position ? " · " + t("queue_pos", { n: m.queue_position - 1 > 0 ? m.queue_position - 1 : 0 }) : "");
  if (m.status === "processing") return `${t("st_processing")} · ${t("stage_" + (m.stage || "queued"))} · ${Math.round((m.progress || 0) * 100)}%`;
  return t("st_" + m.status);
}

async function libraryView(q) {
  document.title = "Cteno Jam";
  // One search box for everything: the local library (filtered here) and, when the server has a Jamendo
  // client id, Jamendo's free catalogue (asked on the server, debounced). Both are shown in one list,
  // most played first — see popularity.js for how local plays and Jamendo listens are compared.
  let songs = [], query = q.get("q") || "", jm = { q: "", results: [], loading: false, error: null };
  let jmTimer = 0, jmSeq = 0, previewId = null;
  const audio = new Audio(); audio.preload = "none"; audio.id = "jmAudio";
  onCleanup(() => { clearTimeout(jmTimer); audio.pause(); audio.removeAttribute("src"); });
  const render = () => {
    app.innerHTML = topBar(`<div class="brand"><i></i>${t("app")}</div><div class="grow"></div>`) + `
      <main class="lib">
        <p class="hero">${esc(t("tagline"))}</p>
        <input type="search" id="q" placeholder="${esc(t(INFO.jamendo ? "search_all" : "search"))}" value="${esc(query)}" autocomplete="off" enterkeyhint="search">
        ${INFO.upload ? uploadCard() : isStatic ? "" : `<div class="card muted">${esc(t("no_upload"))}</div>`}
        <div class="songs" id="songs"></div>
      </main>`;
    bindLang(render);
    $("#q").oninput = e => { query = e.target.value; lastHtml = ""; drawSongs(); askJamendo(); };
    $("#q").onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); clearTimeout(jmTimer); askJamendo(0); e.target.blur(); } };
    if (INFO.upload) bindUpload();
    lastHtml = ""; drawSongs();
  };
  // Jamendo results for the current query (only when the server has a client id; never on an empty query)
  const askJamendo = (delay = 400) => {
    clearTimeout(jmTimer);
    const ql = query.trim();
    if (!INFO.jamendo || isStatic || ql.length < 2) { jmSeq++; jm = { q: "", results: [], loading: false, error: null }; lastHtml = ""; drawSongs(); return; }
    if (jm.q === ql && !jm.error) return;
    jmTimer = setTimeout(async () => {
      const seq = ++jmSeq;
      jm = { q: ql, results: jm.q === ql ? jm.results : [], loading: true, error: null }; lastHtml = ""; drawSongs();
      try {
        const r = await api.jamendoSearch(ql, 0);
        if (seq !== jmSeq) return;
        jm = { q: ql, results: r.results || [], loading: false, error: null };
      } catch (e) {
        if (seq !== jmSeq) return;
        jm = { q: ql, results: [], loading: false, error: e.message };   // local results still show; just a quiet note
      }
      lastHtml = ""; drawSongs();
    }, delay);
  };
  let lastHtml = "";
  const localRow = m => {
    const busy = m.status === "queued" || m.status === "processing" || m.status === "uploading";
    const ai = m.ai && m.ai.status === "done" ? `<span class="badge ai">AI ✓ ${m.ai.accepted || 0}</span>` : "";
    const fromJm = m.source && m.source.kind === "jamendo";
    return `<div class="song" data-kind="local" data-id="${esc(m.id)}">
      <div class="art" style="background:hsl(${hue(m.id)} 70% 62%)">${esc((m.title || "?").trim()[0] || "?")}</div>
      <div class="info">
        <div class="t">${esc(m.title)}${m.demo ? `<span class="badge">${esc(t("demo_badge"))}</span>` : ""}${ai}</div>
        <div class="m ${m.status === "failed" ? "err" : ""}">${esc(m.artist ? m.artist + " · " : "")}${m.duration ? fmt(m.duration) + " · " : ""}${esc(stageLabel(m))}</div>
        <div class="m src-line"><span class="plays" title="${esc(t("plays_title_local"))}">${esc(playsLabel(m.plays || 0, getLang()))}</span>
          <span class="badge srcb ${fromJm ? "jmb" : "localb"}">${esc(t(fromJm ? "src_badge_jamendo_lib" : "src_badge_local"))}</span>${!m.demo && m.license ? `<a class="badge lic" href="${esc(m.license_url || (m.source && m.source.page) || "#")}" target="_blank" rel="noopener" title="${esc(t("jm_license"))}">${esc(m.license)}</a>` : ""}</div>
        ${m.status === "failed" && m.error ? `<div class="m err">${esc(m.error)}</div>` : ""}
        ${busy ? `<div class="prog"><i style="width:${Math.round((m.progress || 0) * 100)}%"></i></div>` : ""}
      </div>
      <div class="acts">
        ${m.status === "ready" ? `<button class="primary" data-act="open">${esc(t("open"))}</button>` : ""}
        ${m.status === "failed" && !isStatic ? `<button data-act="retry">${esc(t("retry"))}</button>` : ""}
        ${!isStatic && INFO.upload ? `<button class="ghost" data-act="menu" aria-label="more">⋯</button>` : ""}
      </div></div>`;
  };
  const jmRow = r => `<div class="song" data-kind="jamendo" data-id="${esc(r.id)}">
      ${r.image ? `<img class="art" src="${esc(r.image)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<div class="art" style="background:hsl(${hue(r.id)} 60% 55%)">${esc((r.title || "?").trim()[0] || "?")}</div>`}
      <div class="info">
        <div class="t">${esc(r.title)}</div>
        <div class="m">${esc(r.artist)}${r.duration ? " · " + fmt(r.duration) : ""}</div>
        <div class="m src-line"><span class="plays" title="${esc(t("plays_title_jamendo"))}">${esc(playsLabel(r.listens || 0, getLang()))}</span>
          <a class="badge srcb jmb" href="${esc(r.page || "https://www.jamendo.com")}" target="_blank" rel="noopener">Jamendo</a><a class="badge lic jmLic" href="${esc(r.license_url || r.page)}" target="_blank" rel="noopener" title="${esc(t("jm_license"))}">${esc(r.license)}</a></div>
      </div>
      <div class="acts">
        <button class="jmPlay" data-act="preview" aria-label="${esc(t("jm_play"))}">${previewId === r.id && !audio.paused ? "❚❚" : "▶"}</button>
        <button class="primary jmUse" data-act="use">${esc(t("jm_use"))}</button>
      </div></div>`;
  const drawSongs = () => {
    const el = $("#songs"); if (!el) return;
    const ql = query.trim().toLowerCase();
    const local = songs.filter(s => !ql || (s.title || "").toLowerCase().includes(ql) || (s.artist || "").toLowerCase().includes(ql));
    const jmOn = INFO.jamendo && !isStatic && ql.length >= 2 && jm.q.toLowerCase() === ql;
    const rows = ql ? mixResults(local, jmOn ? jm.results : []) : sortLocal(local).map(song => ({ kind: "local", song }));
    window.__jamList = rows.map(r => r.kind === "local" ? { kind: "local", id: r.song.id, title: r.song.title, plays: r.song.plays || 0, score: r.score }
      : { kind: "jamendo", id: r.track.id, title: r.track.title, listens: r.track.listens || 0, license: r.track.license, score: r.score });
    let note = "";
    if (INFO.jamendo && ql.length >= 2) {
      if (jm.loading) note = `<div class="muted jmNote">${esc(t("jm_searching"))}</div>`;
      else if (jm.error) note = `<div class="muted jmNote">${esc(t("jm_unreachable"))}</div>`;
      else if (jmOn) note = `<div class="muted jmNote">${esc(t("jm_from"))}</div>`;
    }
    if (!rows.length) {
      const html = (jm.loading ? "" : `<div class="card muted">${esc(t(ql ? "nothing_found" : "empty"))}</div>`) + note;
      if (html !== lastHtml) { lastHtml = html; el.innerHTML = html; }
      return;
    }
    const html = rows.map(r => r.kind === "local" ? localRow(r.song) : jmRow(r.track)).join("") + note;
    if (html === lastHtml) return; // nothing changed: keep the DOM (and any tap in progress)
    lastHtml = html;
    el.innerHTML = html;
    el.querySelectorAll('.song[data-kind="local"]').forEach(row => {
      const id = row.dataset.id, m = songs.find(s => s.id === id);
      row.querySelectorAll("button").forEach(b => b.onclick = async ev => {
        ev.stopPropagation();
        const act = b.dataset.act;
        try {
          if (act === "open") go(`#/s/${id}`);
          if (act === "retry") { await api.retry(id); list(); }
          if (act === "menu") songMenu(m);
        } catch (e) { toast(e.message); }
      });
      row.querySelectorAll("a").forEach(a => a.onclick = ev => ev.stopPropagation());
      row.onclick = () => m && m.status === "ready" && go(`#/s/${id}`);
    });
    el.querySelectorAll('.song[data-kind="jamendo"]').forEach(row => {
      const id = row.dataset.id, r = jm.results.find(x => x.id === id);
      row.querySelectorAll("a").forEach(a => a.onclick = ev => ev.stopPropagation());
      const use = async () => {
        if (!r || row.classList.contains("busy")) return;
        if ($("#upKey")) api.setKey($("#upKey").value);
        row.classList.add("busy"); const b = row.querySelector(".jmUse"); b.disabled = true; b.textContent = t("jm_importing");
        try {
          const m = await api.jamendoImport(id, getLang());
          if (previewId === id) audio.pause();
          if (m.status === "ready") return go(`#/s/${m.id}`);
          toast(t("jm_added", { t: r.title }), 3000);
          await list();
        } catch (e) { toast(e.message, 4000); row.classList.remove("busy"); b.disabled = false; b.textContent = t("jm_use"); }
      };
      row.querySelector(".jmUse").onclick = ev => { ev.stopPropagation(); use(); };
      row.querySelector(".jmPlay").onclick = ev => {
        ev.stopPropagation();
        if (previewId === id && !audio.paused) { audio.pause(); return; }
        previewId = id; audio.src = api.jamendoPreview(id); audio.play().catch(e => toast(e.message));
      };
      row.onclick = () => use();
    });
  };
  const setPreviewBtns = () => document.querySelectorAll('.song[data-kind="jamendo"]').forEach(row => {
    const on = row.dataset.id === previewId && !audio.paused, b = row.querySelector(".jmPlay");
    if (b) { b.textContent = on ? "❚❚" : "▶"; b.classList.toggle("on", on); b.setAttribute("aria-label", t(on ? "jm_pause" : "jm_play")); }
  });
  audio.onplay = audio.onpause = audio.onended = setPreviewBtns;
  window.__jamPreview = audio;
  const list = async () => { try { songs = await api.list(""); lastHtml = ""; drawSongs(); } catch (e) { $("#songs").innerHTML = `<div class="card err">${esc(e.message)}</div>`; } };
  render();
  await list();
  askJamendo(0);
  onCleanup(api.events(s => { songs = s; drawSongs(); }));
}

function songMenu(m) {
  panel(`<h3>${esc(m.title)}</h3>
    <div class="form">
      <label>${esc(t("title"))}<input type="text" id="rnT" value="${esc(m.title)}"></label>
      <label>${esc(t("artist"))}<input type="text" id="rnA" value="${esc(m.artist || "")}"></label>
      <div class="row"><button class="primary" id="rnSave">${esc(t("rename"))}</button><div class="grow"></div>
      ${m.demo ? "" : `<button id="rnDel" class="err">${esc(t("delete"))}</button>`}</div>
    </div>`, close => {
    $("#rnSave").onclick = async () => { try { await api.rename(m.id, { title: $("#rnT").value, artist: $("#rnA").value }); close(); route(); } catch (e) { toast(e.message); } };
    const d = $("#rnDel");
    if (d) d.onclick = async () => { if (!confirm(t("confirm_delete", { t: m.title }))) return; try { await api.remove(m.id); close(); route(); } catch (e) { toast(e.message); } };
  });
}

const MIC_SVG = `<svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/></svg>`;

function uploadCard() {
  const ua = navigator.userAgent, android = /Android/i.test(ua);
  return `<div class="card">
    <label class="drop" id="drop" role="button" tabindex="0" aria-label="${esc(t("upload_btn"))}">
      <input type="file" id="file" class="vh" accept="${esc(acceptFor(ua))}">
      <span class="upbtn" id="upBtn"><svg class="upic" aria-hidden="true" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V4"/><path d="M7 9l5-5 5 5"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/></svg><span id="upLabel">${esc(t("upload_btn"))}</span></span>
      <span class="uphint" id="upHint">${esc(t("upload_hint"))}</span>
      <span class="upfile hidden" id="upFile"></span></label>
    <div class="srcs" id="srcs">
      <span class="srcs-or">${esc(t("src_or"))}</span>
      <div class="srcs-btns">
        <button type="button" class="src" id="recBtn">${MIC_SVG}<span>${esc(t("src_record"))}</span></button>
      </div>
    </div>
    <details class="wxtip" id="wxTip"${isWeChat(ua) ? " open" : ""}><summary>${esc(t("wx_tip_title"))}</summary>
      <p>${esc(t(android ? "wx_tip_android" : "wx_tip_ios"))}</p>${isWeChat(ua) ? `<p>${esc(t("wx_tip_inwx"))}</p>` : ""}</details>
    <div class="form hidden" id="upForm">
      <audio id="upPreview" class="hidden" controls preload="metadata"></audio>
      <input type="text" id="upTitle" placeholder="${esc(t("title"))}">
      <input type="text" id="upArtist" placeholder="${esc(t("artist"))}">
      <details id="upLyricsBox"><summary>${esc(t("lyrics_opt"))}</summary><textarea id="upLyrics" rows="6" style="margin-top:8px"></textarea></details>
      ${INFO.needs_key ? `<input type="password" id="upKey" placeholder="${esc(t("passphrase"))}" value="${esc(localStorage.getItem("jam.key") || "")}">` : ""}
      <button class="primary" id="upGo">${esc(t("start_upload"))}</button>
      <div class="prog hidden" id="upProg"><i style="width:0"></i></div><div id="upMsg" class="muted"></div>
    </div></div>`;
}
function bindUpload() {
  const f = $("#file"), form = $("#upForm"), drop = $("#drop");
  let file = null, previewUrl = null;
  const setPreview = blob => {
    const a = $("#upPreview"); if (!a) return;
    if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; }
    if (blob) { previewUrl = URL.createObjectURL(blob); a.src = previewUrl; a.classList.remove("hidden"); }
    else { a.removeAttribute("src"); a.classList.add("hidden"); }
  };
  onCleanup(() => previewUrl && URL.revokeObjectURL(previewUrl));
  const refuse = msg => {
    file = null; f.value = ""; form.classList.add("hidden"); setPreview(null);
    $("#upFile").textContent = msg; $("#upFile").classList.add("err"); $("#upFile").classList.remove("hidden");
  };
  // fl: a File from the picker / a drop, or a recording. opts.recorded keeps the player visible.
  const pick = (fl, opts = {}) => {
    if (!fl) return;
    $("#upFile").textContent = t("picked", { f: fl.name }); $("#upFile").classList.remove("hidden");
    const fam = encryptedFamily(fl.name);
    if (fam) return refuse(t("enc_file", { app: t("app_" + fam) }));  // encrypted music-app download: say so now
    if (checkPicked(fl.name, fl.type) === "not_audio") return refuse(t("not_audio", { f: fl.name }));
    $("#upFile").classList.remove("err");
    file = fl; form.classList.remove("hidden");
    $("#upLabel").textContent = t("upload_change");
    setPreview(opts.recorded ? fl : null);
    if (!$("#upTitle").value || opts.recorded) $("#upTitle").value = opts.title || fl.name.replace(/\.[^.]+$/, "").replace(/[_]+/g, " ");
    $("#upMsg").textContent = ""; $("#upMsg").className = "muted";
  };
  f.onchange = () => pick(f.files[0]);
  ["dragenter", "dragover"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", ev => pick(ev.dataTransfer.files[0]));
  drop.addEventListener("keydown", ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); f.click(); } });
  $("#recBtn").onclick = () => recordPanel((fl, title) => pick(fl, { recorded: true, title }));
  $("#upGo").onclick = async () => {
    if (!file) return;
    if ($("#upKey")) api.setKey($("#upKey").value);
    $("#upGo").disabled = true; $("#upProg").classList.remove("hidden"); $("#upMsg").textContent = "";
    try {
      await api.upload(file, { title: $("#upTitle").value, artist: $("#upArtist").value, lyrics: $("#upLyrics").value, lang: getLang() },
        p => { $("#upProg i").style.width = (p * 100).toFixed(0) + "%"; $("#upMsg").textContent = t("uploading", { p: Math.round(p * 100) }); });
      route();
    } catch (e) {
      $("#upMsg").textContent = e.message; $("#upMsg").className = "err"; $("#upGo").disabled = false;
    }
  };
}

// ------------------------------------------------------------------ record in the browser
// MediaRecorder: iOS Safari gives AAC in MP4 (audio/mp4), Chrome/Android Opus in WebM. Either way the
// result becomes a File and goes through the normal upload (the server measures streamed recordings).
function recordPanel(onDone) {
  const maxS = Math.min(INFO.max_duration_s || 900, 900);
  panel(`<h3>${esc(t("rec_title"))}</h3>
    <p class="muted" style="margin:0 0 10px;font-size:14px">${esc(t("rec_desc"))}</p>
    <div class="rec" id="rec">
      <div class="recTime" id="recTime">0:00</div>
      <div class="meter"><i id="recLevel"></i></div>
      <div id="recMsg" class="recMsg muted"></div>
      <audio id="recPlay" class="hidden" controls></audio>
      <div class="row recBtns">
        <button class="primary recGo" id="recStart">${MIC_SVG}<span>${esc(t("rec_start"))}</span></button>
        <button class="recGo hidden" id="recStop"><span class="dot"></span><span>${esc(t("rec_stop"))}</span></button>
        <button class="hidden" id="recAgain">${esc(t("rec_again"))}</button>
        <button class="primary hidden" id="recUse">${esc(t("rec_use"))}</button>
      </div>
      <button class="ghost" id="recCancel">${esc(t("rec_cancel"))}</button>
    </div>`, (close, el) => {
    let stream = null, rec = null, chunks = [], t0 = 0, timer = 0, blob = null, url = null, ac = null, raf = 0, dur = 0;
    const R = window.__jamRec = { state: "idle", type: "", error: null, seconds: 0, size: 0 };
    const msg = (text, err) => { $("#recMsg").textContent = text || ""; $("#recMsg").className = "recMsg " + (err ? "err" : "muted"); };
    const show = (ids, on) => ids.forEach(id => $(id) && $(id).classList.toggle("hidden", !on));
    const stopAll = () => {
      clearInterval(timer); cancelAnimationFrame(raf);
      if (rec && rec.state !== "inactive") { try { rec.stop(); } catch (e) {} }
      if (stream) stream.getTracks().forEach(tr => tr.stop());
      stream = null;
      if (ac) { ac.close().catch(() => {}); ac = null; }
      $("#recLevel") && ($("#recLevel").style.width = "0");
    };
    const prevSession = navigator.audioSession ? navigator.audioSession.type : null;
    const setSession = ty => { try { if (navigator.audioSession && ty) navigator.audioSession.type = ty; } catch (e) {} };
    const cleanupRec = () => { stopAll(); if (url) URL.revokeObjectURL(url); url = null; setSession(prevSession); };
    const fail = (key, e) => { R.state = "error"; R.error = key; stopAll(); msg(t(key, { e: e && (e.message || e.name) || "" }), true); show(["#recStart"], true); show(["#recStop"], false); };
    const meter = () => {
      try {
        ac = new (window.AudioContext || window.webkitAudioContext)();
        const an = ac.createAnalyser(); an.fftSize = 512; ac.createMediaStreamSource(stream).connect(an);
        const buf = new Uint8Array(an.fftSize);
        const tick = () => { an.getByteTimeDomainData(buf); let m = 0; for (const v of buf) m = Math.max(m, Math.abs(v - 128)); const el = $("#recLevel"); if (el) el.style.width = Math.min(100, m * 1.6) + "%"; raf = requestAnimationFrame(tick); };
        tick();
      } catch (e) {}
    };
    $("#recStart").onclick = async () => {
      msg("");
      if (!window.isSecureContext) return fail("rec_insecure");
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) return fail("rec_unsupported");
      // The player sets audioSession.type = "playback" (plays with the iPhone silent switch on); Safari
      // refuses to capture in that category, so switch to play-and-record while the panel is open.
      setSession("play-and-record");
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
      } catch (e) { return fail(micErrorKey(e), e); }
      const type = pickRecordingType(ty => MediaRecorder.isTypeSupported(ty));
      try { rec = type ? new MediaRecorder(stream, { mimeType: type, audioBitsPerSecond: 128000 }) : new MediaRecorder(stream); }
      catch (e) { try { rec = new MediaRecorder(stream); } catch (e2) { return fail("rec_failed", e2); } }
      chunks = []; blob = null;
      rec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
      rec.onerror = e => fail("rec_failed", e.error || e);
      rec.onstop = () => {
        if (R.state === "error" || R.state === "cancelled") return;
        dur = (performance.now() - t0) / 1000;
        const ty = (rec.mimeType || type || (chunks[0] && chunks[0].type) || "audio/mp4").split(";")[0];
        blob = new Blob(chunks, { type: ty });
        Object.assign(R, { state: "done", type: ty, seconds: +dur.toFixed(1), size: blob.size });
        if (url) URL.revokeObjectURL(url);
        url = URL.createObjectURL(blob); $("#recPlay").src = url;
        show(["#recPlay", "#recAgain"], true); show(["#recStop"], false);
        if (dur < 5) { msg(t("rec_short", { s: dur.toFixed(1) }), true); show(["#recUse"], false); }
        else { msg((dur >= maxS - 0.5 ? t("rec_max", { m: Math.round(maxS / 60) }) + " " : "") + t("rec_done", { t: fmt(dur) })); show(["#recUse"], true); }
      };
      rec.start(1000);  // timeslice: Safari otherwise keeps everything in one huge chunk
      t0 = performance.now(); R.state = "recording"; R.type = rec.mimeType || type;
      show(["#recStart", "#recPlay", "#recAgain", "#recUse"], false); show(["#recStop"], true);
      $("#rec").classList.add("live");
      timer = setInterval(() => {
        const s = (performance.now() - t0) / 1000; R.seconds = +s.toFixed(1);
        $("#recTime").textContent = fmt(s); msg(t("rec_live", { t: fmt(s) }));
        if (s >= maxS) $("#recStop").click();
      }, 250);
      meter();
    };
    $("#recStop").onclick = () => { $("#rec").classList.remove("live"); stopAll(); };
    $("#recAgain").onclick = () => { $("#recTime").textContent = "0:00"; $("#recStart").click(); };
    $("#recUse").onclick = () => {
      if (!blob) return;
      const ext = extForType(blob.type), d = new Date();
      const stamp = `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, "0")}${String(d.getMinutes()).padStart(2, "0")}`;
      const name = `recording-${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}-${String(d.getHours()).padStart(2, "0")}${String(d.getMinutes()).padStart(2, "0")}.${ext}`;
      let fl; try { fl = new File([blob], name, { type: blob.type }); } catch (e) { fl = blob; fl.name = name; }
      R.state = "used"; cleanupRec(); close();
      onDone(fl, t("rec_name", { d: stamp }));
    };
    $("#recCancel").onclick = () => close();
    el.addEventListener("close", () => { if (R.state !== "used") R.state = "cancelled"; cleanupRec(); });
  });
}

function panel(html, bind) {
  const scrim = document.createElement("div"); scrim.className = "scrim";
  const p = document.createElement("div"); p.className = "sheetpanel"; p.innerHTML = html;
  document.body.append(scrim, p);
  // "close" lets a panel release what it holds (the microphone, a preview) however it is dismissed
  const close = () => { if (!p.isConnected) return; scrim.remove(); p.remove(); p.dispatchEvent(new Event("close")); };
  scrim.onclick = close;
  bind && bind(close, p);
  onCleanup(close);
  return { close, el: p };
}

// ------------------------------------------------------------------ player (sheet + stage)
const prefsKey = id => `jam.prefs.${id}`;
const loadPrefs = id => { try { return JSON.parse(localStorage.getItem(prefsKey(id))) || {}; } catch (e) { return {}; } };

async function playerView(id, view, q) {
  const role = q.get("role") || (q.get("room") ? "viewer" : "solo");
  let room = q.get("room") || null;
  const prefs = Object.assign({ tr: 0, capo: "auto", simple: false, rate: 1 }, loadPrefs(id));
  const S = { id, view, role, room, song: null, an: null, chart: null, tr: prefs.tr, capo: prefs.capo, simple: prefs.simple, edit: false,
    lastLine: -1, follow: role !== "viewer", audioOn: role !== "viewer", meta: null };
  const savePrefs = () => localStorage.setItem(prefsKey(id), JSON.stringify({ tr: S.tr, capo: S.capo, simple: S.simple, rate: player.rate }));
  const player = new Player();
  let sync = null;
  window.__jam = { player, S, get sync() { return sync; }, errors };
  // 热度: one play per opened song, counted when playback really starts or a jam starts/joins
  // (the server also ignores the same browser session within 30 s, so a reload does not double it).
  let counted = false;
  const countPlay = why => { if (counted || isStatic) return; counted = true; S.playCount = why; api.play(id).catch(() => { counted = false; }); };
  player.addEventListener("state", () => { if (player.playing) countPlay("play"); });
  onCleanup(() => { player.unload(); sync && sync.close(); delete window.__jam; });

  try { S.song = await api.song(id); } catch (e) { app.innerHTML = `<div class="lib"><div class="card err">${esc(e.message)}</div><button onclick="location.hash='#/'">${esc(t("back"))}</button></div>`; return; }
  S.an = S.song.analysis;
  if (!S.an) { app.innerHTML = `<div class="lib"><div class="card">${esc(stageLabel(S.song.meta))}</div></div>`; return; }
  document.title = `${S.an.title || "Cteno Jam"} · Cteno Jam`;
  player.setBeats(S.an.beats, S.an.downbeats);
  const stems = (S.song.meta && S.song.meta.stems) || STEMS;

  // ---- render shell
  const isStage = view === "stage";
  if (isStage) renderStageShell(); else renderSheetShell();

  function renderSheetShell() {
    app.innerHTML = `<div class="player" id="pl"><div class="main">
      ${topBar(`<button class="ghost" id="back" aria-label="${esc(t("back"))}">‹</button>
        <div class="grow" style="min-width:0"><h1 id="ttl"></h1><div class="sub" id="meta"></div></div>
        <button class="ghost" id="shareBtn">${esc(t("share"))}</button>`)}
      <div id="aibar"></div>
      <div class="now"><div class="cur" id="cur">–</div><div class="nxt" id="nxt"></div><div class="capo" id="capo"></div></div>
      <div class="diagrow" id="diags"></div>
      <div class="sheet" id="sheet"></div></div>
      <footer class="ctl dis" id="foot">
        <div class="status" id="status"><span id="msg">${esc(t("loading"))}</span><div class="prog" id="lprog"><i></i></div><button id="retryLoad" class="hidden">${esc(t("retry"))}</button></div>
        <div class="bar"><button class="play" id="play" disabled aria-label="play">▶</button>
          <div class="seekwrap"><div class="loopband hidden" id="loopband"></div><input class="seek" id="seek" type="range" min="0" max="1000" value="0" aria-label="seek"></div>
          <div class="time" id="time">0:00</div></div>
        <div class="mix" id="mix"></div>
        <div class="tools">
          <div class="grp"><span>${esc(t("transpose"))}</span><button id="trDn">－</button><b id="trV">0</b><button id="trUp">＋</button></div>
          <div class="grp"><span>${esc(t("speed"))}</span><button id="spd">1.0x</button></div>
          <button id="karaoke">${esc(t("karaoke"))}</button>
          <button class="moreBtn" id="moreBtn">⋯</button>
        </div>
        <div class="tools more" id="more">
          <div class="grp"><span>${esc(t("capo"))}</span><button id="capoDn">－</button><b id="capoV">A</b><button id="capoUp">＋</button></div>
          <button id="simple">${esc(t("simple"))}</button>
          <div class="grp"><span>${esc(t("loop"))}</span><button id="loopA">${esc(t("loop_a"))}</button><button id="loopB">${esc(t("loop_b"))}</button><button id="loopX">✕</button></div>
          <button id="metro">${esc(t("metronome"))}</button><button id="countin">${esc(t("count_in"))}</button>
          <button id="stageBtn">${esc(t("stage"))}</button>
          ${isStatic ? "" : `<button id="editBtn">${esc(t("edit"))}</button><button id="changesBtn">${esc(t("changes"))}</button>`}
          <button id="printBtn">${esc(t("print"))}</button>
          <span class="muted" style="font-size:12px;margin-left:auto">${esc(t("tap_jump"))}</span>
        </div>
      </footer></div>`;
    bindLang(() => { teardown(); route(); });
    $("#back").onclick = () => go("#/");
    $("#shareBtn").onclick = () => sharePanel();
    buildMix();
    bindTools();
  }

  function renderStageShell() {
    app.innerHTML = `<div class="stage" id="stage">
      <div class="meta"><span id="sTitle"></span><span id="sKey"></span></div>
      <div class="pbar"><i id="sProg" style="width:0"></i></div>
      <div class="chords"><div class="c-now" id="sCur">–</div><div class="c-next" id="sNext"></div><div class="c-diag" id="sDiag"></div></div>
      <div class="lyr"><div class="sec-now" id="sSec"></div><div class="l-now" id="sLine"></div><div class="l-next" id="sNextLine"></div></div>
      <div class="corner" id="sCorner"></div>
      <div class="tap hidden" id="sTap">▶</div>
      <div class="countdown hidden" id="sCount"></div>
    </div>`;
    document.addEventListener("keydown", stageKeys); onCleanup(() => document.removeEventListener("keydown", stageKeys));
    $("#stage").ondblclick = () => document.documentElement.requestFullscreen && document.documentElement.requestFullscreen().catch(() => {});
  }
  function stageKeys(e) {
    if (e.key === " " || e.key === "Enter" || e.key === "MediaPlayPause") { e.preventDefault(); if (S.audioOn) togglePlay(); }
    if (e.key === "ArrowRight") player.seek(player.now() + 5);
    if (e.key === "ArrowLeft") player.seek(player.now() - 5);
    if (e.key === "Escape") go(`#/s/${id}${room ? `?room=${room}&role=${role}` : ""}`);
  }

  // ---- chart
  const touched = () => aiTouched(S.song);
  function opts() { return chartOptions(S.an, { tr: S.tr, capo: S.capo, simple: S.simple }); }
  function renderChart() {
    S.chart = buildChart(S.an);
    S.o = opts();
    S.lineEls = []; S.unitEls = []; S.lastLine = -1;
    if (isStage) return renderStageMeta();
    $("#ttl").textContent = S.an.title || "";
    const k = S.an.key ? S.an.key.replace(" major", "").replace(" minor", "m") : "?";
    $("#meta").textContent = `${S.an.artist ? S.an.artist + " · " : ""}${t("original_key", { k })} · ${Math.round(S.an.tempo || 0)} BPM`;
    const o = S.o, ai = touched();
    $("#capo").innerHTML = `${esc(t("key_now", { k: o.soundKeyName }))}<br><b>${esc(o.fret ? t("capo_hint", { f: o.fret, s: o.shapesKey }) : t("no_capo", { s: o.shapesKey }))}</b>${o.rec.ai && S.capo === "auto" ? ' <span class="badge ai">AI</span>' : ""}`;
    $("#capoV").textContent = S.capo === "auto" ? `${o.fret}` : String(S.capo);
    $("#capoV").title = S.capo === "auto" ? "auto" : "";
    $("#trV").textContent = S.tr > 0 ? `+${S.tr}` : String(S.tr);
    $("#simple").classList.toggle("on", S.simple);
    // diagrams of the chords in use
    const used = [...new Set((S.an.chords || []).filter(c => c.chord !== "N").map(c => o.shown(c)))].slice(0, 16);
    $("#diags").innerHTML = used.map(c => diagramSVG(c)).join("");
    const sh = $("#sheet");
    sh.classList.toggle("edit-mode", S.edit);
    const rh = S.an.rhythm;
    let html = rh ? `<div class="inst">${esc(t("rhythm"))}: <span class="rhythm">${esc(rh.pattern)}</span><span class="muted">${esc(rh.note || "")}</span></div>` : "";
    if (!S.an.lyrics || !S.an.lyrics.lines || !S.an.lyrics.lines.length) html += `<div class="inst">${esc(t("no_lyrics"))}</div>`;
    const flags = new Map((S.an.flags || []).map(f => [f.line, f.issue]));
    S.chart.forEach((it, idx) => {
      if (it.type === "section") {
        const aiSec = (S.song.revisions || []).some(r => r.status === "applied" && r.source === "ai" && r.patch.op === "add_section" && Math.abs(r.patch.start - it.start) < 0.01);
        html += `<div class="sec ${aiSec ? "ai" : ""}" data-sec="${esc(it.id)}">${esc(t("sections." + it.label))} <span class="muted">${fmt(it.start)}</span><button data-loop="${it.start},${it.end}" aria-label="loop section">⟲ ${esc(t("loop"))}</button></div>`;
      } else if (it.type === "inst") {
        html += `<div class="inst" data-t="${it.start}">${esc(t("instrumental", { a: fmt(it.start), b: fmt(it.end) }))} ${it.segs.map(s => `<b class="${ai.has(s.id) ? "ai" : ""}" data-seg="${esc(s.id)}">${esc(o.shown(s))}</b>`).join(" ")}</div>`;
      } else {
        html += `<div class="line" data-line="${esc(it.line.id)}"><div class="chars">${it.units.map((u, j) =>
          `<div class="ch" data-t="${u.t ?? it.start}" data-u="${j}"><b class="${u.seg && ai.has(u.seg.id) ? "ai" : ""}" ${u.seg ? `data-seg="${esc(u.seg.id)}"` : ""}>${u.seg ? esc(o.shown(u.seg)) : ""}</b><i>${esc(u.c)}</i></div>`).join("")}</div></div>`;
        if (flags.has(it.line.id)) html += `<div class="flag">AI: ${esc(flags.get(it.line.id))}</div>`;
      }
    });
    sh.innerHTML = html;
    sh.querySelectorAll(".line").forEach(el => {
      const ln = S.an.lyrics.lines.find(l => l.id === el.dataset.line);
      S.lineEls.push([ln.start, ln.end, el, ln]);
    });
    sh.querySelectorAll(".ch").forEach(el => S.unitEls.push([+el.dataset.t, el]));
    sh.onclick = ev => {
      const loopB = ev.target.closest("[data-loop]");
      if (loopB) { const [a, b] = loopB.dataset.loop.split(",").map(Number); player.setLoop(a, b); toast(`${t("loop")} ${fmt(a)}–${fmt(b)}`); return; }
      if (S.edit) return editClick(ev);
      const u = ev.target.closest("[data-t]");
      if (u && player.ready) { player.seek(+u.dataset.t - 0.3); publish(); }
    };
    renderAiBar();
  }

  function renderAiBar() {
    const el = $("#aibar"); if (!el) return;
    const ai = (S.song.meta && S.song.meta.ai) || {};
    const revs = (S.song.revisions || []).filter(r => r.source === "ai");
    const applied = revs.filter(r => r.status === "applied").length;
    if (isStatic && !revs.length) { el.innerHTML = ""; return; }
    let html = "";
    if (ai.status === "running" || ai.status === "queued") html = `<span>✨ ${esc(t(ai.status === "running" ? "ai_running" : "ai_queued"))}</span>`;
    else if (revs.length) html = `<span>✨ ${esc(t("ai_done", { n: applied }))}${ai.rejected && ai.rejected.length ? ` · ${esc(t("ai_rejected", { n: ai.rejected.length }))}` : ""}</span><div class="grow"></div><button id="aiOpen">${esc(t("changes"))}</button>`;
    else if (ai.status === "failed") html = `<span class="err">${esc(t("ai_failed", { e: ai.error || "" }))}</span><div class="grow"></div>${INFO.ai.configured ? `<button id="aiRun">${esc(t("retry"))}</button>` : ""}`;
    else if (!INFO.ai.configured && !isStatic) html = `<span class="muted">✨ ${esc(t("ai_off"))}</span>`;
    else if (INFO.ai.configured) html = `<span>✨ ${esc(t("ai"))}</span><div class="grow"></div><button id="aiRun">${esc(t("ai_run"))}</button>`;
    el.innerHTML = html ? `<div class="aibar" style="margin:6px 14px">${html}</div>` : "";
    const o = $("#aiOpen"); if (o) o.onclick = () => changesPanel();
    const r = $("#aiRun"); if (r) r.onclick = async () => { try { await api.review(id); pollMeta(); toast(t("ai_queued")); } catch (e) { toast(e.message); } };
  }
  let pollT = null;
  function pollMeta() {
    clearTimeout(pollT);
    pollT = setTimeout(async () => {
      try {
        const m = await api.meta(id);
        const st = m.ai && m.ai.status;
        S.song.meta = m;
        if (st === "running" || st === "queued") { renderAiBar(); pollMeta(); }
        else { await reloadSong(); }
      } catch (e) {}
    }, 2000);
  }
  onCleanup(() => clearTimeout(pollT));
  async function reloadSong() { S.song = await api.song(id); S.an = S.song.analysis; player.setBeats(S.an.beats, S.an.downbeats); renderChart(); }

  // ---- mixer & tools
  function buildMix() {
    $("#mix").innerHTML = STEMS.filter(k => stems.includes(k)).map(k => `<div class="trk" data-stem="${k}"><div class="tb"><button type="button" class="m">${esc(t(k))}</button><button type="button" class="s" aria-label="${esc(t("solo"))}">S</button></div>
      <input type="range" min="0" max="1.5" step=".05" value="1" aria-label="${esc(t(k))}"></div>`).join("");
    $("#mix").querySelectorAll(".trk").forEach(d => {
      const k = d.dataset.stem;
      d.querySelector(".m").onclick = () => { player.toggle(k); syncMixUI(); publish(); };
      d.querySelector(".s").onclick = () => { player.setSolo(k); syncMixUI(); publish(); };
      d.querySelector("input").oninput = e => player.setVolume(k, +e.target.value);
    });
  }
  function syncMixUI() {
    document.querySelectorAll(".trk").forEach(d => {
      const k = d.dataset.stem;
      d.classList.toggle("off", player.solo ? player.solo !== k : !player.on[k]);
      d.querySelector(".s").classList.toggle("on", player.solo === k);
    });
    const kb = $("#karaoke"); if (kb) kb.classList.toggle("on", !player.on.vocals && !player.solo);
  }
  function bindTools() {
    $("#play").onclick = () => togglePlay();
    $("#seek").oninput = e => { S.dragging = true; $("#time").textContent = `${fmt(e.target.value / 1000 * player.dur)} / ${fmt(player.dur)}`; };
    $("#seek").onchange = e => { S.dragging = false; player.seek(e.target.value / 1000 * player.dur); publish(); };
    $("#trUp").onclick = () => setTr(S.tr + 1);
    $("#trDn").onclick = () => setTr(S.tr - 1);
    $("#spd").onclick = async () => { const r = player.rate === 1 ? 0.8 : player.rate === 0.8 ? 0.6 : 1; await player.setRate(r); $("#spd").textContent = r.toFixed(1) + "x"; savePrefs(); publish(); };
    $("#karaoke").onclick = () => { player.karaoke(player.on.vocals || !!player.solo); syncMixUI(); publish(); };
    $("#moreBtn").onclick = () => $("#foot").classList.toggle("show-more");
    $("#capoUp").onclick = () => setCapo((S.capo === "auto" ? S.o.fret : +S.capo) + 1);
    $("#capoDn").onclick = () => { const c = S.capo === "auto" ? S.o.fret : +S.capo; setCapo(c <= 0 ? "auto" : c - 1); };
    $("#capoV").onclick = () => setCapo("auto");
    $("#simple").onclick = () => { S.simple = !S.simple; savePrefs(); renderChart(); publish(); };
    $("#loopA").onclick = () => { S.loopA = player.now(); toast(`A ${fmt(S.loopA)}`); };
    $("#loopB").onclick = () => { const b = player.now(); if (S.loopA != null && b > S.loopA + 0.5) player.setLoop(S.loopA, b); };
    $("#loopX").onclick = () => { S.loopA = null; player.setLoop(null, null); };
    $("#metro").onclick = () => { player.setMetronome(!player.metro); $("#metro").classList.toggle("on", player.metro); };
    $("#countin").onclick = () => { player.countIn = !player.countIn; $("#countin").classList.toggle("on", player.countIn); };
    $("#stageBtn").onclick = () => go(`#/s/${id}/stage${room ? `?room=${room}&role=${role}` : ""}`);
    $("#printBtn").onclick = () => go(`#/s/${id}/print?tr=${S.tr}&capo=${S.capo}&simple=${S.simple ? 1 : 0}`);
    const eb = $("#editBtn"); if (eb) eb.onclick = () => {
      S.edit = !S.edit; eb.classList.toggle("on", S.edit);
      $("#pl").classList.toggle("editing", S.edit);
      if (S.edit) { $("#foot").classList.remove("show-more"); toast(t("edit_help"), 4000); }
      renderChart();
    };
    const cb = $("#changesBtn"); if (cb) cb.onclick = () => changesPanel();
    $("#retryLoad").onclick = () => loadAudio();
  }
  async function setTr(v) {
    S.tr = Math.max(-7, Math.min(7, v)); savePrefs();
    renderChart();
    if (S.audioOn && player.ready) await player.setSemitones(S.tr);
    publish();
  }
  function setCapo(v) { S.capo = v === "auto" ? "auto" : Math.max(0, Math.min(9, v)); savePrefs(); renderChart(); publish(); }

  function togglePlay() {
    if (!player.ready) return;
    player.ensureCtx();
    if (player.playing) player.stop(); else player.start();
    const stEl = $("#status"); if (stEl && player.playing && !stEl.classList.contains("err") && !$("#followAudio")) stEl.style.display = "none";
    publish();
  }
  player.addEventListener("state", () => {
    const p = $("#play"); if (p) p.textContent = player.playing ? "❚❚" : "▶";
    const lb = $("#loopband");
    if (lb) { if (player.loop && player.dur) { lb.classList.remove("hidden"); lb.style.left = (player.loop[0] / player.dur * 100) + "%"; lb.style.width = ((player.loop[1] - player.loop[0]) / player.dur * 100) + "%"; } else lb.classList.add("hidden"); }
  });
  player.addEventListener("error", e => toast(String(e.detail)));
  player.addEventListener("countin", e => {
    const el = $("#sCount"); if (!el) return;
    const { per } = e.detail; let n = 4; el.classList.remove("hidden"); el.textContent = n;
    const iv = setInterval(() => { n--; if (n <= 0) { clearInterval(iv); el.classList.add("hidden"); } else el.textContent = n; }, per * 1000);
  });

  // ---- loading
  function status(text, frac, isErr) {
    const m = $("#msg"); if (!m) return;
    m.textContent = text; $("#status").classList.toggle("err", !!isErr); $("#status").style.display = "";
    const pg = $("#lprog"); if (frac != null) pg.firstChild.style.width = (Math.min(1, frac) * 100).toFixed(1) + "%";
    pg.style.display = isErr || frac == null ? "none" : ""; $("#retryLoad").classList.toggle("hidden", !isErr);
  }
  async function loadAudio() {
    if (!S.audioOn) { if (!isStage) status(t("following", { c: room }), null); return; }
    try {
      await player.load(api.stemBase(id), stems, { onProgress: p => {
        if (p.phase === "download") status(t("download", { g: (p.got / 1e6).toFixed(1), t: (p.total / 1e6).toFixed(1) }), p.frac);
        else status(t("decoding", { i: p.i, n: p.n, s: t(p.stem) }), p.frac);
      } });
      window.__loadStats = player.stats;
      if (!isStage) {
        $("#foot").classList.remove("dis"); $("#play").disabled = false;
        status(t("ready_in", { s: (player.stats.totalMs / 1000).toFixed(1) }), 1);
        setTimeout(() => { if (player.ready && !$("#status").classList.contains("err")) $("#status").style.display = "none"; }, 4000);
      } else { $("#sTap").classList.remove("hidden"); $("#sTap").onclick = () => { $("#sTap").classList.add("hidden"); player.ensureCtx(); if (!player.playing) togglePlay(); }; }
      if (prefs.rate && prefs.rate !== 1) { await player.setRate(prefs.rate); const s = $("#spd"); if (s) s.textContent = prefs.rate.toFixed(1) + "x"; }
      if (S.tr) await player.setSemitones(S.tr);
      if (sync && sync.state && role !== "host") applyRemoteState(sync.state);
    } catch (e) {
      console.warn(e);
      if (!isStage) status(t("load_failed", { e: e.message }) + (navigator.onLine === false ? " (offline)" : ""), null, true);
      else $("#sTitle").textContent = t("load_failed", { e: e.message });
    }
  }

  // ---- sync
  function ensureRoom(asRole = "host") {
    if (sync) return;
    if (!room) { room = randomRoom(); }
    sync = new Sync(room, asRole === "host" ? "host" : asRole);
    S.role = asRole;
    sync.addEventListener("peers", e => { S.peers = e.detail.n; const pe = $("#peers"); if (pe) pe.textContent = t("peers", { n: e.detail.n }); });
    if (asRole === "host") {
      sync.addEventListener("open", () => publish());
      sync.addEventListener("cmd", e => onCmd(e.detail));
      const hb = setInterval(() => publish(), 3000); onCleanup(() => clearInterval(hb));
    } else {
      sync.addEventListener("state", e => applyRemoteState(e.detail));
    }
    countPlay("jam");
    const nh = `#/s/${id}${view === "stage" ? "/stage" : ""}?room=${room}&role=${asRole}`;
    history.replaceState(null, "", nh);
  }
  function stateSnapshot() {
    return { song: id, title: S.an.title, playing: player.playing, pos: player.now(), rate: player.rate, tr: S.tr, capo: S.capo, simple: S.simple,
      loop: player.loop, muted: STEMS.filter(k => !player.on[k]), view };
  }
  function publish() { if (sync && S.role === "host") sync.publish(stateSnapshot()); }
  async function onCmd(m) {
    const a = m.arg;
    switch (m.cmd) {
      case "play": if (!player.playing) { player.ensureCtx(); player.start(); } break;
      case "pause": if (player.playing) player.stop(); break;
      case "toggle": togglePlay(); return;
      case "seek": player.seek(typeof a === "number" ? a : player.now()); break;
      case "skip": player.seek(player.now() + (+a || 0)); break;
      case "line": { const ls = S.an.lyrics.lines; const cur = S.lastLine; const j = Math.max(0, Math.min(ls.length - 1, (cur < 0 ? 0 : cur) + (+a || 0))); if (ls[j]) player.seek(ls[j].start - 0.4); break; }
      case "transpose": await setTr(S.tr + (+a || 0)); return;
      case "rate": await player.setRate(+a || 1); { const s = $("#spd"); if (s) s.textContent = player.rate.toFixed(1) + "x"; } savePrefs(); break;
      case "karaoke": player.karaoke(!!a); syncMixUI(); break;
      case "mute": if (a && STEMS.includes(a.stem)) { player.setMute(a.stem, !!a.muted); syncMixUI(); } break;
      case "loop": if (a && a.section) { const sec = sectionAt(S.an, player.now()); if (sec) player.setLoop(sec.start, sec.end); } else player.setLoop(null, null); break;
      case "simple": S.simple = !!a; renderChart(); break;
      case "view": if (a === "stage" || a === "sheet") go(`#/s/${id}${a === "stage" ? "/stage" : ""}?room=${room}&role=host`); return;
    }
    publish();
  }
  async function applyRemoteState(st) {
    if (!st || st.song !== id) {
      if (st && st.song && st.song !== id) go(`#/s/${st.song}${view === "stage" ? "/stage" : ""}?room=${room}&role=${S.role}`);
      return;
    }
    let rerender = false;
    if (st.tr !== S.tr) { S.tr = st.tr || 0; rerender = true; }
    if (st.simple !== undefined && !!st.simple !== S.simple) { S.simple = !!st.simple; rerender = true; }
    if (rerender) renderChart();
    if (S.audioOn && player.ready) {
      const want = sync.livePos(st);
      if (player.rate !== st.rate) await player.setRate(st.rate || 1);
      if (player.semis !== (st.tr || 0)) await player.setSemitones(st.tr || 0);
      (st.muted || []).forEach(k => player.setMute(k, true));
      STEMS.filter(k => !(st.muted || []).includes(k)).forEach(k => player.setMute(k, false));
      if (st.playing && !player.playing) { player.pos = want; player.start(); }
      else if (!st.playing && player.playing) player.stop();
      if (Math.abs(player.now() - want) > 0.25) player.seek(want);
    }
  }
  function now() {
    if (sync && S.role !== "host" && !(S.audioOn && player.ready)) return sync.livePos();
    return player.now();
  }
  window.__jam.now = now;

  function sharePanel() {
    ensureRoom("host");
    const base = publicBase();
    const follow = `${base}/#/s/${id}?room=${room}&role=viewer`;
    const stage = `${base}/#/s/${id}/stage?room=${room}&role=viewer`;
    const remote = `${base}/#/r/${room}`;
    panel(`<h3>${esc(t("share_title"))}</h3>
      <p class="muted" style="margin:0 0 8px">${esc(t("share_desc"))}</p>
      <div class="qr" id="qrFollow">${qrSVG(follow)}</div>
      <div class="linkbox" id="followLink">${esc(follow)}</div>
      <div class="row" style="margin:8px 0"><button id="copyF">${esc(t("copy"))}</button><span class="muted" id="peers">${esc(t("peers", { n: S.peers || 1 }))}</span><div class="grow"></div><b>${esc(t("room", { c: room }))}</b></div>
      <hr style="border:0;border-top:1px solid #262a33;margin:12px 0">
      <p class="muted" style="margin:0 0 6px">${esc(t("tv_hint"))}</p>
      <div class="linkbox" id="stageLink">${esc(stage)}</div>
      <p class="muted" style="margin:10px 0 6px">${esc(t("remote_desc"))}</p>
      <div class="linkbox" id="remoteLink">${esc(remote)}</div>
      <div class="row" style="margin-top:8px"><button id="goStage">${esc(t("open_stage"))}</button></div>`, close => {
      $("#copyF").onclick = () => { navigator.clipboard && navigator.clipboard.writeText(follow).then(() => toast(t("copied"))).catch(() => {}); };
      $("#goStage").onclick = () => { close(); go(`#/s/${id}/stage?room=${room}&role=host`); };
    });
  }

  // ---- editing (human patches)
  function segById(sid) { return (S.an.chords || []).find(c => c.id === sid); }
  function editClick(ev) {
    const b = ev.target.closest("b[data-seg]");
    if (b) return editChord(segById(b.dataset.seg));
    const ch = ev.target.closest(".ch");
    const lineEl = ev.target.closest(".line");
    if (ch && ev.target.tagName === "B") return addChordAt(+ch.dataset.t);
    if (lineEl) return editLine(S.an.lyrics.lines.find(l => l.id === lineEl.dataset.line), ch ? +ch.dataset.t : null);
  }
  function editChord(seg) {
    if (!seg) return;
    panel(`<h3>${esc(t("edit_chord"))} · ${fmt(seg.start)}</h3>
      <div class="form"><input type="text" id="chIn" value="${esc(seg.chord)}" autocapitalize="off" autocomplete="off">
      <div class="err" id="chErr"></div>
      <div class="row"><button class="primary" id="chSave">${esc(t("edit_save"))}</button><button id="chDel">${esc(t("edit_delete"))}</button><div class="grow"></div><button id="chX">${esc(t("edit_cancel"))}</button></div></div>`, close => {
      $("#chIn").focus();
      $("#chX").onclick = close;
      $("#chSave").onclick = async () => {
        const v = $("#chIn").value.trim();
        if (!parseChord(v)) { $("#chErr").textContent = t("edit_invalid", { c: v }); return; }
        if (v === seg.chord) return close();
        await submit([{ op: "replace_chord", id: seg.id, chord: v, reason: "manual edit" }]); close();
      };
      $("#chDel").onclick = async () => { await submit([{ op: "delete_chord", id: seg.id, reason: "manual edit" }]); close(); };
    });
  }
  function addChordAt(tt) {
    const v = prompt(t("edit_add_here") + ` (${fmt(tt)})`, "");
    if (!v) return;
    if (!parseChord(v.trim())) return toast(t("edit_invalid", { c: v }));
    submit([{ op: "insert_chord", start: tt, chord: v.trim(), reason: "manual edit" }]);
  }
  function editLine(ln, unitT) {
    if (!ln) return;
    panel(`<h3>${esc(t("edit_line_text"))} · ${fmt(ln.start)}</h3>
      <div class="form"><input type="text" id="lnIn" value="${esc(ln.text)}">
      <div class="row"><span class="muted">${esc(t("edit_shift"))}</span><button data-d="-0.5">−0.5s</button><button data-d="-0.1">−0.1s</button><button data-d="0.1">+0.1s</button><button data-d="0.5">+0.5s</button></div>
      ${unitT != null ? `<button id="lnAdd">${esc(t("edit_add_here"))} (${fmt(unitT)})</button>` : ""}
      <div class="row"><button class="primary" id="lnSave">${esc(t("edit_save"))}</button><div class="grow"></div><button id="lnX">${esc(t("edit_cancel"))}</button></div></div>`, (close, p) => {
      $("#lnX").onclick = close;
      p.querySelectorAll("[data-d]").forEach(b => b.onclick = async () => { await submit([{ op: "shift_line", line: ln.id, delta: +b.dataset.d, reason: "manual timing" }]); close(); });
      $("#lnSave").onclick = async () => { const v = $("#lnIn").value; if (v.trim() && v !== ln.text) await submit([{ op: "set_line_text", line: ln.id, text: v, reason: "manual edit" }]); close(); };
      const a = $("#lnAdd"); if (a) a.onclick = () => { close(); addChordAt(unitT); };
    });
  }
  async function submit(patches) {
    try {
      const r = await api.edits(id, patches);
      S.song = r.song; S.an = S.song.analysis; renderChart(); toast(t("edit_saved"));
    } catch (e) { toast(e.message, 4000); }
  }
  function describeRev(r) {
    const p = r.patch || {}, seg = segById(p.id);
    switch (p.op) {
      case "respell_chord": case "replace_chord": return `${p.id} → ${p.chord}`;
      case "simplify_chord": return `${p.id}: ${t("simple")} → ${p.chord}`;
      case "merge_chord": return `${p.id} ⤳ ${p.into === "next" ? "→" : "←"}`;
      case "delete_chord": return `− ${p.id}`;
      case "insert_chord": return `+ ${p.chord} @ ${fmt(p.start)}`;
      case "add_section": return `${t("sections." + p.label)} ${fmt(p.start)}–${fmt(p.end)}`;
      case "set_capo": return `${t("capo")} ${p.fret}${p.shapes ? " (" + p.shapes + ")" : ""}`;
      case "set_rhythm": return `${t("rhythm")} ${p.pattern}`;
      case "set_key": return `Key → ${p.key}`;
      case "split_line": return `✂ ${p.line} @${p.at}`;
      case "merge_lines": return `⇥ ${p.line}`;
      case "flag_line": return `⚑ ${p.line}`;
      case "set_line_text": return `✎ ${p.line}`;
      case "shift_line": return `⇄ ${p.line} ${p.delta > 0 ? "+" : ""}${p.delta}s`;
      default: return p.op + (seg ? " " + seg.id : "");
    }
  }
  function changesPanel() {
    const draw = (p) => {
      const revs = S.song.revisions || [];
      const ai = (S.song.meta && S.song.meta.ai) || {};
      const aiRevs = revs.filter(r => r.source === "ai");
      p.innerHTML = `<h3>${esc(t("changes"))}</h3>
        ${aiRevs.length || ai.summary ? `<div class="aibar" style="display:block"><b>✨ ${esc(t("ai"))}</b>${ai.model ? ` <span class="muted">(${esc(ai.model)})</span>` : ""}<div style="margin-top:4px">${esc(ai.summary || "")}</div>
          <div class="muted" style="margin-top:6px;font-size:12px">${esc(t("ai_boundary"))}</div>
          ${isStatic ? "" : `<div class="row" style="margin-top:8px"><button id="undoAll">${esc(t("ai_undo_all"))}</button><button id="redoAll">${esc(t("ai_redo_all"))}</button>${INFO.ai.configured ? `<button id="rerun">${esc(t("ai_rerun"))}</button>` : ""}</div>`}</div>` : ""}
        ${revs.length ? revs.map(r => `<div class="rev ${r.status}" data-id="${esc(r.id)}"><span class="who ${r.source}">${esc(t(r.source === "ai" ? "rev_ai" : "rev_user"))}</span>
          <div class="grow"><div class="what">${esc(describeRev(r))}${r.status === "conflict" ? ` <span class="err">(${esc(t("ai_conflict"))})</span>` : ""}</div><div class="why">${esc(r.reason || "")}</div></div>
          ${isStatic ? "" : `<button data-act="${r.status === "applied" ? "reverted" : "applied"}">${esc(t(r.status === "applied" ? "undo" : "reapply"))}</button>`}</div>`).join("")
          : `<div class="muted">${esc(t("nothing"))}</div>`}
        ${ai.rejected && ai.rejected.length ? `<details style="margin-top:10px"><summary>${esc(t("ai_rejected", { n: ai.rejected.length }))}</summary>${ai.rejected.map(x => `<div class="why" style="margin:6px 0">• ${esc((x.patch && x.patch.op) || x.op || "")}: ${esc(x.error)}</div>`).join("")}</details>` : ""}`;
      p.querySelectorAll(".rev button").forEach(b => b.onclick = async () => {
        const rid = b.closest(".rev").dataset.id;
        try { const r = await api.revisions(id, [rid], b.dataset.act); S.song = r.song; S.an = S.song.analysis; renderChart(); draw(p); } catch (e) { toast(e.message); }
      });
      const ua = $("#undoAll", p); if (ua) ua.onclick = async () => { const r = await api.revisions(id, "all", "reverted", "ai"); S.song = r.song; S.an = S.song.analysis; renderChart(); draw(p); };
      const ra = $("#redoAll", p); if (ra) ra.onclick = async () => { const r = await api.revisions(id, "all", "applied", "ai"); S.song = r.song; S.an = S.song.analysis; renderChart(); draw(p); };
      const rr = $("#rerun", p); if (rr) rr.onclick = async () => { try { await api.review(id); toast(t("ai_queued")); S.song.meta.ai = { status: "queued" }; renderAiBar(); pollMeta(); } catch (e) { toast(e.message); } };
    };
    panel("", (close, p) => draw(p));
  }

  // ---- stage rendering
  function renderStageMeta() {
    const o = S.o;
    $("#sTitle").textContent = S.an.title || "";
    $("#sKey").textContent = `${t("key_now", { k: o.soundKeyName })} · ${o.fret ? t("capo_hint", { f: o.fret, s: o.shapesKey }) : t("no_capo", { s: o.shapesKey })}`;
    const corner = $("#sCorner");
    if (room && S.role === "host") {
      const remote = `${publicBase()}/#/r/${room}`;
      corner.innerHTML = `<div style="text-align:right">${esc(t("remote"))}<br>${esc(t("room", { c: room }))}</div><div class="qr">${qrSVG(remote)}</div>`;
    } else corner.innerHTML = room ? `<span>${esc(t("following", { c: room }))}</span>` : "";
  }
  let stageLine = -2;
  function drawStage(tt) {
    const an = S.an, o = S.o;
    const { cur, next } = chordAt(an, tt);
    const curSym = cur && cur.chord !== "N" ? o.shown(cur) : "–";
    if ($("#sCur").textContent !== curSym) { $("#sCur").textContent = curSym; $("#sDiag").innerHTML = cur && cur.chord !== "N" ? diagramSVG(curSym) : ""; }
    $("#sNext").textContent = next ? "→ " + o.shown(next) : "";
    const sec = sectionAt(an, tt); $("#sSec").textContent = sec ? t("sections." + sec.label) : "";
    $("#sProg").style.width = (player.dur || an.duration ? tt / (player.dur || an.duration) * 100 : 0) + "%";
    const lines = S.chart.filter(x => x.type === "line");
    let li = lines.findIndex(x => tt >= x.start - 0.4 && tt < x.end + 0.6);
    if (li < 0) li = lines.findIndex(x => x.start > tt) - 1; // between lines: show the next one coming
    const nextIdx = lines.findIndex(x => x.start > tt);
    if (li !== stageLine) {
      stageLine = li;
      const L = lines[li];
      const show = L && tt < L.end + 0.6 ? L : null;
      $("#sLine").innerHTML = show ? show.units.map(u => `<span class="w"><span class="u" data-t="${u.t}"><b>${u.seg && !u.carried ? esc(o.shown(u.seg)) : "&nbsp;"}</b>${esc(u.c)}</span></span>`).join("") : "♪";
      const N = show ? lines[li + 1] : lines[nextIdx];
      $("#sNextLine").textContent = N ? N.line.text : "";
    }
    $("#sLine").querySelectorAll(".u").forEach(el => el.classList.toggle("sung", +el.dataset.t <= tt));
  }

  // ---- animation loop
  function frame() {
    if (!S.an) return;
    const tt = now(), d = player.dur || S.an.duration || 0;
    if (isStage) drawStage(tt);
    else {
      if (!S.dragging && $("#time")) { $("#time").textContent = `${fmt(tt)} / ${fmt(d)}`; if (d) $("#seek").value = tt / d * 1000; }
      const { cur, next } = chordAt(S.an, tt);
      $("#cur").textContent = cur && cur.chord !== "N" ? S.o.shown(cur) : "–";
      $("#nxt").textContent = next ? "→ " + S.o.shown(next) : "";
      for (const [ut, el] of S.unitEls) el.classList.toggle("sung", ut <= tt);
      const li = S.lineEls.findIndex(([s, e]) => tt >= s - 0.3 && tt < e + 0.8);
      S.lineEls.forEach(([, , e], j) => e.classList.toggle("on", j === li));
      if (li >= 0 && li !== S.lastLine) {
        S.lastLine = li;
        const el = S.lineEls[li][2], sh = $("#sheet");
        if (!S.edit) sh.scrollTo({ top: el.offsetTop - sh.offsetTop - sh.clientHeight * 0.3, behavior: "smooth" });
      }
    }
    if (player.playing && !player.loop && d && player.now() >= d - 0.02) { player.stop(); player.pos = 0; publish(); }
    raf = requestAnimationFrame(frame);
  }
  let raf = requestAnimationFrame(frame);
  onCleanup(() => cancelAnimationFrame(raf));

  // ---- go
  if (room) {
    if (role === "viewer" && view !== "stage" && !isStatic) {
      // viewers may also play audio locally in sync
      S.audioOn = q.get("audio") === "1";
    }
    if (role === "viewer" && view === "stage") S.audioOn = q.get("audio") === "1";
    ensureRoom(role === "host" ? "host" : "viewer");
  }
  renderChart();
  if (!isStage) syncMixUI();
  if (!isStage && role === "viewer") {
    const f = $("#foot");
    status(t("following", { c: room }), null);
    $("#shareBtn").classList.add("hidden");
    const b = document.createElement("button"); b.textContent = t("follow_audio"); b.id = "followAudio";
    b.onclick = () => { S.audioOn = true; b.remove(); loadAudio(); };
    $("#status").appendChild(b);
    f.classList.remove("dis");
    ["play", "seek", "trUp", "trDn", "spd", "karaoke"].forEach(k => { const e = $("#" + k); if (e) e.disabled = true; });
  }
  await loadAudio();
}

// ------------------------------------------------------------------ remote
async function remoteView(room, q) {
  document.title = "Remote · Cteno Jam";
  const sync = new Sync(room, "remote");
  let song = null, an = null, st = null, opts = null;
  window.__jam = { sync, get state() { return st; }, errors };
  onCleanup(() => { sync.close(); delete window.__jam; });
  app.innerHTML = topBar(`<button class="ghost" onclick="location.hash='#/'">‹</button><div class="grow"><h1>${esc(t("remote"))}</h1><div class="sub" id="rRoom">${esc(t("remote_on", { c: room }))}</div></div>`) + `
    <main class="remote">
      <div class="card"><div class="muted" id="rTitle">…</div><div class="now-chord" id="rChord">–</div><div class="now-line" id="rLine"></div><div class="prog"><i id="rProg" style="width:0"></i></div><div class="muted" id="rPeers"></div></div>
      <div class="big"><button data-c="line" data-a="-1">⏮</button><button class="pp" data-c="toggle" id="rPP">▶</button><button data-c="line" data-a="1">⏭</button></div>
      <div class="grid3"><button data-c="skip" data-a="-10">−10s</button><button data-c="skip" data-a="-5">−5s</button><button data-c="skip" data-a="5">+5s</button></div>
      <div class="grid2"><button data-c="transpose" data-a="-1">${esc(t("transpose"))} −</button><button data-c="transpose" data-a="1">${esc(t("transpose"))} ＋</button></div>
      <div class="grid3"><button data-c="rate" data-a="0.6">0.6x</button><button data-c="rate" data-a="0.8">0.8x</button><button data-c="rate" data-a="1">1.0x</button></div>
      <div class="grid2"><button id="rKar">${esc(t("karaoke"))}</button><button id="rLoop">⟲ ${esc(t("loop"))}</button></div>
      <div class="grid2"><button data-c="view" data-a="stage">${esc(t("stage"))}</button><button data-c="view" data-a="sheet">${esc(t("sheet"))}</button></div>
    </main>`;
  bindLang(() => { teardown(); route(); });
  app.querySelectorAll("[data-c]").forEach(b => b.onclick = () => {
    const a = b.dataset.a; sync.command(b.dataset.c, a == null ? null : isNaN(+a) ? a : +a);
  });
  $("#rKar").onclick = () => sync.command("karaoke", !(st && (st.muted || []).includes("vocals")));
  $("#rLoop").onclick = () => sync.command("loop", st && st.loop ? null : { section: true });
  sync.addEventListener("peers", e => { $("#rPeers").textContent = t("peers", { n: e.detail.n }); });
  sync.addEventListener("state", async e => {
    st = e.detail;
    if (st.song && (!song || song.meta.id !== st.song)) {
      try { song = await api.song(st.song); an = song.analysis; } catch (err) { $("#rTitle").textContent = err.message; }
    }
    if (an) opts = chartOptions(an, { tr: st.tr || 0, capo: st.capo ?? "auto", simple: !!st.simple });
    $("#rTitle").textContent = `${st.title || ""} · ${opts ? t("key_now", { k: opts.soundKeyName }) : ""} · ${(st.rate || 1).toFixed(1)}x`;
    $("#rPP").textContent = st.playing ? "❚❚" : "▶";
    $("#rKar").classList.toggle("on", (st.muted || []).includes("vocals"));
    $("#rLoop").classList.toggle("on", !!st.loop);
  });
  const tick = () => {
    if (st && an && opts) {
      const tt = sync.livePos(st);
      const { cur } = chordAt(an, tt);
      $("#rChord").textContent = cur && cur.chord !== "N" ? opts.shown(cur) : "–";
      const ln = (an.lyrics.lines || []).find(l => tt >= l.start - 0.3 && tt < l.end + 0.6);
      $("#rLine").textContent = ln ? ln.text : "";
      $("#rProg").style.width = (tt / (an.duration || 1) * 100) + "%";
    }
    raf = requestAnimationFrame(tick);
  };
  let raf = requestAnimationFrame(tick);
  onCleanup(() => cancelAnimationFrame(raf));
}

// ------------------------------------------------------------------ print / PDF
async function printView(id, q) {
  let song;
  try { song = await api.song(id); } catch (e) { app.innerHTML = `<div class="card err">${esc(e.message)}</div>`; return; }
  const an = song.analysis;
  const o = chartOptions(an, { tr: +q.get("tr") || 0, capo: q.get("capo") || "auto", simple: q.get("simple") === "1" });
  const chart = buildChart(an);
  document.title = `${an.title} — chord chart`;
  const used = [...new Set((an.chords || []).filter(c => c.chord !== "N").map(c => o.shown(c)))];
  const capoTxt = o.fret ? t("capo_hint", { f: o.fret, s: o.shapesKey }) : t("no_capo", { s: o.shapesKey });
  let body = "";
  for (const it of chart) {
    if (it.type === "section") body += `<div class="psec">${esc(t("sections." + it.label))}</div>`;
    else if (it.type === "inst") body += `<div class="pinst">♪ ${it.segs.map(s => `<b>${esc(o.shown(s))}</b>`).join(" · ")}</div>`;
    else body += `<div class="pl"><div class="chars">${it.units.map(u => `<div class="ch"><b>${u.seg && !u.carried ? esc(o.shown(u.seg)) : u.seg && u.carried ? "" : ""}</b><i>${esc(u.c)}</i></div>`).join("")}</div></div>`;
  }
  app.innerHTML = `<div class="print">
    <div class="noprint row"><button onclick="history.back()">‹ ${esc(t("back"))}</button><button class="primary" id="doPrint">${esc(t("print"))}</button></div>
    <h1>${esc(an.title || "")}</h1>
    <div class="pm">${esc(an.artist ? an.artist + " · " : "")}${esc(t("print_meta", { k: o.soundKeyName, b: Math.round(an.tempo || 0), c: capoTxt }))}${an.rhythm ? ` · ${esc(t("rhythm"))}: <span class="rhythm" style="color:#b3261e">${esc(an.rhythm.pattern)}</span>` : ""}</div>
    <div class="diags">${used.map(c => diagramSVG(c)).join("")}</div>
    ${body}
    <div class="pfoot">${esc(t("print_footer"))}${song.meta && song.meta.license ? " · " + esc(song.meta.license) : ""}</div></div>`;
  $("#doPrint").onclick = () => window.print();
  document.body.style.background = "#fff";
  onCleanup(() => { document.body.style.background = ""; });
  window.__printReady = true;
}

// ------------------------------------------------------------------ boot
(async () => {
  try { INFO = await api.info(); } catch (e) { INFO = { upload: false, ai: { configured: false }, error: e.message }; }
  window.__jamInfo = INFO;
  route();
})();
