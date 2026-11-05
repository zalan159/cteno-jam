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
