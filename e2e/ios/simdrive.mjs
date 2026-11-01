// Drive real Mobile Safari in an iOS Simulator through ios_webkit_debug_proxy (WebKit Inspector
// protocol, Node >= 22 built-in WebSocket, no dependencies) and log timestamped steps used to cut
// the system-audio recording into segments.
//
//   node simdrive.mjs <steps.jsonl> <rec0-epoch-ms> <song-id> <shot-dir>
//
// Clicks run with emulateUserGesture so iOS lets them start Web Audio, like a real tap.
import fs from 'node:fs';

const [out, rec0s, sid, shotDir] = process.argv.slice(2);
const REC0 = +rec0s;
const WI = process.env.WI || 'ws://127.0.0.1:9222/devtools/page/1';
const f = fs.openSync(out, 'a');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (step, v = {}) => {
  const row = JSON.stringify({ t: +((Date.now() - REC0) / 1000).toFixed(2), step, ...v });
  fs.writeSync(f, row + '\n');
  console.log(row.slice(0, 600));
};

let ws, id = 0, inner = 0, target = null;
const ipend = {};
const consoleMsgs = [];
function connect() {
  return new Promise((resolve, reject) => {
    target = null;
    ws = new WebSocket(WI);
    ws.onerror = (e) => reject(new Error('ws error ' + (e.message || '')));
    ws.onmessage = (m) => {
      const d = JSON.parse(m.data);
      if (d.method === 'Target.targetCreated' && !target) { target = d.params.targetInfo.targetId; resolve(); }
      if (d.method === 'Target.dispatchMessageFromTarget') {
        const x = JSON.parse(d.params.message);
        if (x.id && ipend[x.id]) { ipend[x.id](x); delete ipend[x.id]; }
        if (x.method === 'Console.messageAdded') consoleMsgs.push(x.params.message.level + ': ' + x.params.message.text);
      }
    };
  });
}
const call = (method, params) => new Promise((r) => {
  const i = ++inner; ipend[i] = r;
  ws.send(JSON.stringify({ id: ++id, method: 'Target.sendMessageToTarget',
    params: { targetId: target, message: JSON.stringify({ id: i, method, params }) } }));
});
async function ev(expression, gesture = false) {
  const r = await call('Runtime.evaluate', { expression, returnByValue: true, emulateUserGesture: gesture });
  if (r.error || r.result.wasThrown) throw new Error(JSON.stringify(r).slice(0, 500));
  return r.result.result.value;
}
const tap = (css) => ev(`(()=>{const e=document.querySelector(${JSON.stringify(css)});if(!e)throw new Error('no '+${JSON.stringify(css)});e.click();return true})()`, true);
async function waitFor(expr, ms = 60000) {
  const end = Date.now() + ms;
  while (Date.now() < end) { try { if (await ev(expr)) return true; } catch { /* page reloading */ } await sleep(500); }
  return false;
}
async function shot(name) {
  // Page.snapshotRect returns a data URL of the visible viewport.
  try {
    const dims = await ev('[innerWidth, innerHeight]');
    const r = await call('Page.snapshotRect', { x: 0, y: 0, width: dims[0], height: dims[1], coordinateSystem: 'Viewport' });
    const url = r.result && r.result.dataURL;
    if (url) fs.writeFileSync(`${shotDir}/${name}`, Buffer.from(url.split(',')[1], 'base64'));
  } catch (e) { console.log('shot failed', name, e.message); }
}

const SNAP = `(()=>{const p=__jam.player,st=p.stemTimes(),v=Object.values(st);return {now:+p.now().toFixed(3),playing:p.playing,
ctx:p.ctx&&p.ctx.state,engine:p.engine,semis:p.semis,rate:p.rate,spreadMs:v.length?+((Math.max(...v)-Math.min(...v))*1000).toFixed(3):null,
gains:p.gainsNow(),db:p.levelDb()}})()`;

async function main() {
  await connect();
  await call('Console.enable', {});
  const ok = await waitFor("!!(window.__loadStats || document.querySelector('#status.err'))", 120000);
  log('loaded', { ok, url: await ev('location.href'), stats: await ev('window.__loadStats'), ua: await ev('navigator.userAgent'),
    audioSession: await ev('navigator.audioSession && navigator.audioSession.type'), secure: await ev('window.isSecureContext'),
    msg: await ev("(document.querySelector('#msg')||{}).textContent") });
  await shot('01-loaded.png');
  await ev('__jam.player.seek(2.2)');
  await sleep(1500);
  log('before_play', { db: await ev('__jam.player.levelDb()') });
  await sleep(2000);
  log('play'); await tap('#play');
  await sleep(5000); log('playing', await ev(SNAP));
  await shot('02-playing.png');
  log('karaoke_on'); await tap('#karaoke');
  await sleep(4000); log('karaoke', await ev(SNAP));
  log('karaoke_off'); await tap('#karaoke');
  await sleep(4000); log('full_again', await ev(SNAP));
  log('drums_solo_on'); await tap('.trk[data-stem=drums] .s');
  await sleep(4000); log('drums_solo', await ev(SNAP));
  await tap('.trk[data-stem=drums] .s');
  log('transpose_up2'); await tap('#trUp'); await tap('#trUp');
  await waitFor("__jam.player.engine==='stretch' && __jam.player.semis===2 && __jam.player.playing", 30000);
  await sleep(4000);
  log('transposed', { ...(await ev(SNAP)), capo: await ev("document.querySelector('#capo').innerText"), err: await ev('__jam.player.stretchError||null') });
  await shot('03-transposed.png');
  log('speed_08'); await tap('#spd');
  await waitFor('__jam.player.rate===0.8 && __jam.player.playing', 15000);
  const a = await ev('[__jam.player.now(), performance.now()]'); await sleep(4000); const b = await ev('[__jam.player.now(), performance.now()]');
  log('slow', { ...(await ev(SNAP)), ratio: +((b[0] - a[0]) / ((b[1] - a[1]) / 1000)).toFixed(3) });
  await tap('#spd'); await tap('#spd');
  log('pause'); await tap('#play');
  await sleep(3000); log('paused', await ev(SNAP));
  log('resume'); await tap('#play');
  await sleep(3000); log('resumed', await ev(SNAP));
  await tap('#play');
  log('stage_open');
  await ev(`delete window.__loadStats; location.hash=${JSON.stringify('#/s/' + sid + '/stage')}`);
  await waitFor("!!document.querySelector('#sTap')", 30000);
  await waitFor('!!window.__loadStats', 60000);
  await sleep(1000); await tap('#sTap');
  await sleep(5000);
  log('stage_playing', { ...(await ev(SNAP)), chord: await ev("(document.querySelector('#sCur')||{}).textContent"),
    line: await ev("(document.querySelector('#sLine')||{}).innerText") });
  await shot('04-big-screen.png');
  await ev('__jam.player.stop()');
  await sleep(2000);
  log('end', { errors: await ev('__jam.errors'), consoleErrors: consoleMsgs.filter((m) => /^error/.test(m)) });
}
setTimeout(() => { log('timeout'); process.exit(2); }, 300000);
main().then(() => process.exit(0), (e) => { log('fail', { error: e.message }); process.exit(1); });
