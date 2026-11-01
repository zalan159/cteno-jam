// Turn an analysis into a renderable chart: sections, lyric lines with chords on the right
// syllable, instrumental rows. Shared by the phone chart, the big screen and the print view.
import { parseKey, transpose, simplify, shapeFor, bestCapo, keyName, parseChord } from "./theory.js";

export function chartOptions(an, { tr = 0, capo = "auto", simple = false } = {}) {
  const key = parseKey(an.key || "");
  const soundKey = key ? { tonic: (key.tonic + tr + 120) % 12, minor: key.minor } : null;
  const sounding = seg => {
    let sym = seg.chord;
    if (simple) sym = (an.simplified && an.simplified[seg.id]) || simplify(sym);
    return tr ? transpose(sym, tr, key) : sym;
  };
  // recommended capo for what is sounding now
  let rec;
  const aiCapo = an.capo && typeof an.capo.fret === "number" ? an.capo.fret : null;
  if (!tr && aiCapo != null) rec = { fret: aiCapo, ai: true };
  else rec = { ...bestCapo((an.chords || []).filter(c => c.chord !== "N").map(c => [sounding(c), c.end - c.start])), ai: false };
  const fret = capo === "auto" ? rec.fret : +capo || 0;
  const shown = seg => (seg.chord === "N" ? "" : shapeFor(sounding(seg), fret, soundKey));
  const shapesKey = soundKey ? keyName({ tonic: (soundKey.tonic - fret + 120) % 12, minor: soundKey.minor }) : "";
  return { key, soundKey, fret, rec, shown, sounding, shapesKey, soundKeyName: soundKey ? keyName(soundKey) : "" };
}

export function aiTouched(song) {
  const ids = new Set();
  for (const r of song.revisions || []) {
    if (r.status !== "applied" || r.source !== "ai") continue;
    const p = r.patch || {};
    if (p.id) ids.add(p.id);
  }
  return ids;
}

// items: {type:"section"|"line"|"inst", ...}
export function buildChart(an) {
  const lines = (an.lyrics && an.lyrics.lines) || [];
  const chords = (an.chords || []).filter(c => c.chord !== "N");
  const sections = (an.sections || []).slice().sort((a, b) => a.start - b.start);
  const used = new Set();
  const lineItems = lines.map(ln => {
    const units = ln.chars.map(c => ({ c: c.c, t: c.t, end: c.end, seg: null }));
    const lo = ln.start - 0.35, hi = ln.end + 0.05;
    for (const seg of chords) {
      // a chord that starts a little before the line and is still sounding when singing starts
      // belongs on the first word (pickup), not on an instrumental row
      const pickup = seg.start < lo && seg.start >= ln.start - 2.5 && seg.end > ln.start;
      if ((seg.start < lo && !pickup) || seg.start >= hi) continue;
      let j = 0, best = 1e9;
      units.forEach((u, i) => { const d = Math.abs((u.t ?? ln.start) - Math.max(seg.start, ln.start)); if (d < best) { best = d; j = i; } });
      if (!units[j].seg || (seg.end - seg.start) > (units[j].seg.end - units[j].seg.start)) units[j].seg = seg;
      used.add(seg.id);
    }
    if (units.length && !units[0].seg) {
      const cur = chords.find(s => s.start <= (units[0].t ?? ln.start) && (units[0].t ?? ln.start) < s.end);
      if (cur) units[0].seg = cur, units[0].carried = true;
    }
    return { type: "line", line: ln, start: ln.start, end: ln.end, units };
  });
  // instrumental rows: chords that did not land on a lyric line, grouped by the gaps between lines
  const items = [];
  let li = 0, pending = [];
  const flushInst = () => {
    if (!pending.length) return;
    items.push({ type: "inst", start: pending[0].start, end: pending[pending.length - 1].end, segs: pending });
    pending = [];
  };
  const events = [...lineItems.map(x => ({ t: x.start, x })), ...chords.filter(s => !used.has(s.id)).map(s => ({ t: s.start, s }))]
    .sort((a, b) => a.t - b.t);
  let si = 0;
  for (const ev of events) {
    while (si < sections.length && sections[si].start <= ev.t + 0.3) {
      flushInst(); items.push({ type: "section", ...sections[si] }); si++;
    }
    if (ev.x) { flushInst(); items.push(ev.x); li++; }
    else pending.push(ev.s);
  }
  flushInst();
  while (si < sections.length) items.push({ type: "section", ...sections[si++] });
  return items;
}

export function sectionAt(an, t) {
  return (an.sections || []).find(s => s.start <= t && t < s.end) || null;
}
export function chordAt(an, t) {
  const cs = an.chords || [];
  let i = -1;
  for (let k = 0; k < cs.length; k++) if (cs[k].start <= t && t < cs[k].end) { i = k; break; }
  return { i, cur: i >= 0 ? cs[i] : null, next: i >= 0 ? cs.slice(i + 1).find(c => c.chord !== "N" && c.chord !== cs[i].chord) : null };
}
export { parseChord };
