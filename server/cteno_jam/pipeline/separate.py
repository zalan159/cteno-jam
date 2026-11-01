"""Source separation with Demucs (htdemucs_6s: vocals, guitar, piano, bass, drums, other)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Dict

STEMS = ["vocals", "guitar", "piano", "bass", "drums", "other"]


def pick_device(pref: str = "auto") -> str:
    import torch
    if pref and pref != "auto":
        return pref
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def separate(wav: Path, out_dir: Path, model_name: str = "htdemucs_6s", device: str = "auto", threads: int = 0,
             progress: Callable[[float], None] = lambda f: None) -> Dict[str, Path]:
    """Separate `wav` into stems written as 44.1 kHz WAV files in `out_dir`. Returns {stem: path}."""
    import torch
    from demucs.apply import apply_model
    from demucs.audio import save_audio
    from demucs.pretrained import get_model
    import soundfile as sf

    if threads:
        torch.set_num_threads(threads)
    dev = pick_device(device)
    model = get_model(model_name)
    model.eval()
    data, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    mix = torch.from_numpy(data.T.copy())
    if sr != model.samplerate:
        raise RuntimeError("expected %d Hz input, got %d" % (model.samplerate, sr))
    if mix.shape[0] == 1:
        mix = mix.repeat(2, 1)
    ref = mix.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    x = (mix - mean) / std

    # demucs reports progress only through tqdm; split into chunks ourselves for a real progress bar
    seg = int(model.samplerate * 40)
    overlap = int(model.samplerate * 1)
    n = x.shape[1]
    outs = torch.zeros(len(model.sources), 2, n)
    weight = torch.zeros(n)
    starts = list(range(0, max(n - overlap, 1), seg - overlap)) or [0]
    with torch.no_grad():
        for k, s in enumerate(starts):
            e = min(n, s + seg)
            chunk = x[:, s:e][None].to(dev)
            y = apply_model(model, chunk, device=dev, shifts=1, split=True, overlap=0.25, progress=False)[0].cpu()
            w = torch.ones(e - s)
            ramp = min(overlap, e - s)
            if s > 0:
                w[:ramp] = torch.linspace(0, 1, ramp)
            if e < n:
                w[-ramp:] = torch.minimum(w[-ramp:], torch.linspace(1, 0, ramp))
            outs[:, :, s:e] += y * w
            weight[s:e] += w
            progress((k + 1) / len(starts))
            if e >= n:
                break
    outs = outs / weight.clamp(min=1e-6)
    outs = outs * std + mean
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for i, name in enumerate(model.sources):
        p = out_dir / ("%s.wav" % name)
        save_audio(outs[i], str(p), samplerate=model.samplerate)
        paths[name] = p
    return paths
