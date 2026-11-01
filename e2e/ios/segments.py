#!/usr/bin/env python3
"""Cut the recorded system audio at the logged steps and print the level of each segment.
The recording has an unknown start latency, so the offset is found by aligning the first loud
moment with the 'play' step (the 'before_play' segment must then be silent)."""
import json
import re
import subprocess
import sys

steps = [json.loads(l) for l in open(sys.argv[1])]
wav = sys.argv[2]


def vol(a, b):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", str(max(0, a)), "-t", str(max(0.2, b - a)), "-i", wav,
                        "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"mean_volume: (-?[\d.inf]+) dB", r.stderr)
    x = re.search(r"max_volume: (-?[\d.inf]+) dB", r.stderr)
    return (float(m.group(1)) if m else -120.0, float(x.group(1)) if x else -120.0)


# find the first second whose level is above -50 dB: that is when playback started
# (the file may begin long before the steps clock: ScreenCaptureKit delivers silent buffers
# from stream start, and the recorder starts before the page is driven)
r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", wav, "-af",
                    "asetnsamples=12000,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
                    "-f", "null", "-"], capture_output=True, text=True)
levels = [float(x) if x not in ("-inf", "inf") else -120.0 for x in re.findall(r"RMS_level=(-?[\d.]+|-inf)", r.stderr)]
step = 12000 / 48000
onset = next((i * step for i, db in enumerate(levels) if db > -50), None)
play = next(s["t"] for s in steps if s["step"] == "play")
off = (onset - play) if onset is not None else 0.0
print("recording offset vs steps: %.2f s (first sound at %.2f s in the file)" % (off, onset or -1))
# measure 2.5 s windows ending at each observation step
res = {}
prev = None
for s in steps:
    if s["step"] not in ("before_play", "playing", "karaoke", "full_again", "drums_solo", "transposed", "slow", "paused",
                         "resumed", "stage_playing"):
        prev = s
        continue
    if s["step"] in ("before_play", "playing", "karaoke", "full_again", "drums_solo", "transposed", "slow", "paused",
                     "resumed", "stage_playing"):
        # window: the 2.5 s before the observation, but not earlier than 0.8 s after the action
        # that led to it (so a fade or the action itself does not leak into the measurement)
        # (and end 0.4 s early: the offset estimate is only good to ~0.2 s, and the next action
        # follows the observation immediately)
        a, b = s["t"] + off - 2.5, s["t"] + off - 0.4
        if prev is not None:
            a = max(a, prev["t"] + off + 0.8)
        mean, mx = vol(a, b)
        res[s["step"]] = mean
        print("%-14s mean=%6.1f dB  max=%6.1f dB" % (s["step"], mean, mx))
    prev = s

LOUD, SILENT = -45.0, -70.0
checks = [("before_play is silent", res.get("before_play", 0) < SILENT)]
checks += [("%s has sound" % k, res.get(k, -120) > LOUD) for k in
           ("playing", "karaoke", "full_again", "transposed", "slow", "resumed", "stage_playing")]
checks += [("drums_solo quieter than full mix", res.get("drums_solo", 0) < res.get("full_again", -120)),
           ("paused is silent", res.get("paused", 0) < SILENT)]
for name, ok in checks:
    print("%s  %s" % ("PASS" if ok else "FAIL", name))
print("RESULT", "PASS" if all(ok for _, ok in checks) else "FAIL")
sys.exit(0 if all(ok for _, ok in checks) else 1)
