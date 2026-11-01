// dev probe: switch to stretch engine and report
import { chromium, webkit, devices } from "@playwright/test";
const [url, eng = "chromium"] = process.argv.slice(2);
const b = await ({ chromium, webkit })[eng].launch({ args: eng === "chromium" ? ["--autoplay-policy=no-user-gesture-required"] : [] });
const ctx = await b.newContext({ ...devices["iPhone 13"] });
const p = await ctx.newPage();
p.on("console", m => console.log("console", m.type(), m.text()));
p.on("pageerror", e => console.log("pageerror", String(e)));
await p.goto(url);
await p.waitForFunction(() => window.__loadStats, null, { timeout: 60000 });
await p.tap("#play");
await p.waitForTimeout(1500);
const r = await p.evaluate(async () => {
  const t0 = performance.now();
  try { await __jam.player.setSemitones(2); } catch (e) { return { thrown: String(e) }; }
  return { ms: performance.now() - t0, engine: __jam.player.engine, semis: __jam.player.semis, err: __jam.player.stretchError, playing: __jam.player.playing };
});
console.log(JSON.stringify(r));
await p.waitForTimeout(2000);
console.log(JSON.stringify(await p.evaluate(() => ({ db: __jam.player.levelDb(), now: __jam.player.now(), inputTime: __jam.player.stretch && __jam.player.stretch.inputTime }))));
await p.tap("#spd"); await p.waitForTimeout(3000); await p.tap("#spd"); await p.tap("#spd");
console.log("after spd", JSON.stringify(await p.evaluate(() => ({ rate: __jam.player.rate, playing: __jam.player.playing, db: __jam.player.levelDb() }))));
await p.tap("#play"); // pause
for (const ms of [300, 1000, 3000]) { await p.waitForTimeout(ms); console.log("paused+" + ms, JSON.stringify(await p.evaluate(() => ({ db: __jam.player.levelDb(), playing: __jam.player.playing })))); }
await b.close();
