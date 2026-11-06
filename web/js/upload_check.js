// Spot encrypted music-app downloads (QQ Music, NetEase, Kugou, Kuwo, Apple Music) from the file name
// as soon as a file is picked, so the user hears about it before uploading. The server checks the
// file contents too (server/cteno_jam/pipeline/drm.py); keep the two lists in step.
const EXT = {
  qq: ["mgg", "mgg0", "mgg1", "mgg2", "mgga", "mggl", "mflac", "mflac0", "mflac1", "mflaca", "mmp4", "tkm"],
  netease: ["ncm"],
  kugou: ["kgm", "kgma", "kgg", "vpr"],
  kuwo: ["kwm"],
  apple: ["m4p"],
};
const QQ_PREFIX = ["qmc", "mgg", "mflac", "bkc"];

export function encryptedFamily(name) {
  const parts = String(name || "").toLowerCase().split(/[\\/]/).pop().split(".").slice(1).map(s => s.trim());
  for (const p of parts) {
    for (const [fam, list] of Object.entries(EXT)) if (list.includes(p)) return fam;
    if (QQ_PREFIX.some(x => p.startsWith(x))) return "qq";
  }
  return null;
}

// ---------------------------------------------------------------- picking files on phones
// Keep in step with ALLOWED_EXT in server/cteno_jam/pipeline/audio.py.
export const AUDIO_EXT = ["mp3", "m4a", "aac", "wav", "flac", "ogg", "opus", "webm", "mp4", "caf", "aiff", "aif", "amr", "3gp", "3ga", "wma"];

// accept= for the file input. iOS greys out files whose type is not listed, so the extensions are
// spelled out next to audio/* (WeChat voice files are .amr, Android recorders .3gp/.m4a).
// Inside WeChat on Android, any audio filter makes the X5/XWeb chooser offer only the voice recorder
// and hides the file manager, so there we accept everything and check the file after it is picked.
export function acceptFor(ua) {
  const u = String(ua || "");
  if (/MicroMessenger/i.test(u) && /Android/i.test(u)) return "*/*";
  return "audio/*," + AUDIO_EXT.map(e => "." + e).join(",");
}
export const isWeChat = ua => /MicroMessenger/i.test(String(ua || ""));

// "ok" when the picked file may be audio; "not_audio" when it clearly is something else (a photo, a PDF).
// Files from WeChat or a file manager may have no extension and an empty type: let the server decide.
export function checkPicked(name, type) {
  const n = String(name || "").toLowerCase().split(/[\\/]/).pop();
  const ext = n.includes(".") ? n.split(".").pop().trim() : "";
  if (AUDIO_EXT.includes(ext)) return "ok";
  const ty = String(type || "").toLowerCase();
  if (ty.startsWith("audio/") || ty === "video/mp4" || ty === "video/webm" || ty === "video/3gpp") return "ok";
  if (!ty || ty === "application/octet-stream") return ext && /^(jpe?g|png|gif|heic|webp|pdf|docx?|xlsx?|pptx?|txt|zip|rar|apk|exe)$/.test(ext) ? "not_audio" : "ok";
  return "not_audio";
}

// ---------------------------------------------------------------- in-browser recording
// MediaRecorder formats in order of preference. iOS Safari records only AAC in MP4 (audio/mp4);
// Chrome/Firefox/Android record Opus in WebM or Ogg.
const REC_TYPES = ["audio/mp4;codecs=mp4a.40.2", "audio/mp4", "audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/aac"];
export function pickRecordingType(isTypeSupported) {
  for (const ty of REC_TYPES) { try { if (isTypeSupported(ty)) return ty; } catch (e) {} }
  return "";  // let the browser choose; the blob's own type tells us afterwards
}
export function extForType(type) {
  const ty = String(type || "").toLowerCase();
  if (ty.includes("mp4") || ty.includes("m4a")) return "m4a";
  if (ty.includes("webm")) return "webm";
  if (ty.includes("ogg")) return "ogg";
  if (ty.includes("aac")) return "aac";
  if (ty.includes("wav")) return "wav";
  if (ty.includes("mpeg")) return "mp3";
  return "m4a";
}
// getUserMedia errors -> i18n key of a message the user can act on
export function micErrorKey(err) {
  const n = err && err.name;
  if (n === "NotAllowedError" || n === "SecurityError" || n === "PermissionDeniedError") return "rec_denied";
  if (n === "NotFoundError" || n === "DevicesNotFoundError" || n === "OverconstrainedError") return "rec_nomic";
  if (n === "NotReadableError" || n === "TrackStartError" || n === "AbortError") return "rec_busy";
  return "rec_failed";
}
