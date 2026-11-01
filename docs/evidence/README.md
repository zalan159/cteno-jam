# Test evidence

Everything here was produced by real runs on test machines (a Linux box with an NVIDIA GPU for
the server, unit tests and Docker; a Mac with Playwright browsers and the iOS Simulator for the
browser runs). Machine paths are scrubbed (`scripts/scrub_evidence.py`). No API keys appear
anywhere (checked for `sk-` strings).

| Folder | What | Command | Result |
|---|---|---|---|
| [`unit/`](unit/) | server pytest (API, queue, patches validator, AI review with a fake model incl. invalid-patch rejection) + web `node:test` (chord theory) | `bash scripts/unit.sh` | 43 passed · 3 passed |
| [`e2e/`](e2e/) | Playwright, WebKit + Chromium at iPhone size and Chromium desktop: upload → process → chart → play (level measured) → stems → transpose → speed → loop → count-in → edit/undo → print/PDF → second device follows → big screen → remote → rename/delete; failed upload + retry | `scripts/e2e_all.sh` | 6 passed (2.6 min). `steps.jsonl` has every measured value, `*.png` every step, `artifacts/` the videos |
| [`ios/`](ios/) | real Mobile Safari in the iOS Simulator (iPhone 17, iOS 26.2 runtime) driven through Web Inspector; the Mac's system audio is recorded and cut at each step | `zsh e2e/ios/run_sim_gui.sh <server-ip> demo-twinkle docs/evidence/ios` | all 10 audio checks PASS: silent before play (−91 dB), ~−27 dB playing, karaoke/transposed/0.8× all audible, drums solo quieter (−36.5 dB), paused silent (−91 dB); 0 page errors. `system-audio.mp3` is the recording, `simulator-recording.mp4` the screen |
| [`docker/`](docker/) | CPU and GPU images built and smoke-tested: API up, demo songs seeded, one demo song uploaded and processed | `bash scripts/docker_smoke.sh cteno-jam:cpu` / `cteno-jam:gpu --gpus all` | CPU: separation 9.4 s, `device: cpu`; GPU (RTX 4000 Ada): separation 3.0 s, `device: cuda`; key D major, 99.4 BPM, 41 chords, 12 lyric lines in both |
| [`ai-review/`](ai-review/) | real AI review with DeepSeek (`deepseek-chat`) through the Cteno Agent SDK on both demo songs: before/after song JSON, diff with every reason | `python scripts/ai_review_evidence.py …` | Frère Jacques: 10 accepted / 0 rejected (28 s); Twinkle: 6 accepted / 0 rejected (9 s) |
| [`deploy/`](deploy/) | public demo at https://jam.cteno.cn checked from outside: library, demo plays (−16.7 dB), a second phone opens the share link and follows | `node e2e/live_check.mjs https://jam.cteno.cn` | ok, follower offset 6 ms, 0 errors |

Known gaps in the evidence: the iPhone side silent switch cannot be tested in the Simulator
(the code sets `navigator.audioSession.type = "playback"`, read back as `playback` in
`ios/steps.jsonl`); Whisper transcription is exercised by the pipeline but returns nothing on the
synthetic demo voice, so the demos use their bundled LRC lyrics.
