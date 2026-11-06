// Phone audio sources: record in the browser, pick from Files / WeChat (no extension, odd types),
// and Jamendo results mixed into the library search by popularity (preview, use, license shown). 390 px screenshots.
// The server must run with the fake Jamendo API (scripts/fake_jamendo.py) for the Jamendo part:
//   JAM_JAMENDO_CLIENT_ID=e2e JAM_JAMENDO_API_URL=http://127.0.0.1:8782/v3.0
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { deleteFromPage, deleteWithToken } from "./owner.js";

const EVID = process.env.JAM_EVIDENCE || "../docs/evidence/e2e";
const DEMO = process.env.JAM_DEMO_DIR || "../demo/source";
const AUDIO = path.join(DEMO, "twinkle.mp3");
const log = [];
const note = (step, data) => { const row = { t: new Date().toISOString(), step, ...data }; log.push(row); console.log(JSON.stringify(row)); };
// the home page shows tabs + songs only: upload is a sheet behind #upOpen, search a box behind #searchBtn
async function openUpload(page) { if (!(await page.locator(".upsheet").count())) await page.click("#upOpen"); await expect(page.locator(".upsheet #file")).toBeAttached(); }
async function openSearch(page) { if (await page.locator("#q").isHidden()) await page.click("#searchBtn"); await expect(page.locator("#q")).toBeVisible(); }
const shot = (page, name, full = false) => page.screenshot({ path: path.join(EVID, `${test.info().project.name}-${name}.png`), fullPage: full });
const ANDROID_WX = "Mozilla/5.0 (Linux; Android 14; V2309A Build/UP1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/122.0.6261.120 Mobile Safari/537.36 XWEB/1220133 MMWEBSDK/20240404 MicroMessenger/8.0.49.2600(0x2800315A) WeChat/arm64 Weixin NetType/WIFI Language/zh_CN ABI/arm64";
const IOS_WX = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.53(0x18003531) NetType/WIFI Language/zh_CN";

test.afterAll(async () => {
  fs.mkdirSync(EVID, { recursive: true });
  fs.appendFileSync(path.join(EVID, "steps.jsonl"), log.map(r => JSON.stringify(r)).join("\n") + "\n");
});

async function waitProcessed(request, id, ms = 10 * 60_000) {
  const t0 = Date.now();
  for (;;) {
    const m = await (await request.get(`/api/songs/${id}`)).json();
    if (m.status === "ready" || m.status === "failed") return { ...m, seconds: (Date.now() - t0) / 1000 };
    if (Date.now() - t0 > ms) throw new Error("processing timed out");
    await new Promise(r => setTimeout(r, 800));
  }
}
// clean up a song created by this page's browser (its management token is in the page's localStorage)
async function remove(page, request, id) { await deleteFromPage(page, request, id); }
async function fitsPhone(page) {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const over = [...document.querySelectorAll("#drop, .src, .sheetpanel button, .song, .song button, .rec button")]
      .filter(e => e.offsetParent && e.getBoundingClientRect().right > vw + 1).map(e => e.id || e.className);
    return { vw, scrollW: document.documentElement.scrollWidth, over };
  });
}

test("entry points: record and files/WeChat tip; no separate free-music button", async ({ page }, info) => {
  await page.goto("/?lang=zh");
  await openUpload(page);
  await expect(page.locator("#recBtn")).toBeVisible();
  await expect(page.locator("#jmBtn")).toHaveCount(0);           // Jamendo lives in the search box now
  await expect(page.locator("#q")).toHaveAttribute("placeholder", /免费音乐/);
  const accept = await page.getAttribute("#file", "accept");
  note("entries", { proj: info.project.name, accept, vw: page.viewportSize().width });
  expect(accept).toContain("audio/*"); expect(accept).toContain(".amr"); expect(accept).toContain(".m4a");
  const fit = await fitsPhone(page);
  expect(fit.over).toEqual([]); expect(fit.scrollW).toBeLessThanOrEqual(fit.vw + 1);
  await page.locator("#wxTip summary").click();
  await expect(page.locator("#wxTip p").first()).toContainText("微信");
  await shot(page, "30-sources-zh");
  await page.goto("/?lang=en");
  await openUpload(page);
  await expect(page.locator("#recBtn")).toContainText("Record");
  await expect(page.locator("#q")).toHaveAttribute("placeholder", /free music/);
  expect((await fitsPhone(page)).over).toEqual([]);
  await shot(page, "31-sources-en");
});

test("no Jamendo client id: search only looks in the library, no errors", async ({ page }, info) => {
  await page.route("**/api/info", async route => {
    const r = await route.fetch(); const j = await r.json();
    await route.fulfill({ response: r, json: { ...j, jamendo: false } });
  });
  const jmCalls = [];
  page.on("request", r => { if (r.url().includes("/api/jamendo/")) jmCalls.push(r.url()); });
  await page.goto("/?lang=zh");
  await expect(page.locator("#q")).toHaveAttribute("placeholder", "搜索歌曲");
  await openSearch(page);
  await page.fill("#q", "twinkle");
  await page.waitForTimeout(1200);
  expect(jmCalls).toEqual([]);
  await expect(page.locator('.song[data-kind="jamendo"]')).toHaveCount(0);
  await expect(page.locator(".jmNote")).toHaveCount(0);
  await expect(page.locator(".card.err")).toHaveCount(0);
  note("no-jamendo", { proj: info.project.name, jmCalls: jmCalls.length, rows: await page.locator(".song").count() });
});

test("record in the browser → use it → it is processed like an upload", async ({ page, request, browserName }, info) => {
  test.skip(browserName === "webkit", "Playwright's WebKit has no capture devices; Safari's AAC/MP4 path is covered by the format unit tests and the server-side MIME/duration tests");
  await page.context().grantPermissions(["microphone"]);
  await page.goto("/?lang=zh");
  await openUpload(page);
  await page.click("#recBtn");
  await expect(page.locator(".sheetpanel h3").last()).toHaveText("录一段");
  await page.click("#recStart");
  await page.waitForFunction(() => window.__jamRec && window.__jamRec.state === "recording");
  await page.waitForTimeout(6500);
  await shot(page, "32-recording");
  await page.click("#recStop");
  await page.waitForFunction(() => window.__jamRec.state === "done");
  const rec = await page.evaluate(() => window.__jamRec);
  note("recorded", { proj: info.project.name, ...rec });
  expect(rec.seconds).toBeGreaterThan(5); expect(rec.size).toBeGreaterThan(1000);
  await expect(page.locator("#recUse")).toBeVisible();
  expect((await fitsPhone(page)).over).toEqual([]);
  await shot(page, "33-recorded");
  await page.click("#recUse");
  await expect(page.locator("#upForm")).toBeVisible();
  await expect(page.locator("#upPreview")).toBeVisible();
  const title = `rec e2e ${info.project.name} ${Date.now() % 100000}`;
  await page.fill("#upTitle", title);
  await page.click("#upGo");
  await expect(page.locator(".song", { hasText: title })).toBeVisible();
  const id = (await (await request.get("/api/songs?q=" + encodeURIComponent(title))).json()).songs[0].id;
  const m = await waitProcessed(request, id);
  note("recording-processed", { proj: info.project.name, id, status: m.status, error: m.error, duration: m.duration, seconds: m.seconds });
  expect(m.status, m.error || "").toBe("ready");
  expect(m.duration).toBeGreaterThan(5);
  await remove(page, request, id);
});

test("microphone blocked: a plain message, and the upload still works", async ({ page }, info) => {
  await page.addInitScript(() => {
    // what Safari/Chrome do after the user taps "Don't Allow" (or blocked it in the site settings)
    const deny = () => Promise.reject(Object.assign(new Error("Permission denied"), { name: "NotAllowedError" }));
    if (window.MediaDevices) Object.defineProperty(MediaDevices.prototype, "getUserMedia", { value: deny, configurable: true, writable: true });
    if (!navigator.mediaDevices) Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: deny }, configurable: true });
    if (!window.MediaRecorder) window.MediaRecorder = function () {};
  });
  await page.goto("/?lang=zh");
  await openUpload(page);
  await page.click("#recBtn");
  await page.click("#recStart");
  await expect(page.locator("#recMsg")).toContainText("麦克风被拒绝");
  await expect(page.locator("#recMsg")).toHaveClass(/err/);
  await shot(page, "34-mic-denied");
  const during = await page.evaluate(() => navigator.audioSession ? navigator.audioSession.type : null);
  note("mic-denied", { proj: info.project.name, msg: await page.textContent("#recMsg"), audioSession: during });
  await page.click("#recCancel");
  if (during !== null) {  // Safari: recording needs play-and-record; the player's "playback" comes back afterwards
    expect(during).toBe("play-and-record");
    expect(await page.evaluate(() => navigator.audioSession.type)).not.toBe("play-and-record");
  }
  await page.setInputFiles("#file", AUDIO);
  await expect(page.locator("#upForm")).toBeVisible();
});

test("files from WeChat / Files: no extension, wrong kind, Android WeChat accept", async ({ browser, request, baseURL }, info) => {
  const dir = test.info().outputDir; fs.mkdirSync(dir, { recursive: true });
  for (const [ua, name] of [[ANDROID_WX, "android-wechat"], [IOS_WX, "ios-wechat"]]) {
    const ctx = await browser.newContext({ ...info.project.use, userAgent: ua, baseURL, locale: "zh-CN" });
    const page = await ctx.newPage();
    await page.goto("/?lang=zh");
    await openUpload(page);
    const accept = await page.getAttribute("#file", "accept");
    await expect(page.locator("#wxTip")).toHaveAttribute("open", "");
    note("wechat-accept", { proj: info.project.name, ua: name, accept, tip: await page.locator("#wxTip").innerText() });
    if (name === "android-wechat") {
      expect(accept).toBe("*/*");
      await expect(page.locator("#wxTip")).toContainText("Download/WeChat");
      await shot(page, "35-wechat-android");
      // a photo picked by mistake is caught at once
      const jpg = path.join(dir, "IMG_0001.jpg"); fs.writeFileSync(jpg, Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0, 0x10]));
      await page.setInputFiles("#file", jpg);
      await expect(page.locator("#upFile")).toContainText("不是音频文件");
      await expect(page.locator("#upForm")).toBeHidden();
      // WeChat hands over received files with a numeric name and no extension
      const noext = path.join(dir, "1730871234567"); fs.copyFileSync(AUDIO, noext);
      await page.setInputFiles("#file", { name: "1730871234567", mimeType: "", buffer: fs.readFileSync(noext) });
      await expect(page.locator("#upForm")).toBeVisible();
      const title = `wechat noext ${info.project.name} ${Date.now() % 100000}`;
      await page.fill("#upTitle", title);
      await page.click("#upGo");
      await expect(page.locator(".song", { hasText: title })).toBeVisible();
      const s = (await (await request.get("/api/songs?q=" + encodeURIComponent(title))).json()).songs[0];
      note("wechat-noext-upload", { proj: info.project.name, id: s.id, status: s.status });
      expect(["queued", "processing", "ready"]).toContain(s.status);
      await remove(page, request, s.id);
      // the encrypted-download refusal still applies here
      await openUpload(page);   // the sheet closed itself after the upload above
      const ncm = path.join(dir, "歌.ncm"); fs.writeFileSync(ncm, Buffer.concat([Buffer.from("CTENFDAM"), Buffer.alloc(256)]));
      await page.setInputFiles("#file", ncm);
      await expect(page.locator("#upFile")).toContainText("网易云音乐的加密文件");
    } else {
      expect(accept).toContain("audio/*");
      await expect(page.locator("#wxTip")).toContainText("存储到「文件」");
    }
    await ctx.close();
  }
});

// Mixed search: local songs and Jamendo results in one list, most popular first.
// Fake Jamendo listens: Twinkle Twinkle 1,234,567 · Frère Jacques 12,345 · Twinkle Lullaby 800 (and a locked track);
// its popularity order is deliberately not by listens (Lullaby 800 before Frère Jacques 12,345), like the real API.
// Our local "Twinkle Star" gets 2 plays -> score 2 x 1000 = 2000, so the expected order for "twinkle" is
// Twinkle Twinkle (Jamendo, 1.23M) > Twinkle Star (local, 2000) > Twinkle Lullaby (Jamendo, 800).
test("search mixes the library with Jamendo by popularity; tap a result to use it; plays are counted", async ({ page, request }, info) => {
  const lang = info.project.name.startsWith("webkit") ? "zh" : "en";   // 390 px shots in both languages
  const title = `Twinkle Star local ${info.project.name}`;
  const up = await request.post("/api/songs", { multipart: { file: { name: "twinkle.mp3", mimeType: "audio/mpeg", buffer: fs.readFileSync(AUDIO) }, title } });
  expect(up.status(), await up.text()).toBe(201);
  const local = await up.json();
  expect(local.owner_token).toBeTruthy();
  expect((await waitProcessed(request, local.id)).status).toBe("ready");
  for (const s of ["e2e-sess-aaaa", "e2e-sess-bbbb", "e2e-sess-bbbb"]) await request.post(`/api/songs/${local.id}/play`, { data: { session: s } });
  expect((await (await request.get(`/api/songs/${local.id}`)).json()).plays).toBe(2);    // the repeat within 30 s is not counted

  await page.goto(`/?lang=${lang}`);
  await openSearch(page);
  await page.fill("#q", "twinkle");
  await expect(page.locator('.song[data-kind="jamendo"]')).toHaveCount(2);
  // the bundled demo songs (seeded for the relay suite) have 0 plays and sort last; leave them out here
  const rows = (await page.evaluate(() => window.__jamList)).filter(r => !String(r.id).startsWith("demo-"));
  note("mixed", { proj: info.project.name, rows });
  expect(rows.map(r => r.title)).toEqual(["Twinkle Twinkle (e2e)", title, "Twinkle Lullaby (e2e)"]);
  expect(rows.map(r => r.kind)).toEqual(["jamendo", "local", "jamendo"]);
  expect(rows.map(r => r.title).join("|")).not.toContain("Locked");
  const first = page.locator(".song").nth(0), second = page.locator(".song").nth(1);
  await expect(first.locator(".plays")).toHaveText(lang === "zh" ? "▶ 123万" : "▶ 1.2M");
  await expect(first.locator(".badge.srcb")).toHaveText("Jamendo");
  await expect(first.locator(".badge.lic")).toHaveText("CC BY-SA 3.0");
  await expect(first.locator(".badge.lic")).toHaveAttribute("href", /creativecommons\.org\/licenses\/by-sa/);
  await expect(second.locator(".plays")).toHaveText("▶ 2");
  await expect(second.locator(".badge.srcb")).toHaveText(lang === "zh" ? "曲库" : "Library");
  await expect(page.locator(".song").nth(2).locator(".plays")).toHaveText("▶ 800");
  expect((await fitsPhone(page)).over).toEqual([]);
  // preview plays through the server's proxy (the client id never reaches the page)
  await first.locator(".jmPlay").click();
  await page.waitForFunction(() => window.__jamPreview && window.__jamPreview.currentTime > 0.3, null, { timeout: 20_000 });
  const src = await page.evaluate(() => window.__jamPreview.currentSrc || window.__jamPreview.src);
  expect(src).toMatch(/\/api\/jamendo\/preview\/900001\.mp3$/);
  await expect(first.locator(".jmPlay")).toHaveText("❚❚");
  await shot(page, `38-search-mixed-${lang}`, true);
  await first.locator(".jmPlay").click();

  // a word Jamendo only has a locked track for: library-only "nothing found", no error
  await openSearch(page);
  await page.fill("#q", "locked");
  await expect(page.locator(".card.muted")).toBeVisible();
  await expect(page.locator(".song")).toHaveCount(0);

  // tap the Jamendo row itself: it is imported and then lives in the library with its license
  await openSearch(page);
  await page.fill("#q", "twinkle");
  await expect(page.locator('.song[data-kind="jamendo"]')).toHaveCount(2);
  // "e2e" matches all three Jamendo tracks: Jamendo sent Lullaby (800) before Frère Jacques (12,345); the list shows by number
  await openSearch(page);
  await page.fill("#q", "(e2e)");
  await expect(page.locator('.song[data-kind="jamendo"]')).toHaveCount(3);
  const byNum = (await page.evaluate(() => window.__jamList)).filter(r => r.kind === "jamendo").map(r => r.listens);
  note("jamendo-order", { proj: info.project.name, byNum });
  expect(byNum).toEqual([1234567, 12345, 800]);
  await openSearch(page);
  await page.fill("#q", "twinkle");
  await expect(page.locator('.song[data-kind="jamendo"]')).toHaveCount(2);
  await page.locator(".song").nth(0).locator(".info").click();
  const imported = page.locator('.song[data-kind="local"]', { hasText: "Twinkle Twinkle (e2e)" });
  await expect(imported).toBeVisible();
  await expect(imported.locator(".badge.lic")).toHaveText("CC BY-SA 3.0");
  await expect(imported.locator(".badge.srcb")).toHaveText(lang === "zh" ? "曲库 · Jamendo" : "Library · Jamendo");
  await expect(page.locator('.song[data-kind="jamendo"]', { hasText: "Twinkle Twinkle (e2e)" })).toHaveCount(0);   // shown once
  const s = (await (await request.get("/api/songs?q=" + encodeURIComponent("Twinkle Twinkle (e2e)"))).json()).songs[0];
  const m = await waitProcessed(request, s.id);
  expect(m.status, m.error || "").toBe("ready");
  expect(m.license).toBe("CC BY-SA 3.0"); expect(m.source.kind).toBe("jamendo");
  const again = await request.post("/api/jamendo/import", { data: { id: "900001" } });
  expect(again.status()).toBe(200); expect((await again.json()).id).toBe(s.id);    // no second copy

  // open it, press play: one play is counted; play/pause again in the same tab is not counted again
  await page.goto(`/?lang=${lang}#/s/${s.id}`);
  await expect(page.locator("#play")).toBeEnabled({ timeout: 120_000 });
  await page.click("#play");
  await page.waitForFunction(() => window.__jam && window.__jam.player.playing);
  await expect.poll(async () => (await (await request.get(`/api/songs/${s.id}`)).json()).plays).toBe(1);
  await page.click("#play"); await page.click("#play");
  await page.waitForTimeout(800);
  expect((await (await request.get(`/api/songs/${s.id}`)).json()).plays).toBe(1);
  // starting a jam (share) in a fresh page of the same session within 30 s: still 1
  await page.reload();
  await expect(page.locator("#play")).toBeEnabled({ timeout: 120_000 });
  await page.click("#shareBtn");
  await page.waitForTimeout(800);
  const after = (await (await request.get(`/api/songs/${s.id}`)).json()).plays;
  note("plays", { proj: info.project.name, id: s.id, plays: after, why: await page.evaluate(() => window.__jam.S.playCount) });
  expect(after).toBe(1);

  // 我的曲库 (no query): sorted by plays, with the counts shown
  await page.goto(`/?lang=${lang}#/?tab=mine`);
  await expect(page.locator(".song").first()).toBeVisible();
  const lib = await page.evaluate(() => window.__jamList.map(r => [r.title, r.plays]));
  note("library-order", { proj: info.project.name, lib });
  const counts = lib.map(r => r[1]);
  expect(counts).toEqual([...counts].sort((a, b) => b - a));
  expect(lib[0]).toEqual([title, 2]);
  await shot(page, `39-library-plays-${lang}`, true);
  await remove(page, request, s.id); await deleteWithToken(request, local.id, local.owner_token);
});
