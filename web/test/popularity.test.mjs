// node --test web/test/  (no dependencies)
import test from "node:test";
import assert from "node:assert/strict";
import { compactCount, playsLabel, mixResults, sortLocal, JAMENDO_PER_PLAY } from "../js/popularity.js";

test("compact play counts, zh and en, never rounded up", () => {
  const zh = [[0, "0"], [7, "7"], [9999, "9999"], [10000, "1万"], [12345, "1.2万"], [19999, "1.9万"], [123456, "12万"],
    [13845501, "1384万"], [100000000, "1亿"], [234567890, "2.3亿"]];
  for (const [n, s] of zh) assert.equal(compactCount(n, "zh"), s, String(n));
  const en = [[0, "0"], [999, "999"], [1000, "1K"], [1234, "1.2K"], [12345, "12.3K"], [123456, "123K"], [999999, "999K"],
    [1000000, "1M"], [13845501, "13.8M"], [234567890, "234M"], [1234567890, "1.2B"]];
  for (const [n, s] of en) assert.equal(compactCount(n, "en"), s, String(n));
  assert.equal(playsLabel(12345, "zh"), "▶ 1.2万");
  assert.equal(playsLabel(12345, "en"), "▶ 12.3K");
  assert.equal(compactCount(-3), "0"); assert.equal(compactCount("x"), "0"); assert.equal(compactCount(undefined, "en"), "0");
});

test("local songs: most played first, ties newest first", () => {
  const s = sortLocal([{ id: "a", plays: 2, created: 1 }, { id: "b", plays: 9, created: 1 }, { id: "c", plays: 2, created: 5 }, { id: "d", created: 9 }]);
  assert.deepEqual(s.map(x => x.id), ["b", "c", "a", "d"]);
});

test("mixed list: 1 local play = JAMENDO_PER_PLAY Jamendo listens, merged by score, local wins ties", () => {
  assert.equal(JAMENDO_PER_PLAY, 1000);
  const local = [{ id: "L1", plays: 50 }, { id: "L2", plays: 3 }, { id: "L0", plays: 0 }];
  // Jamendo already ranked by order=popularity_total
  const jm = [{ id: "J1", listens: 13845501 }, { id: "J2", listens: 50000 }, { id: "J3", listens: 3000 }, { id: "J4", listens: 10 }];
  const r = mixResults(local, jm);
  // explicit expectation: scores J1 13.8M > L1 50k == J2 50k (local wins tie) > L2 3k == J3 3k (local wins) > J4 10 > L0 0
  assert.deepEqual(r.map(x => x.kind === "local" ? x.song.id : x.track.id), ["J1", "L1", "J2", "L2", "J3", "J4", "L0"]);
  assert.deepEqual(r.map(x => x.score), [13845501, 50000, 50000, 3000, 3000, 10, 0]);
});

test("mixed list is sorted by the shown number even when Jamendo's popularity order is not; imported tracks shown once", () => {
  const local = [{ id: "x", plays: 1, source: { kind: "jamendo", id: "77" } }];
  // real API, q=love, order=popularity_total: 2,129,137 came before 2,670,241
  const jm = [{ id: "5", listens: 2129137 }, { id: "77", listens: 9 }, { id: "6", listens: 2670241 }, { id: "7", listens: 1000 }];
  const r = mixResults(local, jm);
  assert.deepEqual(r.map(x => x.kind === "local" ? "L:" + x.song.id : "J:" + x.track.id), ["J:6", "J:5", "L:x", "J:7"]);   // L:x 1000 ties J:7 -> local first
  const scores = r.map(x => x.score); assert.deepEqual(scores, [...scores].sort((a, b) => b - a));
  assert.deepEqual(mixResults([], []), []);
  assert.deepEqual(mixResults(null, [{ id: "1" }]).map(x => x.kind), ["jamendo"]);
});
