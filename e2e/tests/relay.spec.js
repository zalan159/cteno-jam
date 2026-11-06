// Relay suite: scenarios D1–D3 (+ the public smoke A1/B2) THROUGH a front proxy with the production rules
// (deploy/relay/jam.rules.caddy, started by scripts/e2e_relay.sh). Without JAM_RELAY=1 the whole file is skipped,
// because talking to the Jam server directly would not prove anything about the relay.
//   JAM_RELAY=1 JAM_URL=http://127.0.0.1:<relay port> npx playwright test relay.spec.js
import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { tokenInPage, uploadApi, deleteWithToken } from "./owner.js";

const EVID = process.env.JAM_EVIDENCE || "../docs/evidence/e2e";
const DEMO = process.env.JAM_DEMO_DIR || "../demo/source";
const AUDIO = path.join(DEMO, "twinkle.mp3");
const FILE = () => ({ name: "twinkle.mp3", mimeType: "audio/mpeg", buffer: fs.readFileSync(AUDIO) });
const log = [];
const note = (step, data) => { const row = { t: new Date().toISOString(), step, ...data }; log.push(row); console.log(JSON.stringify(row)); };
const shot = (page, name) => page.screenshot({ path: path.join(EVID, `${test.info().project.name}-${name}.png`) });
const RELAY_403 = /公网上只能管理自己上传的歌/;   // answered by the relay (no X-Jam-Owner header)
const SERVER_403 = /只有上传这首歌的浏览器/;      // answered by the Jam server (header present, token wrong)

test.skip(process.env.JAM_RELAY !== "1", "relay suite: run through scripts/e2e_relay.sh");
test.use({ viewport: { width: 390, height: 844 } });
test.beforeEach(({}, info) => test.skip(info.project.name === "chromium-desktop", "phone suite (390x844)"));
test.afterAll(async () => {
  fs.mkdirSync(EVID, { recursive: true });
  fs.appendFileSync(path.join(EVID, "steps.jsonl"), log.map(r => JSON.stringify(r)).join("\n") + "\n");
});

async function waitStatus(request, id, want = ["ready", "failed"], ms = 10 * 60_000) {
  for (const t0 = Date.now(); Date.now() - t0 < ms;) {
    const m = await (await request.get(`/api/songs/${id}`)).json();
    if (want.includes(m.status)) return m;
    await new Promise(r => setTimeout(r, 800));
  }
  throw new Error("timed out waiting for " + want);
}
const WRITES = id => [
  ["PATCH", `/api/songs/${id}`, { title: "hijacked" }],
  ["POST", `/api/songs/${id}/retry`, null],
  ["POST", `/api/songs/${id}/edits`, { patches: [{ op: "replace_chord", id: "c001", chord: "C" }] }],
  ["POST", `/api/songs/${id}/revisions`, { ids: "all", status: "reverted" }],
  ["POST", `/api/songs/${id}/review`, null],
  ["DELETE", `/api/songs/${id}`, null],
];
async function send(request, method, url, data, headers = {}) {
  const r = await request.fetch(url, { method, headers, ...(data ? { data } : {}) });
  let body = null; try { body = await r.json(); } catch (e) {}
  return { status: r.status(), detail: body && body.detail };
}

// One song "someone else" uploaded (its token stays in this test, never in the page's browser).
let other = null;
test.beforeAll(async ({ request }) => {
  other = await uploadApi(request, FILE(), { title: "Someone else's song (relay e2e)" });
  expect(other.status).toBe(201);
  expect((await waitStatus(request, other.id)).status).toBe("ready");
});
test.afterAll(async ({ request }) => { if (other) await deleteWithToken(request, other.id, other.token); });

test("relay: writes without a token are 403 at the relay, wrong token 403 at the server, own token works", async ({ request }, info) => {
  const rows = [];
  for (const [method, url, data] of WRITES(other.id)) {
    const none = await send(request, method, url, data);
    const wrong = await send(request, method, url, data, { "X-Jam-Owner": "not-the-token-" + "x".repeat(30) });
    rows.push({ method, url, none: none.status, wrong: wrong.status });
    expect(none.status, `${method} ${url} without token`).toBe(403);
    expect(none.detail).toMatch(RELAY_403);
    expect(wrong.status, `${method} ${url} wrong token`).toBe(403);
    expect(wrong.detail).toMatch(SERVER_403);
  }
  // an unknown write path or method stays closed even with a token header
  expect((await send(request, "PUT", `/api/songs/${other.id}`, { title: "x" }, { "X-Jam-Owner": other.token })).status).toBe(403);
  expect((await send(request, "POST", `/api/songs/${other.id}/whatever`, null, { "X-Jam-Owner": other.token })).status).toBe(403);
  // the song's own token gets through the relay and is accepted by the server
  const own = { "X-Jam-Owner": other.token };
  const ok = {
    rename: (await send(request, "PATCH", `/api/songs/${other.id}`, { title: "Someone else's song (relay e2e)" }, own)).status,
    edits: (await send(request, "POST", `/api/songs/${other.id}/edits`, { patches: [{ op: "replace_chord", id: "c001", chord: "C" }] }, own)).status,
    revisions: (await send(request, "POST", `/api/songs/${other.id}/revisions`, { ids: "all", status: "reverted" }, own)).status,
    review: await send(request, "POST", `/api/songs/${other.id}/review`, null, own),
  };
  note("relay-matrix", { proj: info.project.name, rows, ok });
  expect(ok.rename).toBe(200); expect(ok.edits).toBe(200); expect(ok.revisions).toBe(200);
  expect(ok.review.status).toBe(409);                              // passed relay + token; AI is just not configured
  expect(ok.review.detail).toMatch(/not configured/);
  expect((await (await request.get(`/api/songs/${other.id}`)).json()).title).toBe("Someone else's song (relay e2e)");
});

test("D1: my own upload — rename, edit, delete through the relay", async ({ page, request }, info) => {
  const lang = "zh";
  const errs = []; page.on("pageerror", e => errs.push(String(e)));
  await page.goto(`/?lang=${lang}`);
  await page.click("#upOpen");
  await page.setInputFiles("#file", AUDIO);
  const title = `我的歌 relay ${info.project.name} ${Date.now() % 100000}`;
  await page.fill("#upTitle", title);
  await page.click("#upGo");
  await expect(page.locator(".upsheet")).toHaveCount(0);
  const row = page.locator(".song", { hasText: title });
  await expect(row).toBeVisible();
  const id = (await (await request.get("/api/songs?q=" + encodeURIComponent(title))).json()).songs[0].id;
  const token = await tokenInPage(page, id);
  expect(token, "the upload response's token is kept by this browser").toBeTruthy();
  expect(JSON.stringify(await (await request.get(`/api/songs/${id}`)).json())).not.toContain(token);
  expect((await waitStatus(request, id)).status).toBe("ready");
  await expect(row.locator("[data-act=menu]")).toBeVisible();
  await shot(page, "60-relay-own-song-menu");

  // rename
  await row.locator("[data-act=menu]").click();
  await expect(page.locator("#rnDel")).toBeVisible();
  await shot(page, "61-relay-own-song-sheet");
  await page.fill("#rnT", title + " 改名");
  await page.click("#rnSave");
  await expect(page.locator(".song", { hasText: title + " 改名" })).toBeVisible();

  // edit a chord on the song page
  await page.goto(`/?lang=${lang}#/s/${id}`);
  await expect(page.locator("#play")).toBeEnabled({ timeout: 120_000 });
  await page.click("#moreBtn");
  await expect(page.locator("#editBtn")).toBeVisible();
  await page.click("#editBtn");
  const seg = page.locator("#sheet b[data-seg]").first();    // no lyrics here: chords sit in the instrumental line
  await seg.scrollIntoViewIfNeeded();
  const segId = await seg.getAttribute("data-seg");
  await seg.click();
  await page.fill("#chIn", "Bm7");
  await page.click("#chSave");
  await expect(page.locator(`#sheet b[data-seg="${segId}"]`).first()).toContainText(/m7/);
  const chord = (await (await request.get(`/api/songs/${id}/song.json`)).json()).analysis.chords.find(c => c.id === segId).chord;
  expect(chord).toBe("Bm7");
  await shot(page, "62-relay-own-song-edited");

  // delete
  await page.goto(`/?lang=${lang}#/?tab=mine`);
  page.once("dialog", d => d.accept());
  await page.locator(".song", { hasText: title }).locator("[data-act=menu]").click();
  await page.click("#rnDel");
  await expect(page.locator(".song", { hasText: title })).toHaveCount(0);
  expect((await request.get(`/api/songs/${id}`)).status()).toBe(404);
  expect(await tokenInPage(page, id)).toBeNull();                  // forgotten after deleting
  await shot(page, "63-relay-own-song-deleted");
  await expect(page.locator(".toast")).toHaveCount(0);
  note("relay-own", { proj: info.project.name, id, chord });
  expect(errs).toEqual([]);
});

test("D1: my own failed upload can be retried through the relay", async ({ page, request }, info) => {
  await page.goto("/?lang=zh");
  await page.click("#upOpen");
  await page.setInputFiles("#file", AUDIO);
  const title = `fails __e2e_fail__ relay ${info.project.name} ${Date.now() % 100000}`;
  await page.fill("#upTitle", title);
  await page.click("#upGo");
  const row = page.locator(".song", { hasText: title });
  await expect(row.locator("[data-act=retry]")).toBeVisible({ timeout: 60_000 });
  const id = (await (await request.get("/api/songs?q=" + encodeURIComponent(title))).json()).songs[0].id;
  const before = (await waitStatus(request, id, ["failed"])).attempts;
  await shot(page, "64-relay-own-failed");
  await row.locator("[data-act=retry]").click();
  await expect.poll(async () => (await (await request.get(`/api/songs/${id}`)).json()).attempts, { timeout: 60_000 }).toBe(before + 1);
  await expect(page.locator(".toast")).toHaveCount(0);
  note("relay-retry", { proj: info.project.name, id, before });
  page.once("dialog", d => d.accept());
  await row.locator("[data-act=menu]").click();
  await page.click("#rnDel");
  await expect(row).toHaveCount(0);
});

test("D2: someone else's song and the demo song show no management buttons; direct calls are 403 in Chinese", async ({ page, request }, info) => {
  const errs = []; page.on("pageerror", e => errs.push(String(e)));
  await page.goto("/?lang=zh#/?tab=mine");
  const row = page.locator(".song", { hasText: "Someone else's song (relay e2e)" });
  await expect(row).toBeVisible();
  await expect(row.locator("[data-act=menu]")).toHaveCount(0);
  await expect(row.locator("[data-act=retry]")).toHaveCount(0);
  const demo = page.locator('.song[data-id^="demo-"]').first();
  const hasDemo = await demo.count();
  expect(hasDemo, "the relay suite runs with the bundled demo songs seeded (JAM_SEED_DEMO=1)").toBeGreaterThan(0);
  const demoId = hasDemo ? await demo.getAttribute("data-id") : null;
  if (hasDemo) await expect(demo.locator("[data-act=menu], [data-act=retry]")).toHaveCount(0);
  await shot(page, "65-relay-others-no-buttons");
  // the song page: no edit button, the changes list has no undo buttons
  await page.goto(`/?lang=zh#/s/${other.id}`);
  await expect(page.locator("#play")).toBeEnabled({ timeout: 120_000 });
  await page.click("#moreBtn");
  await expect(page.locator("#editBtn")).toHaveCount(0);
  await expect(page.locator("#changesBtn")).toBeVisible();
  await shot(page, "66-relay-others-song-page");
  // what the page itself would get if someone called the API by hand (same origin, through the relay)
  const direct = await page.evaluate(async id => {
    const out = {};
    for (const [k, method, url, body] of [["delete", "DELETE", `/api/songs/${id}`], ["rename", "PATCH", `/api/songs/${id}`, { title: "x" }],
      ["retry", "POST", `/api/songs/${id}/retry`], ["edits", "POST", `/api/songs/${id}/edits`, { patches: [] }]]) {
      const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
      out[k] = [r.status, (await r.json()).detail];
    }
    return out;
  }, other.id);
  for (const [k, [status, detail]] of Object.entries(direct)) { expect(status, k).toBe(403); expect(detail, k).toMatch(/[\u4e00-\u9fff]/); }
  // demo song: even with some token header the server refuses, in Chinese
  const demoDel = demoId ? await send(request, "DELETE", `/api/songs/${demoId}`, null, { "X-Jam-Owner": "guess" }) : null;
  note("relay-others", { proj: info.project.name, direct, demoId, demoDel });
  if (demoDel) { expect(demoDel.status).toBe(403); expect(demoDel.detail).toMatch(/演示歌/); }
  expect((await request.get(`/api/songs/${other.id}`)).status()).toBe(200);
  expect(errs).toEqual([]);
});

test("D3: another browser (or cleared site data) treats my song as someone else's, without errors", async ({ browser, page, request, baseURL }, info) => {
  // browser A uploads; `page` plays browser B
  const ctxA = await browser.newContext({ ...info.project.use, viewport: { width: 390, height: 844 }, baseURL });
  const a = await ctxA.newPage();
  await a.goto("/?lang=zh");
  await a.click("#upOpen");
  await a.setInputFiles("#file", AUDIO);
  const title = `换浏览器 relay ${info.project.name} ${Date.now() % 100000}`;
  await a.fill("#upTitle", title);
  await a.click("#upGo");
  await expect(a.locator(".song", { hasText: title })).toBeVisible();
  const id = (await (await request.get("/api/songs?q=" + encodeURIComponent(title))).json()).songs[0].id;
  const token = await tokenInPage(a, id);
  await waitStatus(request, id);
  await expect(a.locator(".song", { hasText: title }).locator("[data-act=menu]")).toBeVisible();

  // B: a different browser
  const errs = []; page.on("pageerror", e => errs.push(String(e)));
  await page.goto("/?lang=zh#/?tab=mine");
  await expect(page.locator(".song", { hasText: title })).toBeVisible();
  await expect(page.locator(".song", { hasText: title }).locator("[data-act=menu]")).toHaveCount(0);
  // A again, after clearing its site data
  await a.evaluate(() => localStorage.clear());
  await a.reload();
  await expect(a.locator(".song", { hasText: title })).toBeVisible();
  await expect(a.locator(".song", { hasText: title }).locator("[data-act=menu]")).toHaveCount(0);
  await a.goto(`/?lang=zh#/s/${id}`);
  await expect(a.locator("#play")).toBeEnabled({ timeout: 120_000 });
  await expect(a.locator("#editBtn")).toHaveCount(0);
  await shot(a, "67-relay-cleared-storage");
  await expect(a.locator(".toast, .card.err")).toHaveCount(0);
  // a token kept for a song that is already gone: the delete just finishes, no error
  await a.evaluate(([id, tk]) => localStorage.setItem("jam.owned", JSON.stringify({ [id]: tk })), [id, token]);
  expect(await deleteWithToken(request, id, token)).toBe(204);
  await a.goto("/?lang=zh#/?tab=mine");
  await expect(a.locator(".song", { hasText: title })).toHaveCount(0);
  await expect(a.locator(".toast, .card.err")).toHaveCount(0);
  note("relay-other-browser", { proj: info.project.name, id });
  expect(errs).toEqual([]);
  await ctxA.close();
});

// C3 at the front door: the relay caps request bodies at 52 MB (the server's own limit is 50 MB). The page refuses a
// too-big file before sending it; a direct call is refused by the relay with 413 and never reaches the queue.
test("C3: a file over the limit is refused before uploading; the relay answers 413 to a direct call", async ({ page, request }, info) => {
  const big = Buffer.concat([fs.readFileSync(AUDIO), Buffer.alloc(53 * 1024 * 1024)]);
  await page.goto("/?lang=zh");
  await page.click("#upOpen");
  const bigPath = path.join(test.info().outputDir, "big.mp3");   // Playwright refuses in-memory buffers over 50 MB
  fs.mkdirSync(path.dirname(bigPath), { recursive: true }); fs.writeFileSync(bigPath, big);
  await page.setInputFiles("#file", bigPath);
  await expect(page.locator("#upFile")).toContainText("超过 50 MB 上限");
  await expect(page.locator("#upForm")).toBeHidden();
  await shot(page, "69-relay-too-big");
  const before = (await (await request.get("/api/songs")).json()).songs.length;
  const r = await request.post("/api/songs", { multipart: { file: { name: "big.mp3", mimeType: "audio/mpeg", buffer: big }, title: "too big relay" } });
  note("relay-too-big", { proj: info.project.name, status: r.status() });
  expect(r.status()).toBe(413);
  expect((await (await request.get("/api/songs")).json()).songs.length).toBe(before);
  fs.rmSync(bigPath, { force: true });
});

test("public smoke through the relay: A1 first screen, B2 open a library song and play (+1)", async ({ page, request }, info) => {
  const errs = []; page.on("pageerror", e => errs.push(String(e)));
  await page.goto("/?lang=zh");
  await expect(page.locator(".song").first()).toBeVisible();
  const visible = await page.evaluate(() => [...document.querySelectorAll(".song")].filter(e => { const r = e.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }).length);
  expect(visible).toBeGreaterThanOrEqual(5);
  await shot(page, "68-relay-home");
  const before = (await (await request.get(`/api/songs/${other.id}`)).json()).plays || 0;
  await page.goto(`/?lang=zh#/s/${other.id}`);
  await expect(page.locator("#play")).toBeEnabled({ timeout: 120_000 });
  await page.click("#play");
  await page.waitForFunction(() => window.__jam && window.__jam.player.playing);
  await expect.poll(async () => (await (await request.get(`/api/songs/${other.id}`)).json()).plays).toBe(before + 1);
  note("relay-smoke", { proj: info.project.name, visible, before });
  expect(errs).toEqual([]);
});
