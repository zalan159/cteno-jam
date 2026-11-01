// Multi-stem player.
//
// Two engines on one AudioContext, both sample-accurate across stems:
//  * "direct": one AudioBufferSourceNode per stem, all started at the same context time and
//    offset (the prototype's proven iOS path, lowest CPU). Used at 1.0x and original key.
//  * "stretch": one Signalsmith Stretch AudioWorklet with 6 channels (one per stem) feeding a
//    ChannelSplitter -> per-stem gains. Time-stretch without pitch change and pitch shift
//    without tempo change. Switched to the first time the user changes speed or key; the
//    decoded stems are moved (not copied) into the worklet so memory does not double.
//
// Stems are mono MP3 (WebKit cannot decode ffmpeg's m4a), decoded at 32 kHz one by one with an
// OfflineAudioContext. The AudioContext is created inside the first tap (iOS), and
// navigator.audioSession.type = "playback" lets it play with the silent switch on.
import SignalsmithStretch from "../vendor/SignalsmithStretch.mjs";

export const STEMS = ["vocals", "guitar", "piano", "bass", "drums", "other"];
const SR = 32000;

try { if (navigator.audioSession) navigator.audioSession.type = "playback"; } catch (e) {}

function silentWav() {
  const n = 8000, b = new Uint8Array(44 + n), v = new DataView(b.buffer);
  const w = (o, t) => [...t].forEach((c, i) => (b[o + i] = c.charCodeAt(0)));
  w(0, "RIFF"); v.setUint32(4, 36 + n, true); w(8, "WAVEfmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
  v.setUint16(22, 1, true); v.setUint32(24, 8000, true); v.setUint32(28, 8000, true); v.setUint16(32, 1, true);
  v.setUint16(34, 8, true); w(36, "data"); v.setUint32(40, n, true); b.fill(128, 44);
  return URL.createObjectURL(new Blob([b], { type: "audio/wav" }));
}

async function fetchProgress(url, onp, signal) {
  let r;
  try { r = await fetch(url, { cache: "force-cache", signal }); }
  catch (e) { throw new Error(`${url}: ${e && e.message || e}`); }
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  const total = +r.headers.get("content-length") || 0;
  if (!r.body || !total) { const b = await r.arrayBuffer(); onp(b.byteLength, b.byteLength); return b; }
  const rd = r.body.getReader(), out = new Uint8Array(total); let got = 0;
  for (;;) {
    const { done, value } = await rd.read();
    if (done) break;
    if (got + value.length > out.length) throw new Error(`${url}: size mismatch`);
    out.set(value, got); got += value.length; onp(got, total);
  }
  return out.buffer.slice(0, got);
}
const decodeWith = (dctx, ab) => new Promise((res, rej) => {
  const p = dctx.decodeAudioData(ab, res, e => rej(e || new Error("decode failed")));
  if (p && p.catch) p.catch(rej);
});

export class Player extends EventTarget {
  constructor() {
    super();
    this.ctx = null; this.bufs = {}; this.chans = {}; this.gains = {}; this.vol = {}; this.on = {};
    STEMS.forEach(k => { this.vol[k] = 1; this.on[k] = true; });
    this.solo = null; this.playing = false; this.pos = 0; this.t0 = 0; this.rate = 1; this.semis = 0;
    this.dur = 0; this.ready = false; this.engine = "direct"; this.srcs = {}; this.stretch = null;
    this.loop = null; this.stems = STEMS.slice(); this.beats = []; this.downbeats = new Set(); this.metro = false;
    this.countIn = false; this.clickGain = null; this._clicks = []; this._sched = null; this.stats = null;
    this.ac = null; this.stretchError = null; this.counting = false;
  }

  // ------------------------------------------------------------ loading
  async load(baseUrl, stems, { onProgress = () => {} } = {}) {
    this.unload();
    this.stems = stems && stems.length ? stems.filter(s => STEMS.includes(s)) : STEMS.slice();
    this.ac = window.AbortController ? new AbortController() : null;
    const bytes = {}, sizes = {}, t = performance.now();
    const upd = () => {
      const g = Object.values(bytes).reduce((a, b) => a + b, 0), s = Object.values(sizes).reduce((a, b) => a + b, 0) || 1;
      onProgress({ phase: "download", got: g, total: s, frac: 0.85 * g / s });
    };
    const abs = await Promise.all(this.stems.map(k => fetchProgress(`${baseUrl}${k}.mp3`, (g, s) => { bytes[k] = g; sizes[k] = s; upd(); }, this.ac && this.ac.signal)));
    const tDl = performance.now();
    const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    const dctx = new OAC(1, SR, SR);
    for (let i = 0; i < this.stems.length; i++) {
      const k = this.stems[i];
      onProgress({ phase: "decode", i: i + 1, n: this.stems.length, stem: k, frac: 0.85 + 0.15 * i / this.stems.length });
      try { this.bufs[k] = await decodeWith(dctx, abs[i]); }
      catch (e) { throw new Error(`${k}: ${e && e.message || e}`); }
      abs[i] = null;
    }
    this.dur = Math.min(...this.stems.map(k => this.bufs[k].duration));
    this.stats = { downloadMs: Math.round(tDl - t), decodeMs: Math.round(performance.now() - tDl), totalMs: Math.round(performance.now() - t),
      decodedMB: +(this.stems.reduce((a, k) => a + this.bufs[k].length * 4, 0) / 1e6).toFixed(1), bytes: Object.values(sizes).reduce((a, b) => a + b, 0) };
    this.ready = true;
    this.emit("ready");
  }

  unload() {
    this.stop(true);
    if (this.ac) try { this.ac.abort(); } catch (e) {}
    if (this.stretch) { try { this.stretch.stop(); this.stretch.disconnect(); this.stretch.dropBuffers(); } catch (e) {} }
    this.stretch = null; this.engine = "direct"; this.bufs = {}; this.chans = {}; this.ready = false; this.pos = 0; this.loop = null;
  }

  // ------------------------------------------------------------ context
  ensureCtx() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      try { this.ctx = new AC({ sampleRate: SR, latencyHint: "playback" }); } catch (e) { this.ctx = new AC(); }
      this.master = this.ctx.createGain(); this.master.connect(this.ctx.destination);
      STEMS.forEach(k => { this.gains[k] = this.ctx.createGain(); this.gains[k].connect(this.master); });
      this.applyGains();
      this.clickGain = this.ctx.createGain(); this.clickGain.gain.value = 0.5; this.clickGain.connect(this.ctx.destination);
      this.analyser = this.ctx.createAnalyser(); this.analyser.fftSize = 2048; this.master.connect(this.analyser);
      if (!navigator.audioSession) { try { const a = new Audio(silentWav()); a.loop = true; a.play().catch(() => {}); this._unlock = a; } catch (e) {} }
      document.addEventListener("visibilitychange", () => { if (!document.hidden && this.ctx && this.playing && this.ctx.state !== "running") this.ctx.resume().catch(() => {}); });
    }
    if (this.ctx.state !== "running") this.ctx.resume().catch(e => this.emit("error", e.message));
    const s = this.ctx.createBufferSource(); s.buffer = this.ctx.createBuffer(1, 1, this.ctx.sampleRate); s.connect(this.ctx.destination); s.start(0);
  }

  // ------------------------------------------------------------ mixing
  gainOf(k) {
    if (this.solo) return k === this.solo ? this.vol[k] : 0;
    return this.on[k] ? this.vol[k] : 0;
  }
  applyGains() { STEMS.forEach(k => { if (this.gains[k]) this.gains[k].gain.setTargetAtTime(this.gainOf(k), this.ctx.currentTime, 0.01); }); this.emit("mix"); }
  setMute(k, muted) { this.on[k] = !muted; this.applyGains(); }
  toggle(k) { this.on[k] = !this.on[k]; this.applyGains(); }
  setVolume(k, v) { this.vol[k] = Math.max(0, Math.min(1.5, v)); this.applyGains(); }
  setSolo(k) { this.solo = this.solo === k ? null : k; this.applyGains(); }
  karaoke(on) { this.on.vocals = !on; this.solo = null; this.applyGains(); }
  // target mix (what the user set) and the live gain values (ramping, ~30 ms)
  gainsNow() { return Object.fromEntries(STEMS.map(k => [k, +this.gainOf(k).toFixed(3)])); }
  gainsLive() { return Object.fromEntries(STEMS.map(k => [k, this.gains[k] ? +this.gains[k].gain.value.toFixed(3) : this.gainOf(k)])); }

  // ------------------------------------------------------------ time
  now() {
    if (!this.playing || !this.ctx) return this.pos;
    let p = this.pos + Math.max(0, this.ctx.currentTime - this.t0) * this.rate;
    if (this.loop && p >= this.loop[1]) p = this.loop[0] + ((p - this.loop[0]) % (this.loop[1] - this.loop[0]));
    return Math.min(p, this.dur);
  }

  start() {
    if (!this.ready) return;
    this.ensureCtx();
    if (this.pos >= this.dur - 0.05) this.pos = 0;
    if (this.loop && (this.pos < this.loop[0] || this.pos >= this.loop[1])) this.pos = this.loop[0];
    let lead = 0.08;
    if (this.countIn && this.beats.length > 1) lead = this.scheduleCountIn(this.ctx.currentTime + 0.08) + 0.08;
    const w = this.ctx.currentTime + lead;
    if (this.engine === "stretch" && this.stretch) {
      const sch = { output: w, input: this.pos, rate: this.rate, semitones: this.semis, active: true };
      if (this.loop) { sch.loopStart = this.loop[0]; sch.loopEnd = this.loop[1]; } else { sch.loopStart = 0; sch.loopEnd = 0; }
      this.stretch.schedule(sch);
      const g = this.gate.gain; g.cancelScheduledValues(0); g.setValueAtTime(0, this.ctx.currentTime); g.setValueAtTime(1, w);
    } else {
      this.srcs = {};
      this.stems.forEach(k => {
        const s = this.ctx.createBufferSource(); s.buffer = this.bufs[k]; s.playbackRate.value = 1;
        if (this.loop) { s.loop = true; s.loopStart = this.loop[0]; s.loopEnd = this.loop[1]; }
        s.connect(this.gains[k]); s.start(w, this.pos); this.srcs[k] = { node: s, when: w, offset: this.pos };
      });
    }
    this.t0 = w; this.playing = true; this.counting = lead > 0.1;
    this.startMetronome();
    this.emit("state");
  }

  stop(silent) {
    if (!this.playing) return;
    this.pos = this.now();
    if (this.engine === "stretch" && this.stretch) {
      const t = this.ctx.currentTime, g = this.gate.gain;
      g.cancelScheduledValues(0); g.setValueAtTime(g.value, t); g.linearRampToValueAtTime(0, t + 0.015);
      try { this.stretch.schedule({ active: false, output: t + 0.015 }); } catch (e) {}
    }
    Object.values(this.srcs).forEach(({ node }) => { try { node.stop(); node.disconnect(); } catch (e) {} });
    this.srcs = {}; this.playing = false; this.counting = false;
    this.stopMetronome();
    if (!silent) this.emit("state");
  }
  toggle_play() { this.ensureCtx(); this.playing ? this.stop() : this.start(); }

  seek(s) {
    if (!this.ready) return;
    const p = this.playing; if (p) this.stop(true);
    this.pos = Math.max(0, Math.min(s, this.dur - 0.05));
    if (this.loop && (this.pos < this.loop[0] || this.pos >= this.loop[1])) this.loop = null;
    if (p) { const ci = this.countIn; this.countIn = false; this.start(); this.countIn = ci; } else this.emit("state");
  }

  setLoop(a, b) {
    const p = this.playing; if (p) this.stop(true);
    this.loop = a != null && b != null && b - a > 0.5 ? [Math.max(0, a), Math.min(b, this.dur)] : null;
    if (this.loop) this.pos = this.loop[0];
    if (p) this.start(); else this.emit("state");
  }

  // speed / key: switch to the stretch engine on first use
  async setRate(r) { await this._retune(r, this.semis); }
  async setSemitones(s) { await this._retune(this.rate, s); }
  async _retune(rate, semis) {
    rate = Math.max(0.5, Math.min(1.25, rate)); semis = Math.max(-7, Math.min(7, Math.round(semis)));
    const p = this.playing; if (p) this.stop(true);
    this.rate = rate; this.semis = semis;
    if ((rate !== 1 || semis !== 0) && this.engine !== "stretch") {
      try { await (this._toStretchP ||= this._toStretch().finally(() => { this._toStretchP = null; })); }
      catch (e) {
        this.stretchError = String(e && e.message || e);
        // fall back: speed changes pitch, key change is display only
        this.rate = rate; this.semis = 0;
        this.emit("error", "stretch unavailable: " + this.stretchError);
      }
    }
    if (p) this.start(); else this.emit("state");
  }
  async _toStretch() {
    if (this.engine === "stretch") return;
    this.ensureCtx();
    if (!this.ctx.audioWorklet) throw new Error(window.isSecureContext === false
      ? "needs https (or localhost) for pitch-preserving speed and key change"
      : "AudioWorklet not supported by this browser");
    const n = this.stems.length;
    const node = await SignalsmithStretch(this.ctx, { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [n], channelCount: n, channelCountMode: "explicit" });
    const split = this.ctx.createChannelSplitter(n);
    // output gate: pausing must be silent at once, even if the worklet applies the
    // "inactive" schedule late (seen on a heavily loaded iOS Simulator host)
    const gate = this.ctx.createGain();
    gate.channelCount = n; gate.channelCountMode = "explicit"; gate.channelInterpretation = "discrete";
    gate.gain.value = 0;
    node.connect(gate); gate.connect(split);
    this.gate = gate;
    this.stems.forEach((k, i) => split.connect(this.gains[k], i));
    // copy each stem out (getChannelData works everywhere; copyFromChannel is missing on some
    // WebKit builds) and only drop the AudioBuffers once the worklet has accepted the data
    const arrs = this.stems.map(k => new Float32Array(this.bufs[k].getChannelData(0)));
    await node.addBuffers(arrs, arrs.map(a => a.buffer));
    node.configure({ preset: "default" });
    this.stems.forEach(k => { const b = this.bufs[k]; this.bufs[k] = { duration: b.duration, length: b.length }; });
    this.stretch = node; this.engine = "stretch"; this.splitter = split;
  }

  // ------------------------------------------------------------ metronome / count-in
  setBeats(beats, downbeats) { this.beats = beats || []; this.downbeats = new Set((downbeats || []).map(t => t.toFixed(3))); }
  click(at, accent) {
    const o = this.ctx.createOscillator(), g = this.ctx.createGain();
    o.frequency.value = accent ? 1760 : 1175; o.type = "square";
    g.gain.setValueAtTime(0, at); g.gain.linearRampToValueAtTime(accent ? 0.5 : 0.3, at + 0.002); g.gain.exponentialRampToValueAtTime(0.001, at + 0.05);
    o.connect(g); g.connect(this.clickGain); o.start(at); o.stop(at + 0.06); this._clicks.push(o);
  }
  beatPeriod() {
    const b = this.beats; if (b.length < 2) return 0.5;
    const d = []; for (let i = 1; i < b.length; i++) d.push(b[i] - b[i - 1]); d.sort((x, y) => x - y);
    return d[d.length >> 1];
  }
  scheduleCountIn(at) {
    const per = this.beatPeriod() / this.rate;
    // land the music start on the next beat: count 4 beats
    for (let i = 0; i < 4; i++) this.click(at + i * per, i === 0);
    this.emit("countin", { at, per });
    return 4 * per;
  }
  startMetronome() {
    this.stopMetronome();
    if (!this.metro || !this.beats.length) return;
    let last = -1;
    const tick = () => {
      if (!this.playing) return;
      const ahead = 0.25, nowT = this.now(), ctxNow = this.ctx.currentTime;
      const startT = this.counting ? this.pos : nowT;
      for (const b of this.beats) {
        if (b <= last || b < startT) continue;
        const at = Math.max(this.t0, ctxNow) + (b - startT) / this.rate;
        if (at > ctxNow + ahead) break;
        this.click(at, this.downbeats.has(b.toFixed(3)));
        last = b;
      }
    };
    tick(); this._sched = setInterval(tick, 60);
  }
  stopMetronome() {
    if (this._sched) clearInterval(this._sched); this._sched = null;
    this._clicks.forEach(o => { try { o.stop(); } catch (e) {} }); this._clicks = [];
  }
  setMetronome(on) { this.metro = !!on; if (this.playing) this.startMetronome(); this.emit("state"); }

  // ------------------------------------------------------------ test hooks
  stemTimes() {
    return Object.fromEntries(this.stems.map(k => {
      const r = this.srcs[k];
      if (this.engine === "stretch") return [k, this.now()];
      return [k, r && this.ctx ? r.offset + Math.max(0, this.ctx.currentTime - r.when) : this.pos];
    }));
  }
  levelDb() {
    if (!this.analyser) return -120;
    const a = new Float32Array(this.analyser.fftSize); this.analyser.getFloatTimeDomainData(a);
    let s = 0; for (const x of a) s += x * x; return +(20 * Math.log10(Math.sqrt(s / a.length) + 1e-9)).toFixed(1);
  }
  emit(type, detail) { this.dispatchEvent(new CustomEvent(type, { detail })); }
}
