# Deploying Cteno Jam · 部署方案

Cteno Jam has two very different halves:

| Part | Needs | Where it fits |
|---|---|---|
| **Player + sync rooms** (static files, a WebSocket hub) | ~65 MB RAM, no GPU, no PyTorch | any small VPS, a NAS, GitHub Pages + a sync host |
| **Processing** (Demucs, librosa, Whisper, optional AI review) | 3–4 GB RAM per job, PyTorch; a GPU makes separation ~3× faster | a home PC / Mac mini / NAS with enough RAM, or a GPU box |

## 1. Self-hosting for your own group (recommended)

One machine runs everything:

```bash
cp .env.example .env     # set JAM_ADMIN_KEY if others can reach it
docker compose up -d     # or the GPU override
```

Friends on the same Wi-Fi open `http://<that-machine>:8765`. For pitch-preserving speed/key on
phones the page must be **https or localhost** (browsers only enable AudioWorklet there), so
put it behind a reverse proxy with a certificate (Caddy does this automatically) or use a
tunnel. Set `JAM_PUBLIC_URL` to the https address so share links and QR codes use it.

## 2. Player-only demo on a small VPS

```bash
JAM_DEPLOY_SSH=root@your-vps JAM_DEPLOY_DOMAIN=jam.example.com bash scripts/deploy_relay.sh
```

- static player with the bundled CC0 demo songs in `/srv/jam/www`
- `cteno-jam` with `JAM_MODE=player` as systemd unit `cteno-jam-sync` (sync rooms only; uploads
  return 403; capped at 200 MB RAM)
- a Caddy site block in `/etc/caddy/sites/cteno-jam.caddy` (`/ws/*` and `/api/info` → the sync
  service, everything else → static files). Other sites on the box are left untouched.

A 2-core / 1 GB VPS cannot run stem separation (Demucs alone peaks at several GB), so **do not
run processing there**.

## 3. Where processing should run (plan for a hosted version)

1. **Now — at home.** The full image on a home machine (any 16 GB PC/Mac; a gaming GPU if you have
   one). The VPS only serves the player. This costs nothing extra and keeps users' audio at home.
2. **Hosted uploads later — a GPU worker pulled by the VPS.** Keep the VPS as the public front door
   (player, library, rooms, uploads stored on disk/object storage). Run the `cteno-jam` worker on
   a rented GPU (on-demand cloud GPU or a spot instance) that pulls jobs, processes them and pushes
   stems back. A 4-minute song is ~10 s of separation on a mid-range GPU, so one GPU serves
   hundreds of songs per hour; scale to zero when the queue is empty. This needs a small job
   API between front door and worker (the queue is already one subprocess per song, so the
   worker boundary exists).
3. **Never** run processing on the public 1 GB box, and keep user uploads private by default
   (`JAM_ADMIN_KEY`), because people will upload copyrighted recordings.

---

## 中文

- **播放器 + 同步房间**很轻：约 65MB 内存，不需要 GPU，也不装 PyTorch，适合任何小 VPS。
- **处理**很重：每首歌要 3–4GB 内存和 PyTorch；有 GPU 时分轨快约 3 倍。

**自己和朋友用（推荐）**：一台机器 `docker compose up -d` 跑全部。手机要用变速/移调，页面必须是 https 或 localhost，所以请加一个带证书的反向代理（Caddy 会自动签证书），并把 `JAM_PUBLIC_URL` 设成 https 地址。

**小 VPS 上的只读演示**：`scripts/deploy_relay.sh` 装静态播放器、`JAM_MODE=player` 的同步服务（systemd，限 200MB 内存，上传返回 403）和一个 Caddy 站点，不动机器上的其他站点。2 核 1G 的机器跑不了分轨，**不要在上面做处理**。

**处理放在哪里（托管版规划）**：
1. 现在：放在家里的电脑上（16GB 内存的 PC 或 Mac 即可，有游戏显卡更好），VPS 只当播放器。不额外花钱，用户音频也不出门。
2. 以后要开放上传：VPS 继续做公开入口（播放器、曲库、房间、接收上传），处理交给按需租用的 GPU worker，从 VPS 拉任务、处理完把分轨传回。中端 GPU 上一首 4 分钟的歌分轨约 10 秒，一张卡每小时能处理几百首，队列空了就关机。需要在入口和 worker 之间加一个小的任务 API（现在每首歌已经是一个独立子进程，边界是现成的）。
3. 不要在 1G 的公网机器上处理；默认用 `JAM_ADMIN_KEY` 把上传保护起来，因为一定会有人传有版权的录音。

## What jam.cteno.cn runs now · jam.cteno.cn 现在的部署

Since 2026-11-02 jam.cteno.cn is a full instance (upload + processing) on one RTX 4090 at our office,
reached through a small cloud relay (Caddy for TLS, frp tunnel to the GPU box). No passphrase; abuse is
bounded by `JAM_WORKERS=1`, `JAM_MAX_UPLOAD_MB=50`, `JAM_MAX_QUEUE=20`, `JAM_UPLOADS_PER_IP_HOUR=5`
and `JAM_MAX_DISK_PERCENT=80`, and the relay answers 403 to rename/delete/edit/retry/review so visitors
cannot touch other people's songs. One 4-minute song takes about 42 s on the GPU (~2 GB VRAM peak).

2026-11-02 起 jam.cteno.cn 是完整实例（可上传、可处理），跑在办公室一张 RTX 4090 上，经云上中转（Caddy 签证书，frp 隧道到显卡机）对外。不设口令，靠上面这几项限制防刷；中转层对重命名/删除/编辑/重试/AI 校对一律返回 403，访客动不了别人的歌。一首 4 分钟的歌在 GPU 上约 42 秒处理完，显存峰值约 2GB。

**Jamendo + popularity (2026-11-07).** The jam container reads `JAM_JAMENDO_CLIENT_ID` from
`/models/cteno-jam/jamendo.env` (mode 600, `env_file` in docker-compose.yml; the value is in the vault as
`jam/JAM_JAMENDO_CLIENT_ID`, developer account `ctenojam` / zal@cteno.ai, password `jam/JAMENDO_DEV_PASSWORD`).
Play counts live in `data/songs/.plays.json`. The relay additionally lets two POSTs through to the public:
`/api/jamendo/import` (same queue/rate/disk guards as an upload) and `/api/songs/{id}/play`.

**Jamendo 与热度（2026-11-07）**：jam 容器从 `/models/cteno-jam/jamendo.env`（权限 600，compose 里用 `env_file`）读
`JAM_JAMENDO_CLIENT_ID`，值在保险箱 `jam/JAM_JAMENDO_CLIENT_ID`（开发者账号 `ctenojam` / zal@cteno.ai，密码
`jam/JAMENDO_DEV_PASSWORD`）。播放次数存在 `data/songs/.plays.json`。中转层对公网额外放行两个 POST：
`/api/jamendo/import`（和上传一样受队列、限频、磁盘限制）和 `/api/songs/{id}/play`。

