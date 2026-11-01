// Sync client. One WebSocket per tab; the server relays state from the host to everyone else
// and commands from remotes to the host. Clock offset to the server is estimated from pings.
export class Sync extends EventTarget {
  constructor(code, role, name = "") {
    super();
    this.code = code; this.role = role; this.name = name; this.offset = 0; this.rtt = 1e9; this.peers = 0;
    this.ws = null; this.state = null; this.closed = false; this._backoff = 500; this.connected = false;
    this.connect();
  }
  url() {
    const base = (window.JAM_CONFIG && window.JAM_CONFIG.syncUrl) || `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}`;
    return `${base.replace(/\/$/, "")}/ws/room/${this.code}`;
  }
  connect() {
    if (this.closed) return;
    let ws;
    try { ws = new WebSocket(this.url()); } catch (e) { this._retry(); return; }
    this.ws = ws;
    ws.onopen = () => {
      this.connected = true; this._backoff = 500;
      ws.send(JSON.stringify({ t: "hello", role: this.role, name: this.name }));
      this._pings = 0; this.ping();
      this._pi = setInterval(() => this.ping(), this._pings < 5 ? 400 : 5000);
      this.emit("open");
    };
    ws.onmessage = ev => {
      let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.t === "pong") {
        const now = Date.now(), rtt = now - m.c;
        if (rtt < this.rtt * 1.5 || this._pings < 5) { this.rtt = Math.min(rtt, this.rtt); this.offset = m.s - (m.c + rtt / 2); }
        if (++this._pings === 5) { clearInterval(this._pi); this._pi = setInterval(() => this.ping(), 5000); }
      } else if (m.t === "welcome") {
        this.peers = m.n; if (m.state) { this.state = m.state; this.emit("state", m.state); } this.emit("peers", m);
      } else if (m.t === "peers") { this.peers = m.n; this.emit("peers", m); }
      else if (m.t === "state") { this.state = m; this.emit("state", m); }
      else if (m.t === "cmd") this.emit("cmd", m);
    };
    ws.onclose = () => { this.connected = false; clearInterval(this._pi); this.emit("close"); this._retry(); };
    ws.onerror = () => {};
  }
  _retry() { if (this.closed) return; setTimeout(() => this.connect(), this._backoff); this._backoff = Math.min(this._backoff * 2, 8000); }
  ping() { if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify({ t: "ping", c: Date.now() })); }
  serverNow() { return Date.now() + this.offset; }
  send(obj) { if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(obj)); }
  publish(state) { this.send({ t: "state", ...state }); }
  command(cmd, arg) { this.send({ t: "cmd", cmd, arg }); }
  // live position of a received state
  livePos(st = this.state) {
    if (!st) return 0;
    return st.playing ? st.pos + Math.max(0, this.serverNow() - st.at) / 1000 * (st.rate || 1) : st.pos;
  }
  close() { this.closed = true; clearInterval(this._pi); if (this.ws) this.ws.close(); }
  emit(type, detail) { this.dispatchEvent(new CustomEvent(type, { detail })); }
}

export function randomRoom() {
  const a = "23456789abcdefghjkmnpqrstuvwxyz"; let s = "";
  const r = crypto.getRandomValues(new Uint8Array(6)); r.forEach(x => (s += a[x % a.length])); return s;
}
