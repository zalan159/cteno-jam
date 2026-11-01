#!/usr/bin/env python3
"""Quick check: does Demucs put a synthetic phrase into the vocals stem? (dev tool)"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_demo as M  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/vtest")
out.mkdir(parents=True, exist_ok=True)
song = M.twinkle()
song["bars"] = song["bars"][:7]
song["phrases"] = song["phrases"][:3]
mix, T, truth, lrc = M.render(song)
M.save_wav(out / "clip.wav", mix)
import soundfile  # noqa: F401,E402
import torch  # noqa: E402
from demucs.apply import apply_model  # noqa: E402
from demucs.pretrained import get_model  # noqa: E402

m = get_model("htdemucs_6s")
x = torch.tensor(np.stack([mix, mix]), dtype=torch.float32)[None]
y = apply_model(m, x, shifts=0, split=True, progress=False)[0]
ref = {k: float(np.sqrt(np.mean(v ** 2))) for k, v in T.items()}
tot = sum(ref.values())
print("in :", {k: "%.0f%%" % (100 * v / tot) for k, v in ref.items()})
got = {name: float(y[i].pow(2).mean().sqrt()) for i, name in enumerate(m.sources)}
tot = sum(got.values())
print("out:", {k: "%.0f%%" % (100 * v / tot) for k, v in got.items()})
# correlation of separated vocals with the true vocal track
v = y[m.sources.index("vocals")].mean(0).numpy()
tv = T["vocals"][:len(v)] / (np.abs(mix).max() / 0.9)
print("vocal corr %.2f" % (np.dot(v, tv) / (np.linalg.norm(v) * np.linalg.norm(tv) + 1e-9)))
