// First-screen screenshots of the home page at 390x844 (no scrolling) against any server, e.g. one using the
// real Jamendo API. Prints what is visible (song rows fully on screen, stars, upload card) as JSON.
//   node e2e/home_shots.mjs <url> <out-dir>      (WebKit, iPhone 13 UA, zh)
import { webkit, devices } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const [url, out] = [process.argv[2] || "http://127.0.0.1:8765", process.argv[3] || "home-shots"];
fs.mkdirSync(out, { recursive: true });
const browser = await webkit.launch();
const ctx = await browser.newContext({ ...devices["iPhone 13"], viewport: { width: 390, height: 844 }, locale: "zh-CN" });
const page = await ctx.newPage();
const errors = []; page.on("pageerror", e => errors.push(String(e)));
const look = () => page.evaluate(() => {
  const vh = innerHeight, vw = document.documentElement.clientWidth;
  const rows = [...document.querySelectorAll(".song")].filter(e => { const r = e.getBoundingClientRect(); return r.top >= 0 && r.bottom <= vh + 0.5 && r.right <= vw + 1; });
  return {
    scrollY, viewport: [vw, vh], visibleSongs: rows.length,
    withPlaysAndLicense: rows.filter(r => r.querySelector(".plays") && r.querySelector(".badge.lic")).length,
    stars: (document.body.innerText.match(/[★☆✦✧✨⭐🌟✩✪✫✬✭✮✯✰⋆]/gu) || []).length,
    uploadCardVisible: [...document.querySelectorAll("#drop, .upbtn")].some(e => e.offsetParent),
    tab: window.__jamTab,
    songs: rows.map(r => [r.querySelector(".t").textContent.trim(), r.querySelector(".plays").textContent, (r.querySelector(".badge.lic") || {}).textContent]),
  };
});
const res = {};
await page.goto(url + "/?lang=zh");
await page.locator('.song[data-kind="jamendo"]').first().waitFor({ timeout: 60_000 });
await page.waitForTimeout(800);
res.hot = await look();
await page.screenshot({ path: path.join(out, "home-hot-390x844.png") });
await page.click('.tab[data-tab="zh"]');
await page.waitForFunction(() => window.__jamTab === "zh" && document.querySelector('.song[data-kind="jamendo"]'), null, { timeout: 60_000 });
await page.waitForTimeout(800);
res.zh = await look();
await page.screenshot({ path: path.join(out, "home-zh-390x844.png") });
await page.click('.tab[data-tab="hot"]');
await page.click("#upOpen");
await page.locator(".upsheet #drop").waitFor();
await page.waitForTimeout(300);
await page.screenshot({ path: path.join(out, "upload-sheet-390x844.png") });
res.errors = errors;
fs.writeFileSync(path.join(out, "home-shots.json"), JSON.stringify(res, null, 1));
console.log(JSON.stringify(res, null, 1));
await browser.close();
