// README screenshots from a server with the bundled demo songs seeded (JAM_SEED_DEMO=1).
//   JAM_URL=http://127.0.0.1:8765 node shots.mjs ../docs/screenshots [en|zh]
// Produces chart-phone, big-screen, library-phone, ai-changes, share, remote (.png).
import { chromium, webkit, devices } from "@playwright/test";
import fs from "node:fs";

const [out = "../docs/screenshots", lang = "en"] = process.argv.slice(2);
const URL = process.env.JAM_URL || "http://127.0.0.1:8765";
const SONG = process.env.JAM_SONG || "demo-twinkle";
fs.mkdirSync(out, { recursive: true });
const phone = { ...devices["iPhone 13"], locale: lang === "zh" ? "zh-CN" : "en-US" };
const init = `try { localStorage.setItem("jam.lang", ${JSON.stringify(lang)}) } catch (e) {}`;

const b = await webkit.launch();
const ctx = await b.newContext(phone);
await ctx.addInitScript(init);
const p = await ctx.newPage();
const errors = [];
p.on("pageerror", e => errors.push(String(e)));

// library
await p.goto(URL + "/#/");
await p.waitForSelector(".song", { timeout: 20000 });
await p.waitForTimeout(600);
await p.screenshot({ path: `${out}/library-phone.png` });

// chart while playing (mid-song, so a lyric line is highlighted)
await p.goto(`${URL}/#/s/${SONG}`);
await p.waitForFunction(() => window.__loadStats, null, { timeout: 60000 });
await p.tap("#play");
await p.evaluate(() => __jam.player.seek(17.5));
await p.waitForTimeout(2500);
await p.screenshot({ path: `${out}/chart-phone.png` });

// what the AI changed and why
await p.tap("#play");
await p.waitForSelector("#aiOpen", { timeout: 10000 });
await p.tap("#aiOpen");
await p.waitForTimeout(700);
await p.screenshot({ path: `${out}/ai-changes.png` });
await p.goto(`${URL}/#/s/${SONG}`);
await p.waitForFunction(() => window.__loadStats, null, { timeout: 60000 });

// share sheet (QR for friends)
await p.tap("#shareBtn");
await p.waitForTimeout(700);
await p.screenshot({ path: `${out}/share.png` });
const remoteUrl = await p.textContent("#remoteLink");
const stageUrl = await p.textContent("#stageLink");
await p.keyboard.press("Escape").catch(() => {});
// close the sheet (reload keeps ?room=...&role=host) and play on the phone: it leads the room
const hostUrl = p.url();
await p.goto("about:blank"); await p.goto(hostUrl);
await p.waitForFunction(() => window.__loadStats, null, { timeout: 60000 });
await p.tap("#play");
await p.evaluate(() => __jam.player.seek(24));

// big screen on a TV, following the phone
const tvB = await chromium.launch();
const tv = await tvB.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, locale: phone.locale });
await tv.addInitScript(init);
const tvp = await tv.newPage();
await tvp.goto(stageUrl.trim().replace(/^https?:\/\/[^/]+/, URL));
await tvp.waitForFunction(() => { const e = document.querySelector("#sCur"); return e && e.textContent !== "–"; }, null, { timeout: 20000 });
await tvp.waitForTimeout(2500);
await tvp.screenshot({ path: `${out}/big-screen.png` });

// phone as remote
const rc = await b.newContext(phone);
await rc.addInitScript(init);
const rcp = await rc.newPage();
await rcp.goto(remoteUrl.trim().replace(/^https?:\/\/[^/]+/, URL));
await rcp.waitForTimeout(2500);
await rcp.screenshot({ path: `${out}/remote.png` });

await p.evaluate(() => __jam.player.stop());
console.log(JSON.stringify({ out, lang, errors, hostUrl, stageUrl, remoteUrl }));
await tvB.close(); await b.close();
