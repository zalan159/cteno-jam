// node --test web/test/  (no dependencies)
import test from "node:test";
import assert from "node:assert/strict";
import { parseChord, parseKey, transpose, simplify, bestCapo, shapeFor, noteName } from "../js/theory.js";
import { buildChart, chartOptions } from "../js/chart.js";

test("parse and transpose with key-aware spelling", () => {
  const E = parseKey("E major");
  assert.equal(transpose("G#m", 1, E), "Am");
  assert.equal(transpose("B7", 1, E), "C7");
  const F = parseKey("F major");
  assert.equal(transpose("C", 0, F), "C");
  assert.equal(noteName(10, F), "Bb");
  assert.equal(transpose("E", 1, null), "F");
  assert.equal(parseChord("H7"), null);
  assert.equal(parseChord("Bb/D").bass, 2);
});

test("simplify and capo, same answers as theory.py", () => {
  assert.equal(simplify("F#m7"), "F#m");
  assert.equal(simplify("B/D#"), "B");
  assert.equal(bestCapo([["F", 4], ["Bb", 4], ["C", 4], ["Dm", 4]]).fret, 3);
  assert.equal(bestCapo([["G", 1], ["C", 1], ["D", 1], ["Em", 1]]).fret, 0);
  assert.equal(shapeFor("F", 3, parseKey("F major")), "D");
  assert.equal(shapeFor("Bb", 3, parseKey("F major")), "G");
});

test("chart puts chords on the syllable being sung", () => {
  const an = {
    key: "D major", chords: [{ id: "c1", start: 0, end: 2, chord: "D" }, { id: "c2", start: 2, end: 4, chord: "G" }, { id: "c3", start: 4, end: 9, chord: "A" }],
    sections: [{ id: "s1", start: 0, end: 9, label: "verse" }],
    lyrics: { lines: [{ id: "l1", start: 0.5, end: 3.9, text: "a b c", chars: [{ c: "a ", t: 0.5 }, { c: "b ", t: 2.05 }, { c: "c", t: 3 }] }] },
  };
  const items = buildChart(an);
  assert.deepEqual(items.map(i => i.type), ["section", "line", "inst"]);
  const line = items[1];
  assert.equal(line.units[0].seg.chord, "D");
  assert.equal(line.units[1].seg.chord, "G");
  assert.equal(items[2].segs[0].chord, "A");
  const o = chartOptions(an, { tr: 2, capo: 0 });
  assert.equal(o.shown(an.chords[0]), "E");
  assert.equal(o.soundKeyName, "E");
});
