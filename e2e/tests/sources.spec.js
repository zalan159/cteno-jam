// Phone audio sources: record in the browser, pick from Files / WeChat (no extension, odd types),
// and the Jamendo free catalogue (search → preview → use, license shown). 390 px screenshots of all three.
// The server must run with the fake Jamendo API (scripts/fake_jamendo.py) for the Jamendo part:
//   JAM_JAMENDO_CLIENT_ID=e2e JAM_JAMENDO_API_URL=http://127.0.0.1:8782/v3.0
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const EVID = process.env.JAM_EVIDENCE || "../docs/evidence/e2e";
const DEMO = process.env.JAM_DEMO_DIR || "../demo/source";
const AUDIO = path.join(DEMO, "twinkle.mp3");
const log = [];
const note = (step, data) => { const row = { t: new Date().toISOString(), step, ...data }; log.push(row); console.log(JSON.stringify(row)); };
const shot = (page, name) => page.screenshot({ path: path.join(EVID, `${test.info().project.name}-${name}.png`) });
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
async function remove(request, id) { await request.delete(`/api/songs/${id}`).catch(() => {}); }
async function fitsPhone(page) {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const over = [...document.querySelectorAll("#drop, .src, .sheetpanel button, .jm, .rec button")]
      .filter(e => e.offsetParent && e.getBoundingClientRect().right > vw + 1).map(e => e.id || e.className);
    return { vw, scrollW: document.documentElement.scrollWidth, over };
  });
}

test("entry points: record, files/WeChat tip and free music on the library page", async ({ page }, info) => {
  await page.goto("/?lang=zh");
  await expect(page.locator("#recBtn")).toBeVisible();
  await expect(page.locator("#jmBtn")).toBeVisible();
  const accept = await page.getAttribute("#file", "accept");
  note("entries", { proj: info.project.name, accept, vw: page.viewportSize().width });
  expect(accept).toContain("audio/*"); expect(accept).toContain(".amr"); expect(accept).toContain(".m4a");
  const fit = await fitsPhone(page);
  expect(fit.over).toEqual([]); expect(fit.scrollW).toBeLessThanOrEqual(fit.vw + 1);
  await page.locator("#wxTip summary").click();
  await expect(page.locator("#wxTip p").first()).toContainText("微信");
  await shot(page, "30-sources-zh");
  await page.goto("/?lang=en");
  await expect(page.locator("#recBtn")).toContainText("Record");
  await expect(page.locator("#jmBtn")).toContainText("Free music");
  expect((await fitsPhone(page)).over).toEqual([]);
  await shot(page, "31-sources-en");
});

test("Jamendo entry is hidden when the server has no client id", async ({ page }) => {
  await page.route("**/api/info", async route => {
    const r = await route.fetch(); const j = await r.json();
    await route.fulfill({ response: r, json: { ...j, jamendo: false } });
  });
  await page.goto("/");
  await expect(page.locator("#recBtn")).toBeVisible();
  await expect(page.locator("#jmBtn")).toHaveCount(0);
});

test("record in the browser → use it → it is processed like an upload", async ({ page, request, browserName }, info) => {
  test.skip(browserName === "webkit", "Playwright's WebKit has no capture devices; Safari's AAC/MP4 path is covered by the format unit tests and the server-side MIME/duration tests");
  await page.context().grantPermissions(["microphone"]);
  await page.goto("/?lang=zh");
  await page.click("#recBtn");
  await expect(page.locator(".sheetpanel h3")).toHaveText("录一段");
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
  await remove(request, id);
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
      await remove(request, s.id);
      // the encrypted-download refusal still applies here
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

test("Jamendo: search → preview → use; only downloadable tracks; license kept", async ({ page, request }, info) => {
  await page.goto("/?lang=zh");
  await page.click("#jmBtn");
  await expect(page.locator(".sheetpanel h3")).toHaveText("Jamendo 免费曲库");
  await expect(page.locator(".jm").first()).toBeVisible();
  const popular = await page.locator(".jm .t").allTextContents();
  expect(popular.join("|")).not.toContain("Locked");
  await page.fill("#jmQ", "twinkle");
  await page.click("#jmGo");
  await expect(page.locator(".jm")).toHaveCount(1);
  await expect(page.locator(".jm .jmLic")).toHaveText("CC BY-SA 3.0");
  await expect(page.locator(".jm .jmLic")).toHaveAttribute("href", /creativecommons\.org\/licenses\/by-sa/);
  // preview plays through the server's proxy (the client id never reaches the page)
  await page.locator(".jmPlay").first().click();
  await page.waitForFunction(() => { const a = document.querySelector("#jmAudio"); return a && a.currentTime > 0.3; }, null, { timeout: 20_000 });
  const src = await page.$eval("#jmAudio", a => a.currentSrc || a.src);
  note("jamendo-preview", { proj: info.project.name, src, popular });
  expect(src).toMatch(/\/api\/jamendo\/preview\/900001\.mp3$/);
  await expect(page.locator(".jmPlay").first()).toHaveText("❚❚");
  expect((await fitsPhone(page)).over).toEqual([]);
  await shot(page, "36-jamendo");
  await page.fill("#jmQ", "locked");
  await page.click("#jmGo");
  await expect(page.locator("#jmList")).toContainText("没找到");
  await page.fill("#jmQ", "twinkle");
  await page.click("#jmGo");
  await page.locator(".jmUse").first().click();
  await expect(page.locator(".sheetpanel")).toHaveCount(0);
  const row = page.locator(".song", { hasText: "Twinkle Twinkle (e2e)" }).first();
  await expect(row).toBeVisible();
  await expect(row.locator(".badge.lic")).toHaveText("CC BY-SA 3.0");
  await shot(page, "37-jamendo-added");
  const s = (await (await request.get("/api/songs?q=" + encodeURIComponent("Twinkle Twinkle (e2e)"))).json()).songs[0];
  const m = await waitProcessed(request, s.id);
  const song = await (await request.get(`/api/songs/${s.id}/song.json`)).json();
  note("jamendo-import", { proj: info.project.name, id: s.id, status: m.status, license: m.license, source: m.source, key: song.analysis && song.analysis.key, seconds: m.seconds });
  expect(m.status, m.error || "").toBe("ready");
  expect(m.license).toBe("CC BY-SA 3.0");
  expect(m.source.kind).toBe("jamendo");
  expect(song.analysis.key).toBe("D major");
  await remove(request, s.id);
});
