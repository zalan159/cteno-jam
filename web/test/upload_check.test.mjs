// node --test web/test/  (no dependencies)
import test from "node:test";
import assert from "node:assert/strict";
import { encryptedFamily } from "../js/upload_check.js";

test("encrypted music-app downloads are spotted by any extension in the name", () => {
  assert.equal(encryptedFamily("B.o.B&Jessie J - Price Tag [mqms2].mgg2"), "qq");
  assert.equal(encryptedFamily("B.o.B&Jessie J - Price Tag [mqms2].mgg2.flac"), "qq");
  for (const n of ["a.mgg", "a.MFLAC", "a.mflac0", "a.qmc0", "a.qmcflac", "a.qmc8", "a.tkm", "a.bkcmp3"]) assert.equal(encryptedFamily(n), "qq", n);
  assert.equal(encryptedFamily("a.ncm"), "netease");
  for (const n of ["a.kgm", "a.kgma", "a.vpr"]) assert.equal(encryptedFamily(n), "kugou", n);
  assert.equal(encryptedFamily("a.kwm"), "kuwo");
  assert.equal(encryptedFamily("a.m4p"), "apple");
});

test("regular audio passes", () => {
  for (const n of ["song.mp3", "song.m4a", "song.flac", "Mr. Brightside.wav", "no-extension", ""]) assert.equal(encryptedFamily(n), null, n);
});
