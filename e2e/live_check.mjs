// Check a deployed static demo + sync server from the outside:
// the demo song plays, and a second phone that opens the share link follows the first one.
//   node live_check.mjs https://jam.example.com [out-dir]
import { webkit, chromium, devices } from "@playwright/test";
import fs from "node:fs";

const [BASE, out = "../docs/evidence/deploy"] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const res = { base: BASE, t: new Date().toISOString() };
const b = await webkit.launch();
const host = await (await b.newContext(devices["iPhone 13"])).newPage();
const errs = [];
host.on("pageerror", e => errs.push(String(e)));
await host.goto(BASE + "/#/");
await host.waitForSelector(".song", { timeout: 30000 });
res.library = await host.$$eval(".song .t", els => els.map(e => e.textContent));
await host.goto(BASE + "/#/s/demo-twinkle");
await host.waitForFunction(() => window.__loadStats, null, { timeout: 60000 });
res.load = await host.evaluate(() => window.__loadStats);
await host.tap("#shareBtn");
await host.waitForSelector("#followLink");
const follow = (await host.textContent("#followLink")).trim();
res.followLink = follow;
await host.goto("about:blank"); await host.goBack();
await host.waitForFunction(() => window.__loadStats, null, { timeout: 60000 });
await host.tap("#play");
await host.waitForTimeout(3000);
res.host = await host.evaluate(() => ({ playing: __jam.player.playing, now: __jam.player.now(), db: __jam.player.levelDb(), url: location.href }));

const cb = await chromium.launch();
const guest = await (await cb.newContext(devices["Pixel 7"])).newPage();
guest.on("pageerror", e => errs.push("guest: " + String(e)));
await guest.goto(follow);
await guest.waitForFunction(() => window.__jam && __jam.sync && __jam.sync.state && __jam.sync.state.playing, null, { timeout: 30000 });
await guest.waitForTimeout(1500);
const g = await guest.evaluate(() => ({ chord: document.querySelector("#cur") && document.querySelector("#cur").textContent, livePos: __jam.sync.livePos(__jam.sync.state) }));
const hNow = await host.evaluate(() => __jam.player.now());
res.guest = { ...g, hostNow: hNow, diff: +(g.livePos - hNow).toFixed(3) };
await guest.screenshot({ path: `${out}/guest-following.png` });
res.errors = errs;
res.ok = res.host.playing && res.host.db > -45 && Math.abs(res.guest.diff) < 0.5 && !errs.length;
fs.writeFileSync(`${out}/live-check.json`, JSON.stringify(res, null, 1));
console.log(JSON.stringify(res));
await b.close(); await cb.close();
process.exit(res.ok ? 0 : 1);
