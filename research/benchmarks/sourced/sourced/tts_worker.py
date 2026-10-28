"""Kokoro-82M worker, run inside the TTS environment (mlx-audio + misaki).

    python tts_worker.py jobs.json

Each job: {"text", "voice", "out", "seed"}. Writes <out>.wav (24 kHz mono)
with light noise added (about -38 dBFS, seeded), so recordings are not
studio-clean. Kept standalone: it must not import the generator package.

Setup notes (macOS, Apple silicon):
  python -m venv tts-venv && tts-venv/bin/pip install mlx-audio soundfile "misaki[en]"
  The espeakng_loader wheel may ship without its data files ("phontab: No
  such file or directory"): link the system espeak-ng data into it, e.g.
  for f in /opt/homebrew/share/espeak-ng-data/*; do
    ln -sf "$f" tts-venv/lib/python3.11/site-packages/espeakng_loader/; done
"""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from mlx_audio.tts.utils import load_model

MODEL = "mlx-community/Kokoro-82M-bf16"
SR = 24000


def main() -> None:
    jobs = json.loads(Path(sys.argv[1]).read_text())
    model = load_model(MODEL)
    for j in jobs:
        lang = "b" if j["voice"].startswith("b") else "a"
        chunks = [np.array(r.audio, dtype=np.float32)
                  for r in model.generate(text=j["text"], voice=j["voice"], speed=1.0,
                                          lang_code=lang)]
        audio = np.concatenate(chunks) if chunks else np.zeros(SR, dtype=np.float32)
        seed = int(hashlib.sha256(j["seed"].encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        lead = np.zeros(int(SR * rng.uniform(0.2, 0.6)), dtype=np.float32)
        audio = np.concatenate([lead, audio, lead[: SR // 4]])
        audio = audio + rng.normal(0, 0.0125, audio.shape).astype(np.float32)
        audio = np.clip(audio, -1, 1)
        sf.write(Path(j["out"]).with_suffix(".wav"), audio, SR, subtype="PCM_16")
        print(f"tts {Path(j['out']).name} {len(audio) / SR:.1f}s", flush=True)


if __name__ == "__main__":
    main()
