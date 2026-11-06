// Home page, first screen at 390x844 (iPhone 13), no scrolling, no search, no login:
// tabs 热门 / 中文 / 我的曲库 on top, then playable songs (each with plays + license); no slogan, no stars,
// no permanent upload card. Upload opens in a sheet from the small button and closes itself after uploading.
// Server: JAM_JAMENDO_CLIENT_ID=e2e JAM_JAMENDO_API_URL=http://127.0.0.1:8782/v3.0 (scripts/fake_jamendo.py).
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const EVID = process.env.JAM_EVIDENCE || "../docs/evidence/e2e";
const DEMO = process.env.JAM_DEMO_DIR || "../demo/source";
const AUDIO = path.join(DEMO, "twinkle.mp3");
const log = [];
const note = (step, data) => { const row = { t: new Date().toISOString(), step, ...data }; log.push(row); console.log(JSON.stringify(row)); };
const shot = (page, name) => page.screenshot({ path: path.join(EVID, `${test.info().project.name}-${name}.png`) });   // viewport only
// The acceptance size is the full 390x844 iPhone screen (the iPhone 13 preset subtracts Safari's bars: 390x664).
test.use({ viewport: { width: 390, height: 844 } });
test.afterAll(async () => {
  fs.mkdirSync(EVID, { recursive: true });
  fs.appendFileSync(path.join(EVID, "steps.jsonl"), log.map(r => JSON.stringify(r)).join("\n") + "\n");
});

// One ready library song (the suite runs on an empty library), so 热门 can show library + Jamendo together.
let libSong = null;
test.beforeAll(async ({ request }) => {
  const have = (await (await request.get("/api/songs")).json()).songs.find(s => s.status === "ready");
  if (have) return;
  const up = await request.post("/api/songs", { multipart: { file: { name: "twinkle.mp3", mimeType: "audio/mpeg", buffer: fs.readFileSync(AUDIO) }, title: "Home list library song" } });
  libSong = (await up.json()).id;
  for (const t0 = Date.now(); Date.now() - t0 < 10 * 60_000;) {
    const m = await (await request.get(`/api/songs/${libSong}`)).json();
    if (m.status === "ready" || m.status === "failed") break;
    await new Promise(r => setTimeout(r, 1000));
  }
});
test.afterAll(async ({ request }) => { if (libSong) await request.delete(`/api/songs/${libSong}`); });

// What a person sees on the first screen: song rows fully inside the viewport, decorations, upload card.
async function firstScreen(page) {
  return page.evaluate(() => {
    const vh = window.innerHeight, vw = document.documentElement.clientWidth;
    const inView = e => { const r = e.getBoundingClientRect(); return r.height > 0 && r.top >= 0 && r.bottom <= vh + 0.5 && r.right <= vw + 1; };
    const rows = [...document.querySelectorAll(".song")].filter(inView);
    const text = document.body.innerText;
    return {
      scrollY: window.scrollY, vh, vw, scrollW: document.documentElement.scrollWidth,
      visibleSongs: rows.length,
      withPlaysAndLicense: rows.filter(r => r.querySelector(".plays") && r.querySelector(".badge.lic")).length,
      clickable: rows.filter(r => r.querySelector("button.primary")).length,
      titles: rows.map(r => r.querySelector(".t").textContent.trim()),
      stars: (text.match(/[★☆✦✧✨⭐🌟✩✪✫✬✭✮✯✰⋆]/gu) || []).length,
      starNodes: document.querySelectorAll(".star, .stars, [class*=star], .hero, .sparkle").length,
      uploadCard: !!document.querySelector("#drop, .upbtn") && [...document.querySelectorAll("#drop, .upbtn")].some(e => e.offsetParent),
      tabs: [...document.querySelectorAll(".tab")].map(b => [b.textContent.trim(), b.classList.contains("on")]),
      tabsTop: document.querySelector(".tabsrow").getBoundingClientRect().top,
      firstSongTop: rows.length ? rows[0].getBoundingClientRect().top : null,
      tab: window.__jamTab,
    };
  });
}

test("home first screen: tabs + ≥5 playable songs, no stars, no upload card; 中文 tab; upload sheet", async ({ page, request }, info) => {
  test.skip(info.project.name === "chromium-desktop", "the acceptance is the 390x844 phone screen");
  const lang = info.project.name.startsWith("webkit") ? "zh" : "en";
  const errs = []; page.on("pageerror", e => errs.push(String(e)));
  await page.goto(`/?lang=${lang}`);
  expect(page.viewportSize()).toEqual({ width: 390, height: 844 });
  await expect(page.locator('.song[data-kind="jamendo"]').first()).toBeVisible();
  const hot = await firstScreen(page);
  note("home-hot", { proj: info.project.name, ...hot });
  expect(hot.scrollY).toBe(0);
  expect(hot.tab).toBe("hot");
  expect(hot.tabs.map(x => x[0])).toEqual(lang === "zh" ? ["热门", "中文", "我的曲库"] : ["Popular", "Chinese", "My library"]);
  expect(hot.tabs[0][1]).toBe(true);
  expect(hot.visibleSongs).toBeGreaterThanOrEqual(5);
  expect(hot.withPlaysAndLicense).toBe(hot.visibleSongs);
  expect(hot.clickable).toBe(hot.visibleSongs);
  expect(hot.stars).toBe(0); expect(hot.starNodes).toBe(0);
  expect(hot.uploadCard).toBe(false);
  expect(hot.tabsTop).toBeLessThan(80);                      // right under the top bar
  expect(hot.firstSongTop).toBeLessThan(140);                // songs start right below the tabs
  expect(hot.scrollW).toBeLessThanOrEqual(hot.vw + 1);
  await expect(page.locator("#q")).toBeHidden();             // the search box is behind the small button
  await shot(page, `50-home-hot-${lang}`);
  // the hot list mixes the library's ready demo songs with Jamendo's popular ones
  const list = await page.evaluate(() => window.__jamList);
  expect(list.some(r => r.kind === "jamendo")).toBe(true);
  expect(list.some(r => r.kind === "local")).toBe(true);
  expect(list.map(r => r.title).join("|")).not.toContain("Locked");

  // 中文
  await page.click('.tab[data-tab="zh"]');
  await expect(page.locator(".song", { hasText: "中文歌 1" })).toBeVisible();
  const zh = await firstScreen(page);
  note("home-zh", { proj: info.project.name, ...zh });
  expect(zh.tab).toBe("zh");
  expect(zh.visibleSongs).toBeGreaterThanOrEqual(5);
  expect(zh.withPlaysAndLicense).toBe(zh.visibleSongs);
  expect(zh.stars).toBe(0); expect(zh.uploadCard).toBe(false);
  expect(zh.firstSongTop).toBe(hot.firstSongTop);            // switching tabs does not push the songs down
  const zhList = await page.evaluate(() => window.__jamList);
  expect(zhList.filter(r => r.title.startsWith("中文歌")).length).toBe(8);   // 6 lang=zh + 2 topped up from tags=chinese
  await shot(page, `51-home-zh-${lang}`);

  // tap a song in a list: it is imported (same path as search) and appears in the library
  await page.locator(".song", { hasText: "中文歌 1" }).locator(".jmUse").click();
  await expect.poll(async () => (await (await request.get("/api/songs?q=" + encodeURIComponent("中文歌 1"))).json()).songs.length).toBe(1);

  // 我的曲库
  await page.click('.tab[data-tab="mine"]');
  await expect(page.locator('.song[data-kind="local"]', { hasText: "中文歌 1" })).toBeVisible();
  await expect(page.locator('.song[data-kind="jamendo"]')).toHaveCount(0);

  // upload sheet
  await page.click('.tab[data-tab="hot"]');
  await page.click("#upOpen");
  await expect(page.locator(".upsheet #drop")).toBeVisible();
  await shot(page, `52-upload-sheet-${lang}`);
  await page.setInputFiles("#file", AUDIO);
  const title = `sheet upload ${info.project.name} ${Date.now() % 100000}`;
  await page.fill("#upTitle", title);
  await page.click("#upGo");
  await expect(page.locator(".upsheet")).toHaveCount(0);                // closes by itself
  await expect(page.locator('.tab[data-tab="mine"]')).toHaveClass(/on/); // and shows the library with the new song
  await expect(page.locator(".song", { hasText: title })).toBeVisible();
  await shot(page, `53-after-upload-${lang}`);
  note("upload-sheet", { proj: info.project.name, title });

  for (const t of [title, "中文歌 1"]) {
    const s = (await (await request.get("/api/songs?q=" + encodeURIComponent(t))).json()).songs;
    for (const m of s) await request.delete(`/api/songs/${m.id}`);
  }
  expect(errs).toEqual([]);
});

test("Jamendo down: the home lists still show the library songs, never an empty box", async ({ page }, info) => {
  test.skip(info.project.name === "chromium-desktop", "phone screen");
  await page.route("**/api/jamendo/charts/**", r => r.fulfill({ status: 502, json: { detail: "Jamendo is not reachable right now" } }));
  await page.goto("/?lang=zh");
  await expect(page.locator(".jmNote")).toBeVisible();
  const hot = await firstScreen(page);
  note("jamendo-down", { proj: info.project.name, ...hot });
  expect(hot.visibleSongs).toBeGreaterThanOrEqual(1);
  await page.click('.tab[data-tab="zh"]');
  await expect(page.locator(".song").first()).toBeVisible();
  await expect(page.locator(".card.muted")).toHaveCount(0);
});

test("no Jamendo client id: no chart requests, the library shows", async ({ page }, info) => {
  test.skip(info.project.name === "chromium-desktop", "phone screen");
  await page.route("**/api/info", async route => { const r = await route.fetch(); await route.fulfill({ response: r, json: { ...(await r.json()), jamendo: false } }); });
  const calls = []; page.on("request", r => { if (r.url().includes("/api/jamendo/")) calls.push(r.url()); });
  await page.goto("/?lang=zh");
  await expect(page.locator(".song").first()).toBeVisible();
  await page.waitForTimeout(800);
  expect(calls).toEqual([]);
  await expect(page.locator(".jmNote")).toHaveCount(0);
});
