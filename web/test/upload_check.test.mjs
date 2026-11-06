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

import { acceptFor, checkPicked, pickRecordingType, extForType, micErrorKey } from "../js/upload_check.js";

const IOS_SAFARI = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1";
const IOS_WX = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.53(0x18003531) NetType/WIFI Language/zh_CN";
const ANDROID_WX = "Mozilla/5.0 (Linux; Android 14; V2309A Build/UP1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/122.0.6261.120 Mobile Safari/537.36 XWEB/1220133 MMWEBSDK/20240404 MicroMessenger/8.0.49.2600(0x2800315A) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64";

test("accept lists audio/* plus phone extensions; WeChat on Android accepts anything", () => {
  const a = acceptFor(IOS_SAFARI);
  assert.ok(a.startsWith("audio/*,"));
  for (const e of [".mp3", ".m4a", ".amr", ".flac", ".wav", ".aac", ".3gp"]) assert.ok(a.split(",").includes(e), e);
  assert.equal(acceptFor(IOS_WX), a);           // iOS WeChat uses the system picker: keep the filter
  assert.equal(acceptFor(ANDROID_WX), "*/*");   // X5/XWeb: an audio filter hides the file manager
});

test("picked files: audio by extension or type; WeChat files without extension are let through", () => {
  assert.equal(checkPicked("song.mp3", ""), "ok");
  assert.equal(checkPicked("voice.amr", ""), "ok");
  assert.equal(checkPicked("1730871234567", ""), "ok");
  assert.equal(checkPicked("1730871234567", "application/octet-stream"), "ok");
  assert.equal(checkPicked("rec", "audio/mp4"), "ok");
  assert.equal(checkPicked("IMG_0001.HEIC", "image/heic"), "not_audio");
  assert.equal(checkPicked("report.pdf", "application/pdf"), "not_audio");
  assert.equal(checkPicked("photo.jpg", ""), "not_audio");
});

test("recording format: AAC/MP4 on Safari, Opus/WebM on Chrome, file extension follows", () => {
  const safari = new Set(["audio/mp4", "audio/mp4;codecs=mp4a.40.2"]);
  const chrome = new Set(["audio/webm", "audio/webm;codecs=opus"]);
  assert.equal(pickRecordingType(t => safari.has(t)), "audio/mp4;codecs=mp4a.40.2");
  assert.equal(pickRecordingType(t => chrome.has(t)), "audio/webm;codecs=opus");
  assert.equal(pickRecordingType(() => false), "");
  assert.equal(pickRecordingType(() => { throw new Error("old"); }), "");
  assert.equal(extForType("audio/mp4"), "m4a");
  assert.equal(extForType("audio/webm;codecs=opus"), "webm");
  assert.equal(extForType("audio/ogg"), "ogg");
  assert.equal(extForType(""), "m4a");
});

test("microphone errors map to messages the user can act on", () => {
  assert.equal(micErrorKey({ name: "NotAllowedError" }), "rec_denied");
  assert.equal(micErrorKey({ name: "NotFoundError" }), "rec_nomic");
  assert.equal(micErrorKey({ name: "NotReadableError" }), "rec_busy");
  assert.equal(micErrorKey(new Error("x")), "rec_failed");
});
