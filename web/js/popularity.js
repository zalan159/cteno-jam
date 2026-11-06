// Popularity ("热度"): the compact play-count label and the one rule that mixes local songs with
// Jamendo search results. Pure functions, no DOM, so node --test covers them (web/test/popularity.test.mjs).
//
// Two kinds of numbers:
//   * local songs   — `plays`: how often people on THIS server started playing or jamming the song
//                     (counted by the server, one per browser session per 30 s, see app.py /play).
//   * Jamendo songs — `listens`: Jamendo's own all-time listen counter (stats.rate_listened_total),
//                     and the API already returns them in order=popularity_total.
// Jamendo's audience is far larger than one Jam server, so raw numbers are not comparable. The mixed
// list uses a fixed exchange rate: one local play weighs as much as JAMENDO_PER_PLAY Jamendo listens.
//   score(local)   = plays * JAMENDO_PER_PLAY
//   score(jamendo) = listens
// Each source keeps its own order (local by plays, Jamendo as the API ranked it) and the two lists are
// merged by comparing the scores at their heads; on a tie the local song wins (it is ready to play).
// A Jamendo track that is already in the library (imported earlier) is shown once, as the local song.

export const JAMENDO_PER_PLAY = 1000;

export function localScore(m, rate = JAMENDO_PER_PLAY) { return (Number(m && m.plays) || 0) * rate; }
export function jamendoScore(r) { return Number(r && r.listens) || 0; }

// Local songs: most played first; equal counts keep the newest first.
export function sortLocal(songs) {
  return [...(songs || [])].sort((a, b) => ((b.plays || 0) - (a.plays || 0)) || ((b.created || 0) - (a.created || 0)));
}

// -> [{kind:"local", song, score} | {kind:"jamendo", track, score}]
export function mixResults(localSongs, jamendoTracks, rate = JAMENDO_PER_PLAY) {
  const local = sortLocal(localSongs);
  const have = new Set(local.filter(m => m.source && m.source.kind === "jamendo").map(m => String(m.source.id)));
  const jm = (jamendoTracks || []).filter(r => !have.has(String(r.id)));
  const out = [];
  let i = 0, j = 0;
  while (i < local.length || j < jm.length) {
    const ls = i < local.length ? localScore(local[i], rate) : -1;
    const js = j < jm.length ? jamendoScore(jm[j]) : -1;
    if (i < local.length && ls >= js) { out.push({ kind: "local", song: local[i], score: ls }); i++; }
    else { out.push({ kind: "jamendo", track: jm[j], score: js }); j++; }
  }
  return out;
}

// 1234 -> "1234" / "1.2K"; 12345 -> "1.2万" / "12.3K"; 123456789 -> "1.2亿" / "123.4M".
// Truncated, never rounded up, so a label never claims more plays than there were.
export function compactCount(n, lang = "zh") {
  n = Math.max(0, Math.floor(Number(n) || 0));
  const cut = (v, d) => { const s = (Math.floor(v * 10 ** d) / 10 ** d).toFixed(d); return s.replace(/\.0+$/, ""); };
  if (lang === "zh") {
    if (n < 10000) return String(n);
    if (n < 1e8) return cut(n / 1e4, n < 1e5 ? 1 : 0) + "万";
    return cut(n / 1e8, 1) + "亿";
  }
  if (n < 1000) return String(n);
  if (n < 1e6) return cut(n / 1e3, n < 1e5 ? 1 : 0) + "K";
  if (n < 1e9) return cut(n / 1e6, n < 1e8 ? 1 : 0) + "M";
  return cut(n / 1e9, 1) + "B";
}

export const playsLabel = (n, lang = "zh") => "▶ " + compactCount(n, lang);
