// Guitar chord diagrams (SVG). Open shapes from a table; everything else as an E- or A-shape barre.
import { parseChord, SHARP } from "./theory.js";

// strings low E -> high E; -1 = muted, 0 = open; fingers optional
const OPEN = {
  C: [-1, 3, 2, 0, 1, 0], D: [-1, -1, 0, 2, 3, 2], E: [0, 2, 2, 1, 0, 0], G: [3, 2, 0, 0, 0, 3], A: [-1, 0, 2, 2, 2, 0],
  Am: [-1, 0, 2, 2, 1, 0], Em: [0, 2, 2, 0, 0, 0], Dm: [-1, -1, 0, 2, 3, 1],
  C7: [-1, 3, 2, 3, 1, 0], D7: [-1, -1, 0, 2, 1, 2], E7: [0, 2, 0, 1, 0, 0], G7: [3, 2, 0, 0, 0, 1], A7: [-1, 0, 2, 0, 2, 0], B7: [-1, 2, 1, 2, 0, 2],
  Am7: [-1, 0, 2, 0, 1, 0], Em7: [0, 2, 0, 0, 0, 0], Dm7: [-1, -1, 0, 2, 1, 1],
  Cmaj7: [-1, 3, 2, 0, 0, 0], Fmaj7: [-1, -1, 3, 2, 1, 0], Gmaj7: [3, 2, 0, 0, 0, 2], Dmaj7: [-1, -1, 0, 2, 2, 2], Amaj7: [-1, 0, 2, 1, 2, 0], Emaj7: [0, 2, 1, 1, 0, 0],
  Dsus4: [-1, -1, 0, 2, 3, 3], Asus4: [-1, 0, 2, 2, 3, 0], Esus4: [0, 2, 2, 2, 0, 0], Dsus2: [-1, -1, 0, 2, 3, 0], Asus2: [-1, 0, 2, 2, 0, 0],
  Cadd9: [-1, 3, 2, 0, 3, 0], G6: [3, 2, 0, 0, 0, 0], A6: [-1, 0, 2, 2, 2, 2], E6: [0, 2, 2, 1, 2, 0],
};
// relative to the barre fret (root on string 6 for E-shape, string 5 for A-shape)
const E_SHAPE = { "": [0, 2, 2, 1, 0, 0], m: [0, 2, 2, 0, 0, 0], 7: [0, 2, 0, 1, 0, 0], m7: [0, 2, 0, 0, 0, 0], maj7: [0, 2, 1, 1, 0, 0],
  sus4: [0, 2, 2, 2, 0, 0], "7sus4": [0, 2, 0, 2, 0, 0], 6: [0, 2, 2, 1, 2, 0], m6: [0, 2, 2, 0, 2, 0] };
const A_SHAPE = { "": [-1, 0, 2, 2, 2, 0], m: [-1, 0, 2, 2, 1, 0], 7: [-1, 0, 2, 0, 2, 0], m7: [-1, 0, 2, 0, 1, 0], maj7: [-1, 0, 2, 1, 2, 0],
  sus4: [-1, 0, 2, 2, 3, 0], sus2: [-1, 0, 2, 2, 0, 0], dim: [-1, 0, 1, 2, 1, -1], m7b5: [-1, 0, 1, 0, 1, -1], dim7: [-1, 0, 1, 2, 1, 2],
  add9: [-1, 0, 2, 4, 2, 0] };
const FALLBACK_Q = { 9: "7", m9: "m7", add9: "", aug: "", mmaj7: "m", "6": "", m6: "m", dim7: "dim", m7b5: "dim" };

export function voicing(sym) {
  const c = parseChord(sym);
  if (!c) return null;
  const name = SHARP[c.root] + c.quality;
  const flatName = c.rootName + c.quality;
  if (OPEN[flatName]) return { frets: OPEN[flatName], base: 1 };
  if (OPEN[name]) return { frets: OPEN[name], base: 1 };
  let q = c.quality;
  const opts = [];
  for (let tries = 0; tries < 2; tries++) {
    if (E_SHAPE[q]) { const f = (c.root - 4 + 12) % 12 || 12; opts.push({ rel: E_SHAPE[q], fret: f }); }
    if (A_SHAPE[q]) { const f = (c.root - 9 + 12) % 12 || 12; opts.push({ rel: A_SHAPE[q], fret: f }); }
    if (opts.length) break;
    q = FALLBACK_Q[q] ?? "";
  }
  if (!opts.length) return null;
  const best = opts.sort((a, b) => a.fret - b.fret)[0];
  const frets = best.rel.map(x => (x < 0 ? -1 : x + best.fret));
  return { frets, base: best.fret, barre: best.fret };
}

export function diagramSVG(sym, label) {
  const v = voicing(sym);
  const W = 64, H = 84, x0 = 10, y0 = 22, dx = 9, dy = 11, rows = 5;
  let s = `<svg class="chord-svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${label || sym}">`;
  s += `<text x="${W / 2}" y="11" text-anchor="middle" class="cd-name">${label || sym}</text>`;
  if (!v) return s + `<text x="${W / 2}" y="50" text-anchor="middle" class="cd-x">?</text></svg>`;
  const played = v.frets.filter(f => f > 0);
  const lo = played.length ? Math.min(...played) : 1, hi = played.length ? Math.max(...played) : 1;
  const base = hi <= 5 ? 1 : lo;
  for (let i = 0; i <= rows; i++) s += `<line x1="${x0}" x2="${x0 + 5 * dx}" y1="${y0 + i * dy}" y2="${y0 + i * dy}" class="${i === 0 && base === 1 ? "cd-nut" : "cd-l"}"/>`;
  for (let j = 0; j < 6; j++) s += `<line x1="${x0 + j * dx}" x2="${x0 + j * dx}" y1="${y0}" y2="${y0 + rows * dy}" class="cd-l"/>`;
  if (base > 1) s += `<text x="${x0 + 5 * dx + 3}" y="${y0 + dy - 2}" class="cd-fr">${base}</text>`;
  if (v.barre && v.barre >= base) {
    const r = v.barre - base;
    const strs = v.frets.map((f, j) => (f === v.barre ? j : -1)).filter(j => j >= 0);
    if (strs.length > 1) s += `<rect x="${x0 + strs[0] * dx - 3}" y="${y0 + r * dy + 2}" width="${(strs[strs.length - 1] - strs[0]) * dx + 6}" height="7" rx="3.5" class="cd-dot"/>`;
  }
  v.frets.forEach((f, j) => {
    const x = x0 + j * dx;
    if (f < 0) s += `<text x="${x}" y="${y0 - 3}" text-anchor="middle" class="cd-x">×</text>`;
    else if (f === 0) s += `<circle cx="${x}" cy="${y0 - 6}" r="2.6" class="cd-open"/>`;
    else s += `<circle cx="${x}" cy="${y0 + (f - base) * dy + dy / 2}" r="3.6" class="cd-dot"/>`;
  });
  return s + "</svg>";
}
