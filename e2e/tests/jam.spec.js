// Full chain: upload a CC0 demo song -> processing -> chart -> play (sound) -> stems -> key/speed
// -> loop -> edit + undo -> print/PDF -> share to a second device (follows) -> big screen -> remote.
// Optional: if the server has an AI key configured, also checks the AI review panel and undo-all.
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const EVID = process.env.JAM_EVIDENCE || "../docs/evidence/e2e";
const DEMO = process.env.JAM_DEMO_DIR || "../demo/source";
const AUDIO = path.join(DEMO, "twinkle.mp3");
const LRC = fs.readFileSync(path.join(DEMO, "twinkle.lrc"), "utf8");
const log = [];
const note = (step, data) => { const row = { t: new Date().toISOString(), step, ...data }; log.push(row); console.log(JSON.stringify(row)); };
// the home page shows tabs + songs only: upload is a sheet behind #upOpen, search a box behind #searchBtn
async function openUpload(page) { if (!(await page.locator(".upsheet").count())) await page.click("#upOpen"); await expect(page.locator(".upsheet #file")).toBeAttached(); }
async function openSearch(page) { if (await page.locator("#q").isHidden()) await page.click("#searchBtn"); await expect(page.locator("#q")).toBeVisible(); }

async function shot(page, name) {
  const p = path.join(EVID, `${test.info().project.name}-${name}.png`);
  await page.screenshot({ path: p });
  return p;
}
// tap on touch devices, click on desktop
async function tap(p, sel) {
  try { await p.tap(sel); }
  catch (e) { if (/does not support tap/.test(e.message)) await p.click(sel); else throw e; }
}
const stemSpread = o => { const v = Object.values(o); return +((Math.max(...v) - Math.min(...v)) * 1000).toFixed(3); };

test.afterAll(async () => {
  fs.mkdirSync(EVID, { recursive: true });
  fs.appendFileSync(path.join(EVID, "steps.jsonl"), log.map(r => JSON.stringify(r)).join("\n") + "\n");
});

test("upload → process → play → share → big screen → remote", async ({ browser, page, request, baseURL }, info) => {
  const proj = info.project.name;
  const pageErrors = [], consoleErrors = [];
  page.on("pageerror", e => pageErrors.push(String(e)));
  page.on("console", m => { if (m.type() === "error") consoleErrors.push(m.text()); });
  const title = `Twinkle e2e ${proj} ${Date.now() % 100000}`;

  // ---------------------------------------------------------- 1. upload from the library
  await page.goto("/");
  await openUpload(page);
  await expect(page.locator(".brand")).toBeVisible();
  await shot(page, "01-library");
  await page.setInputFiles("#file", AUDIO);
  await page.fill("#upTitle", title);
  await page.fill("#upArtist", "Traditional");
  await page.locator("#upLyricsBox summary").click();
  await page.fill("#upLyrics", LRC);
  await page.click("#upGo");
  const row = page.locator(".song", { hasText: title });
  await expect(row).toBeVisible();
  const songs = (await (await request.get("/api/songs?q=" + encodeURIComponent(title))).json()).songs;
  const id = songs[0].id;
  note("uploaded", { proj, id, status: songs[0].status });

  // ---------------------------------------------------------- 2. progress shows, then ready
  let seen = new Set(), meta;
  const t0 = Date.now();
  for (;;) {
    meta = await (await request.get(`/api/songs/${id}`)).json();
    seen.add(`${meta.status}:${meta.stage}`);
    if (meta.status === "ready" || meta.status === "failed") break;
    if (Date.now() - t0 > 12 * 60_000) throw new Error("processing timed out");
    if (seen.size === 3) await shot(page, "02-processing");
    await page.waitForTimeout(700);
  }
  note("processed", { proj, status: meta.status, error: meta.error, seconds: (Date.now() - t0) / 1000, stages: [...seen], timings: meta.timings, device: meta.device, ai: meta.ai && meta.ai.status });
  expect(meta.status, meta.error || "").toBe("ready");
  await expect(row.locator("button[data-act=open]")).toBeVisible({ timeout: 10_000 });
  // layout: on a phone the whole row (incl. its buttons) fits inside the viewport
  const fit = await page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const over = [...document.querySelectorAll(".song, .song button, #drop")].filter(e => e.getBoundingClientRect().right > vw + 1);
    return { vw, scrollW: document.documentElement.scrollWidth, over: over.map(e => e.className || e.id) };
  });
  note("layout", { proj, ...fit });
  expect(fit.over).toEqual([]);
  expect(fit.scrollW).toBeLessThanOrEqual(fit.vw + 1);
  await shot(page, "03-library-ready");

  // ---------------------------------------------------------- 3. chart
  await row.locator("button[data-act=open]").click();
  await expect(page).toHaveURL(new RegExp(`#/s/${id}`));
  await page.waitForFunction(() => window.__loadStats || document.querySelector("#status.err"), null, { timeout: 120_000 });
  const loadErr = await page.$eval("#status", s => (s.classList.contains("err") ? s.textContent : null));
  expect(loadErr).toBeNull();
  const song = await (await request.get(`/api/songs/${id}/song.json`)).json();
  const an = song.analysis;
  note("analysis", { proj, key: an.key, tempo: an.tempo, chords: an.chords.length, lines: an.lyrics.lines.length, lyrics: an.lyrics.source, stats: await page.evaluate(() => window.__loadStats) });
  expect(an.key).toBe("D major");
  expect(Math.abs(an.tempo - 100)).toBeLessThan(3);
  expect(an.lyrics.lines.length).toBe(12);
  await expect(page.locator(".line")).toHaveCount(12);
  expect(await page.locator(".chord-svg").count()).toBeGreaterThanOrEqual(3);
  await expect(page.locator("#capo")).toContainText(/D/);
  await expect(page.locator(".trk")).toHaveCount(6);
  await shot(page, "04-chart");

  // ---------------------------------------------------------- 4. play: in sync, audible
  await tap(page, "#play");
  await page.waitForTimeout(3500);
  const p1 = await page.evaluate(() => ({ playing: __jam.player.playing, ctx: __jam.player.ctx.state, now: __jam.player.now(), times: __jam.player.stemTimes(), db: __jam.player.levelDb() }));
  note("playing", { proj, ...p1, spreadMs: stemSpread(p1.times) });
  expect(p1.playing).toBe(true);
  expect(p1.ctx).toBe("running");
  expect(p1.now).toBeGreaterThan(2.5);
  expect(stemSpread(p1.times)).toBeLessThan(1);
  expect(p1.db).toBeGreaterThan(-45);
  // a word got highlighted and the current chord is shown
  await expect(page.locator(".ch.sung").first()).toBeVisible();
  await expect(page.locator("#cur")).not.toHaveText("–");
  await shot(page, "05-playing");
  // E1: each chord sits right above the word it belongs to, and the sung line is kept in view while playing
  const geo = await page.evaluate(() => {
    const units = [...document.querySelectorAll(".ch")].filter(u => u.querySelector("b[data-seg]") && u.querySelector("i").textContent.trim());
    const bad = units.filter(u => { const b = u.querySelector("b").getBoundingClientRect(), i = u.querySelector("i").getBoundingClientRect();
      return !(b.bottom <= i.top + 2 && b.left >= i.left - 2 && b.left <= i.right); }).length;
    return { units: units.length, bad };
  });
  const scrollAt = async () => page.evaluate(() => { const sh = document.querySelector("#sheet"), on = document.querySelector(".line.on");
    if (!on) return { on: null, top: sh.scrollTop };
    const r = on.getBoundingClientRect(), v = sh.getBoundingClientRect();
    return { on: [...document.querySelectorAll(".line")].indexOf(on), top: Math.round(sh.scrollTop), lineTop: Math.round(r.top), lineBottom: Math.round(r.bottom),
      viewTop: Math.round(v.top), viewBottom: Math.round(v.bottom),
      // the sheet can be only ~70 px tall on a 390x664 phone with the controls open: "in view" = the line's top is inside it
      inView: r.top >= v.top - 1 && r.top < v.bottom }; });
  const sc1 = await scrollAt();
  await page.evaluate(() => __jam.player.seek(Math.max(0, __jam.S.an.lyrics.lines[9].start)));
  // the sheet scrolls smoothly; give it time to settle
  await expect.poll(async () => { const x = await scrollAt(); return x.on >= 8 && x.inView; }, { timeout: 6000 }).toBe(true).catch(() => {});
  const sc2 = await scrollAt();
  note("chords-over-words", { proj, ...geo, sc1, sc2 });
  expect(geo.units).toBeGreaterThan(10);
  expect(geo.bad).toBe(0);
  expect(sc2.on).toBeGreaterThanOrEqual(8);
  expect(sc2.inView).toBe(true);
  expect(sc2.top).toBeGreaterThan(sc1.top);
  await page.evaluate(() => __jam.player.seek(3));

  // ---------------------------------------------------------- 5. stems: karaoke, solo, volume
  await tap(page, "#karaoke");
  const kar = await page.evaluate(() => __jam.player.gainsNow());
  await page.waitForTimeout(400);
  await tap(page, ".trk[data-stem=drums] .s");
  await page.waitForTimeout(1200);
  const solo = await page.evaluate(() => ({ g: __jam.player.gainsNow(), live: __jam.player.gainsLive(), db: __jam.player.levelDb() }));
  await tap(page, ".trk[data-stem=drums] .s");
  await tap(page, "#karaoke");
  await page.waitForTimeout(400);
  const back = await page.evaluate(() => __jam.player.gainsNow());
  note("stems", { proj, karaoke: kar, drumsSolo: solo, restored: back });
  expect(kar.vocals).toBe(0); expect(kar.guitar).toBe(1);
  expect(solo.g.drums).toBe(1); expect(solo.g.vocals + solo.g.guitar + solo.g.piano + solo.g.bass + solo.g.other).toBe(0);
  expect(solo.live.vocals).toBeLessThan(0.01);
  expect(solo.db).toBeGreaterThan(-70); // drums alone: quieter than the mix, but not silent (silence is -120)
  expect(back.vocals).toBe(1);

  // ---------------------------------------------------------- 6. transpose (+2): chart and audio
  const before = await page.textContent("#cur");
  await tap(page, "#trUp"); await tap(page, "#trUp");
  await page.waitForFunction(() => (__jam.player.engine === "stretch" && __jam.player.semis === 2) || __jam.player.stretchError, null, { timeout: 30_000 });
  expect(await page.evaluate(() => __jam.player.stretchError)).toBeNull();
  await page.waitForTimeout(1500);
  const tr = await page.evaluate(() => ({ semis: __jam.player.semis, engine: __jam.player.engine, playing: __jam.player.playing, db: __jam.player.levelDb(), capo: document.querySelector("#capo").innerText, err: __jam.player.stretchError }));
  note("transpose", { proj, before, ...tr, chordNow: await page.textContent("#cur") });
  expect(tr.playing).toBe(true);
  expect(tr.db).toBeGreaterThan(-45);
  expect(tr.capo).toMatch(/E/);

  // ---------------------------------------------------------- 7. speed 0.8x keeps key, time runs at 0.8
  await tap(page, "#spd");
  await page.waitForFunction(() => __jam.player.rate === 0.8);
  const a = await page.evaluate(() => [__jam.player.now(), performance.now()]);
  await page.waitForTimeout(2500);
  const b = await page.evaluate(() => [__jam.player.now(), performance.now(), __jam.player.levelDb()]);
  const ratio = (b[0] - a[0]) / ((b[1] - a[1]) / 1000);
  note("speed", { proj, ratio: +ratio.toFixed(3), db: b[2] });
  expect(ratio).toBeGreaterThan(0.7); expect(ratio).toBeLessThan(0.9);
  expect(b[2]).toBeGreaterThan(-45);
  await tap(page, "#spd"); await tap(page, "#spd"); // 0.6 -> 1.0
  await page.waitForFunction(() => __jam.player.rate === 1);
  await shot(page, "06-transposed");

  // ---------------------------------------------------------- 8. A-B loop, metronome, count-in
  if (!(await page.isVisible("#loopA"))) await tap(page, "#moreBtn");
  await page.evaluate(() => __jam.player.seek(20));
  await tap(page, "#loopA");
  await page.evaluate(() => __jam.player.seek(24.5));
  await page.waitForTimeout(500);
  await tap(page, "#loopB");
  await page.waitForTimeout(6000);
  const lp = await page.evaluate(() => ({ loop: __jam.player.loop, now: __jam.player.now() }));
  note("loop", { proj, ...lp });
  expect(lp.loop).not.toBeNull();
  expect(lp.now).toBeGreaterThanOrEqual(lp.loop[0] - 0.05);
  expect(lp.now).toBeLessThanOrEqual(lp.loop[1] + 0.05);
  await tap(page, "#loopX");
  await tap(page, "#metro");
  await page.waitForTimeout(1200);
  const metro = await page.evaluate(() => ({ on: __jam.player.metro, clicks: __jam.player._clicks.length }));
  await tap(page, "#metro");
  await tap(page, "#countin");
  await tap(page, "#play"); // pause
  await tap(page, "#play"); // count-in, then play
  const ci = await page.evaluate(() => ({ counting: __jam.player.counting, startsIn: +(__jam.player.t0 - __jam.player.ctx.currentTime).toFixed(2) }));
  await tap(page, "#countin");
  note("metronome", { proj, metro, countIn: ci });
  expect(metro.clicks).toBeGreaterThan(0);
  expect(ci.counting).toBe(true);
  expect(ci.startsIn).toBeGreaterThan(1.5);
  await page.waitForTimeout(3000);

  // ---------------------------------------------------------- 9. edit a chord, then undo it
  await tap(page, "#editBtn");
  const seg = page.locator(".ch b[data-seg]").first();
  await seg.scrollIntoViewIfNeeded();
  const segId = await seg.getAttribute("data-seg");
  await seg.click();
  await page.fill("#chIn", "Bm7");
  await page.click("#chSave");
  await expect(page.locator(`.ch b[data-seg="${segId}"]`).first()).toContainText(/m7/);
  await shot(page, "07-edited");
  await tap(page, "#editBtn");
  if (!(await page.isVisible("#changesBtn"))) await tap(page, "#moreBtn");
  await tap(page, "#changesBtn");
  await expect(page.locator(".rev")).toHaveCount(1);
  await shot(page, "08-changes");
  await page.locator(".rev button").click();
  await expect(page.locator(".rev.reverted")).toHaveCount(1);
  const afterUndo = (await (await request.get(`/api/songs/${id}/song.json`)).json()).analysis.chords.find(c => c.id === segId);
  note("edit", { proj, segId, afterUndo: afterUndo.chord });
  expect(afterUndo.chord).not.toBe("Bm7");
  await page.locator(".scrim").click({ position: { x: 5, y: 5 } });

  // ---------------------------------------------------------- 10. AI review panel (only when configured)
  const ai = await page.evaluate(() => window.__jamInfo.ai);
  if (ai.configured) {
    await expect.poll(async () => ((await (await request.get(`/api/songs/${id}`)).json()).ai || {}).status, { timeout: 240_000 }).toMatch(/done|failed/);
    await page.reload();
    await page.waitForFunction(() => window.__loadStats, null, { timeout: 60_000 });
    const m2 = await (await request.get(`/api/songs/${id}`)).json();
    note("ai", { proj, status: m2.ai.status, accepted: m2.ai.accepted, rejected: (m2.ai.rejected || []).length, error: m2.ai.error });
    if (m2.ai.status === "done" && m2.ai.accepted > 0) {
      await expect(page.locator(".aibar")).toBeVisible();
      await shot(page, "09-ai-chart");
      await page.click("#aiOpen");
      await expect(page.locator(".rev .who.ai").first()).toBeVisible();
      await shot(page, "10-ai-changes");
      await page.click("#undoAll");
      await expect(page.locator(".rev.reverted .who.ai").first()).toBeVisible();
      const s3 = await (await request.get(`/api/songs/${id}/song.json`)).json();
      expect(s3.revisions.filter(r => r.source === "ai").every(r => r.status === "reverted")).toBe(true);
      await page.click("#redoAll");
      await page.locator(".scrim").click({ position: { x: 5, y: 5 } });
    }
  } else {
    await expect(page.locator(".aibar")).toContainText(/AI/);
  }

  // ---------------------------------------------------------- 11. print / PDF
  const printPage = await page.context().newPage();
  await printPage.goto(`/#/s/${id}/print?tr=2&capo=auto`);
  await printPage.waitForFunction(() => window.__printReady);
  await expect(printPage.locator(".print h1")).toContainText("Twinkle");
  expect(await printPage.locator(".print .chord-svg").count()).toBeGreaterThanOrEqual(3);
  await printPage.screenshot({ path: path.join(EVID, `${proj}-11-print.png`), fullPage: true });
  if (info.project.use.browserName === "chromium" && !info.project.use.isMobile) {
    await printPage.emulateMedia({ media: "print" });
    await printPage.pdf({ path: path.join(EVID, `${proj}-chart.pdf`), format: "A4" });
  }
  await printPage.close();

  // ---------------------------------------------------------- 12. share -> a second phone follows
  await tap(page, "#shareBtn");
  const follow = (await page.textContent("#followLink")).trim();
  const stageLink = (await page.textContent("#stageLink")).trim();
  const remoteLink = (await page.textContent("#remoteLink")).trim();
  expect(await page.locator("#qrFollow svg").count()).toBe(1);
  await shot(page, "12-share");
  await page.locator(".scrim").click({ position: { x: 5, y: 5 } });
  const room = new URL(follow.replace("/#/", "/")).searchParams.get("room") || follow.match(/room=([a-z0-9]+)/)[1];

  const ctx2 = await browser.newContext({ ...info.project.use, baseURL });
  const phone2 = await ctx2.newPage();
  const p2err = []; phone2.on("pageerror", e => p2err.push(String(e)));
  await phone2.goto(follow.replace(/^https?:\/\/[^/]+/, ""));
  await expect(phone2.locator("#status")).toContainText(room);
  await page.waitForTimeout(1500);
  const sync1 = await Promise.all([page.evaluate(() => __jam.player.now()), phone2.evaluate(() => __jam.now())]);
  // host transposes back down to 0; the follower's chart follows
  await tap(page, "#trDn"); await tap(page, "#trDn");
  await page.waitForTimeout(1200);
  const hostChord = await page.textContent("#cur"), f2Chord = await phone2.textContent("#cur");
  const hostCapo = await page.innerText("#capo"), f2Capo = await phone2.innerText("#capo");
  const sync2 = await Promise.all([page.evaluate(() => __jam.player.now()), phone2.evaluate(() => __jam.now())]);
  note("second-device", { proj, room, drift1: +(sync1[0] - sync1[1]).toFixed(3), drift2: +(sync2[0] - sync2[1]).toFixed(3), hostChord, f2Chord, hostCapo, f2Capo });
  expect(Math.abs(sync2[0] - sync2[1])).toBeLessThan(0.35);
  expect(f2Capo).toBe(hostCapo);
  await phone2.screenshot({ path: path.join(EVID, `${proj}-13-second-phone.png`) });

  // ---------------------------------------------------------- 13. big screen (TV) follows
  const tv = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, baseURL });
  const tvp = await tv.newPage();
  await tvp.goto(stageLink.replace(/^https?:\/\/[^/]+/, ""));
  await expect(tvp.locator("#sCur")).not.toHaveText("–", { timeout: 15_000 });
  await tvp.waitForTimeout(800);
  const tvState = await tvp.evaluate(() => ({ cur: document.querySelector("#sCur").textContent, line: document.querySelector("#sLine").innerText, now: __jam.now() }));
  const hostNow = await page.evaluate(() => __jam.player.now());
  note("big-screen", { proj, ...tvState, hostNow, hostChord: await page.textContent("#cur") });
  expect(Math.abs(tvState.now - hostNow)).toBeLessThan(0.35);
  // the big-screen line keeps the spaces between words: a unit like "Twinkle " must render its
  // trailing space (it collapsed to 0 px once, gluing the words together)
  const spaceW = await tvp.evaluate(() => {
    for (const u of document.querySelectorAll("#sLine .u")) {
      const tn = u.lastChild;
      if (!tn || tn.nodeType !== 3 || !/\S\s$/.test(tn.textContent)) continue;
      const r = document.createRange(), n = tn.textContent.length;
      r.setStart(tn, n - 1); r.setEnd(tn, n);
      return r.getBoundingClientRect().width;
    }
    return null;
  });
  note("big-screen-space", { proj, spaceW });
  expect(spaceW).not.toBeNull();
  expect(spaceW).toBeGreaterThan(8);
  await tvp.screenshot({ path: path.join(EVID, `${proj}-14-big-screen.png`) });

  // ---------------------------------------------------------- 14. remote control pauses the host
  const rc = await browser.newContext({ ...info.project.use, baseURL });
  const rcp = await rc.newPage();
  await rcp.goto(remoteLink.replace(/^https?:\/\/[^/]+/, ""));
  await expect(rcp.locator("#rPP")).toHaveText("❚❚", { timeout: 15_000 });
  await rcp.screenshot({ path: path.join(EVID, `${proj}-15-remote.png`) });
  await tap(rcp, "#rPP");
  await page.waitForFunction(() => !__jam.player.playing, null, { timeout: 5000 });
  await expect(tvp.locator("#sCur")).toBeVisible();
  await tap(rcp, "[data-c=transpose][data-a='1']");
  await page.waitForFunction(() => __jam.S.tr === 1, null, { timeout: 5000 });
  await tap(rcp, "#rPP");
  await page.waitForFunction(() => __jam.player.playing, null, { timeout: 5000 });
  note("remote", { proj, hostPlaying: await page.evaluate(() => __jam.player.playing), hostTr: await page.evaluate(() => __jam.S.tr) });
  await page.waitForTimeout(1000);
  await tvp.screenshot({ path: path.join(EVID, `${proj}-16-big-screen-after-remote.png`) });
  await Promise.all([ctx2.close(), tv.close(), rc.close()]);
  await tap(page, "#play").catch(() => {});

  // ---------------------------------------------------------- 15. rename, search, delete
  await page.goto("/");
  await openSearch(page);
  await page.fill("#q", title.slice(0, 12));
  await expect(page.locator(".song", { hasText: title })).toBeVisible();
  await page.locator(".song", { hasText: title }).locator("[data-act=menu]").click();
  await page.fill("#rnT", title + " renamed");
  await page.click("#rnSave");
  await expect(page.locator(".song", { hasText: title + " renamed" })).toBeVisible();
  page.once("dialog", d => d.accept());
  await page.locator(".song", { hasText: title + " renamed" }).locator("[data-act=menu]").click();
  await page.click("#rnDel");
  await expect(page.locator(".song", { hasText: title })).toHaveCount(0);
  const gone = await request.get(`/api/songs/${id}`);
  expect(gone.status()).toBe(404);

  const appErrors = await page.evaluate(() => (window.__jam && window.__jam.errors) || []);
  note("errors", { proj, pageErrors, consoleErrors, p2err, appErrors });
  expect(pageErrors).toEqual([]);
  expect(p2err).toEqual([]);
});

// C3: a file that is not audio is refused while uploading (plain Chinese reason, no row, nothing queued).
// D1 retry: a song that fails while processing (server started with JAM_TEST_FAIL_TITLE=__e2e_fail__) shows the
// reason, and its uploader's browser can retry it and delete it.
test("broken file refused at upload; a processing failure shows the reason and can be retried", async ({ page, request }) => {
  await page.goto("/?lang=zh");
  await openUpload(page);
  const bad = path.join(test.info().outputDir, "not-audio.mp3");
  fs.mkdirSync(path.dirname(bad), { recursive: true });
  fs.writeFileSync(bad, "this is not audio");
  await page.setInputFiles("#file", bad);
  const brokenTitle = "broken file " + Date.now() % 10000;
  await page.fill("#upTitle", brokenTitle);
  await page.click("#upGo");
  await expect(page.locator("#upMsg")).toContainText("读不出这个文件里的音频");
  await shot(page, "20-broken-refused");
  expect((await (await request.get("/api/songs?q=" + encodeURIComponent(brokenTitle))).json()).songs).toEqual([]);
  note("broken-refused", { proj: test.info().project.name, msg: await page.textContent("#upMsg") });

  // a real song that fails during processing (test marker in the title)
  await page.setInputFiles("#file", AUDIO);
  const title = "fails __e2e_fail__ " + Date.now() % 10000;
  await page.fill("#upTitle", title);
  await page.click("#upGo");
  await page.goto("/?lang=zh#/?tab=mine");
  const row = page.locator(".song", { hasText: title }).first();
  await expect(row.locator(".m.err").nth(1)).toBeVisible({ timeout: 60_000 });
  const msg = await row.locator(".m.err").nth(1).textContent();
  await expect(row.locator("[data-act=retry]")).toBeVisible();
  await shot(page, "20-failed");
  note("failed-upload", { proj: test.info().project.name, msg });
  expect(msg).toContain("JAM_TEST_FAIL_TITLE");
  expect(msg).not.toMatch(/\/home\/|\/Users\/|songs\//);
  const id = (await (await request.get("/api/songs?q=" + encodeURIComponent(title))).json()).songs[0].id;
  const before = (await (await request.get(`/api/songs/${id}`)).json()).attempts;
  await row.locator("[data-act=retry]").click();
  await expect.poll(async () => (await (await request.get(`/api/songs/${id}`)).json()).attempts, { timeout: 60_000 }).toBe(before + 1);
  await expect(row.locator(".m.err").nth(1)).toBeVisible({ timeout: 60_000 });
  page.once("dialog", d => d.accept());
  await row.locator("[data-act=menu]").click();
  await page.click("#rnDel");
  await expect(page.locator(".song", { hasText: title })).toHaveCount(0);
  expect((await request.get(`/api/songs/${id}`)).status()).toBe(404);
});

test("encrypted music-app files are refused with a plain message", async ({ page }) => {
  await page.goto("/?lang=zh");
  await openUpload(page);
  const dir = test.info().outputDir; fs.mkdirSync(dir, { recursive: true });
  // 1. picked by name: told at once, no upload form
  const mgg = path.join(dir, "Price Tag [mqms2].mgg2");
  fs.writeFileSync(mgg, Buffer.alloc(4096, 0x8a));
  await page.setInputFiles("#file", mgg);
  await expect(page.locator("#upFile")).toContainText("QQ 音乐的加密文件");
  await expect(page.locator("#upForm")).toBeHidden();
  await shot(page, "21-encrypted-picked");
  // 2. renamed to .flac: the server sniffs the QQ Music trailer and answers 415 with the same message
  const flac = path.join(dir, "renamed.flac");
  fs.writeFileSync(flac, Buffer.concat([Buffer.alloc(4096, 0x8a), Buffer.from("5010487,2,004KannO2MlVCc"), Buffer.from([0, 0, 0, 26]), Buffer.from("STag")]));
  await page.setInputFiles("#file", flac);
  await expect(page.locator("#upForm")).toBeVisible();
  await page.fill("#upTitle", "encrypted renamed " + Date.now() % 10000);
  await page.click("#upGo");
  await expect(page.locator("#upMsg")).toContainText("QQ 音乐的加密文件");
  await expect(page.locator(".song", { hasText: "encrypted renamed" })).toHaveCount(0);
  await shot(page, "22-encrypted-refused");
});
