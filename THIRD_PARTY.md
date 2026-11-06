# Third-party software, models, data and content

Cteno Jam itself is licensed under the [Apache License 2.0](LICENSE). It builds on the
components below. Versions are the ones tested (see `docs/evidence/`). Licenses were
checked against each project's own repository or package metadata on 2026-11-01.

## Shipped in this repository

| Component | Where | License | Notes |
|---|---|---|---|
| [Signalsmith Stretch (Web)](https://signalsmith-audio.co.uk/code/stretch/) 1.3.2 | `web/vendor/SignalsmithStretch.mjs` | MIT | Pitch shift / time stretch in an AudioWorklet (WASM). Unmodified npm build. |
| [qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator) 2.0.4 | `web/vendor/qrcode.mjs` | MIT | QR codes for share links. "QR Code" is a registered trademark of DENSO WAVE INCORPORATED. |
| Demo songs (`demo/`) | `demo/source`, `demo/songs` | **CC0 1.0** (our audio) on **public-domain** works | See *Demo content* below. |

## Online services (optional)

| Service | When | Terms |
|---|---|---|
| [Jamendo API](https://developer.jamendo.com/v3.0) | only with `JAM_JAMENDO_CLIENT_ID` set | Search/preview/download through the server. Jam shows and imports only tracks with `audiodownload_allowed`; each imported song keeps its Creative Commons license name and URL, the artist and the Jamendo page. Users must follow the track's license (many are NonCommercial / NoDerivatives). |

## Installed at build/run time (not vendored)

| Component | License | Used for |
|---|---|---|
| [Demucs](https://github.com/facebookresearch/demucs) 4.0.1 | MIT | Stem separation |
| Demucs pretrained weights `htdemucs_6s` (downloaded from `dl.fbaipublicfiles.com`) | MIT (released with the Demucs repository) | 6-stem model: vocals, guitar, piano, bass, drums, other. Upstream notes the piano stem has noticeable bleed. |
| [PyTorch](https://pytorch.org) / torchaudio 2.5.1 | BSD-3-Clause / BSD-2-Clause | Model runtime |
| [librosa](https://librosa.org) 0.10.2 | ISC | Beats, chroma, onsets, pitch |
| [NumPy](https://numpy.org), [SciPy](https://scipy.org) | BSD-3-Clause | DSP |
| [soundfile](https://github.com/bastibe/python-soundfile) / libsndfile | BSD-3-Clause / LGPL-2.1 (shared library, unmodified) | WAV I/O |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 1.2, [CTranslate2](https://github.com/OpenNMT/CTranslate2) 4.x | MIT | Lyrics transcription when no lyrics are found |
| Whisper weights `Systran/faster-whisper-small` (Hugging Face) | MIT (OpenAI Whisper) | Speech/lyrics recognition |
| [pypinyin](https://github.com/mozillazg/python-pinyin) | MIT | Matching Chinese lyrics to transcribed words |
| [FastAPI](https://fastapi.tiangolo.com), [Starlette](https://www.starlette.io), [Uvicorn](https://www.uvicorn.org), python-multipart | MIT / BSD-3-Clause / BSD-3-Clause / Apache-2.0 | Web server |
| [FFmpeg](https://ffmpeg.org) (Debian package in the Docker image) | LGPL-2.1+ / GPL-2.0+ depending on build | Decoding uploads, encoding stems. Called as a separate program, not linked. |
| [Cteno SDK](https://github.com/zalan159/cteno-sdk) `cteno-sdk` 2.10.15+ (optional) | Client: MIT. Bundled daemon binaries: Cteno Daemon Binary License (free use and unmodified redistribution) | AI review agent (optional extra `review`) |
| Python 3.12 (Docker base image `python:3.12-slim-bookworm`), Debian | PSF / various | Runtime |

Test-only: [Playwright](https://playwright.dev) (Apache-2.0), pytest (MIT), httpx (BSD-3-Clause);
for the iOS Simulator run, [ios-webkit-debug-proxy](https://github.com/google/ios-webkit-debug-proxy)
(BSD-3-Clause, installed with Homebrew on the test Mac, not bundled). Deployment script uses
[Caddy](https://caddyserver.com) (Apache-2.0) if already present on the server (not bundled).

## Online services (optional, off by configuration)

- **LRCLIB** (`https://lrclib.net`): free synced-lyrics database, no key. When enabled
  (`JAM_LRCLIB=1`, default) the server sends the song **title, artist and duration** to look up
  lyrics. Lyrics returned by LRCLIB belong to their rights holders; Cteno Jam only shows them
  to the person who uploaded the song and never redistributes them. Set `JAM_LRCLIB=0` to stay offline.
- **Your model provider** (only if you configure an AI key): the AI review sends the detected
  analysis (key, tempo, chord list, lyric lines and timings, title) to the endpoint you set,
  e.g. DeepSeek. No audio is sent.

## Demo content

The repository contains **no commercial recordings, lyrics or stems**. The two demo songs were
synthesised from scratch by `scripts/make_demo.py` (numpy oscillators and formant filters, no
samples) and are dedicated to the public domain under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/):

| Song | Melody | Lyrics |
|---|---|---|
| Twinkle, Twinkle, Little Star | "Ah! vous dirai-je, maman", French folk tune, first published 1761 — public domain | Jane Taylor, "The Star", 1806 — public domain |
| Frère Jacques | Traditional French round, 18th century — public domain | Traditional — public domain |

The stems in `demo/songs/` were produced from those files by the pipeline itself (Demucs
`htdemucs_6s`); the chord charts and AI revisions in `song.json` are machine output.

## Your uploads

Songs you upload stay on your server. You are responsible for having the right to use them.
Do not publish a public instance that serves copyrighted recordings to people who do not own them.
