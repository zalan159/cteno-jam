// Chord theory, mirror of server/cteno_jam/theory.py (tests: web/test/theory.test.mjs).
export const SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
export const FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];
const PC = {};
SHARP.forEach((n, i) => (PC[n] = i));
FLAT.forEach((n, i) => (PC[n] = i));
Object.assign(PC, { Cb: 11, "B#": 0, "E#": 5, Fb: 4 });
export const QUALITIES = {
  "": [0, 4, 7], m: [0, 3, 7], 7: [0, 4, 7, 10], maj7: [0, 4, 7, 11], m7: [0, 3, 7, 10], sus4: [0, 5, 7],
  sus2: [0, 2, 7], dim: [0, 3, 6], aug: [0, 4, 8], 6: [0, 4, 7, 9], m6: [0, 3, 7, 9], add9: [0, 2, 4, 7],
  9: [0, 4, 7, 10, 2], m9: [0, 3, 7, 10, 2], "7sus4": [0, 5, 7, 10], dim7: [0, 3, 6, 9], m7b5: [0, 3, 6, 10], mmaj7: [0, 3, 7, 11],
};
const ALIAS = { M: "", maj: "", min: "m", "-": "m", M7: "maj7", Maj7: "maj7", min7: "m7", "-7": "m7", sus: "sus4", o: "dim", "+": "aug" };
export const SIMPLE = { "": "", m: "m", 7: "", maj7: "", m7: "m", sus4: "", sus2: "", dim: "m", aug: "", 6: "", m6: "m", add9: "", 9: "", m9: "m", "7sus4": "", dim7: "m", m7b5: "m", mmaj7: "m" };
const KEY_MAJ = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
const KEY_MIN = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"];
const FLAT_MAJ = new Set(["F", "Bb", "Eb", "Ab", "Db", "Gb"]);
const FLAT_MIN = new Set(["D", "G", "C", "F", "Bb", "Eb"]);
const LETTERS = "CDEFGAB", LPC = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
const MAJ = [0, 2, 4, 5, 7, 9, 11], MIN = [0, 2, 3, 5, 7, 8, 10];
const RE = /^([A-G])([#b]?)([^/]*)(?:\/([A-G])([#b]?))?$/;

export function parseChord(sym) {
  if (typeof sym !== "string") return null;
  const m = RE.exec(sym.trim());
  if (!m) return null;
  let q = m[3];
  q = q in ALIAS ? ALIAS[q] : q;
  if (!(q in QUALITIES)) return null;
  const rootName = m[1] + m[2], bassName = m[4] ? m[4] + m[5] : "";
  return { root: PC[rootName], quality: q, bass: m[4] ? PC[bassName] : null, rootName, bassName };
}
export function parseKey(name) {
  const m = /^\s*([A-G][#b]?)\s*(major|minor|maj|min|m)?\s*$/.exec(name || "");
  if (!m || !(m[1] in PC)) return null;
  return { tonic: PC[m[1]], minor: (m[2] || "major").startsWith("min") || m[2] === "m" };
}
export const keyName = k => (k.minor ? KEY_MIN : KEY_MAJ)[((k.tonic % 12) + 12) % 12] + (k.minor ? "m" : "");
function usesFlats(k) {
  const t = (k.minor ? KEY_MIN : KEY_MAJ)[k.tonic];
  return (k.minor ? FLAT_MIN : FLAT_MAJ).has(t) || t.includes("b");
}
function scaleNames(k) {
  const t = (k.minor ? KEY_MIN : KEY_MAJ)[k.tonic], li = LETTERS.indexOf(t[0]), out = {};
  (k.minor ? MIN : MAJ).forEach((step, deg) => {
    const L = LETTERS[(li + deg) % 7], pc = (k.tonic + step) % 12;
    const diff = ((pc - LPC[L] + 6 + 12) % 12) - 6;
    out[pc] = L + ({ 0: "", 1: "#", "-1": "b", 2: "##", "-2": "bb" })[diff];
  });
  return out;
}
export function noteName(pc, k) {
  pc = ((pc % 12) + 12) % 12;
  if (k) {
    const n = scaleNames(k)[pc];
    if (n && !n.includes("##") && !n.includes("bb") && !["Cb", "Fb", "E#", "B#"].includes(n)) return n;
    return (usesFlats(k) ? FLAT : SHARP)[pc];
  }
  return SHARP[pc];
}
export function transpose(sym, semis, key) {
  const c = parseChord(sym);
  if (!c) return sym;
  const nk = key ? { tonic: (((key.tonic + semis) % 12) + 12) % 12, minor: key.minor } : null;
  let out = noteName(c.root + semis, nk) + c.quality;
  if (c.bass != null) out += "/" + noteName(c.bass + semis, nk);
  return out;
}
export function simplify(sym) {
  const c = parseChord(sym);
  return c ? c.rootName + SIMPLE[c.quality] : sym;
}
const EASY = new Set(["C", "G", "D", "A", "E", "Am", "Em", "Dm", "A7", "D7", "E7", "G7", "C7", "B7", "Am7", "Em7", "Dm7", "Cmaj7", "Fmaj7", "Asus4", "Dsus4", "Esus4", "Asus2", "Dsus2"]);
export function bestCapo(chords, maxCapo = 7) {
  let best = null;
  const total = chords.reduce((a, [, d]) => a + d, 0) || 1;
  for (let capo = 0; capo <= maxCapo; capo++) {
    let easy = 0;
    for (const [sym, d] of chords) {
      const c = parseChord(sym);
      if (!c) { easy += d; continue; }
      const sh = SHARP[(((c.root - capo) % 12) + 12) % 12];
      if (EASY.has(sh + c.quality)) easy += d;
      else if (EASY.has(sh + SIMPLE[c.quality])) easy += 0.85 * d;
    }
    const score = easy / total - 0.015 * capo;
    if (!best || score > best[0]) best = [score, capo, easy / total];
  }
  return { fret: best[1], easy: best[2] };
}
// The chord shape a guitarist fingers with a capo on `capo`, for a sounding chord.
export function shapeFor(sym, capo, key) {
  if (!capo) return sym;
  const sk = key ? { tonic: (((key.tonic - capo) % 12) + 12) % 12, minor: key.minor } : null;
  // shapes read best in sharps (open-chord names)
  return transpose(sym, -capo, sk && usesFlats(sk) ? sk : null);
}
