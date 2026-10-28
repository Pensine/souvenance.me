"""Piper TTS worker, run inside the TTS environment (piper-tts + onnx).

    python tts_worker.py jobs.json
    python tts_worker.py --download          # fetch the five voices once

Each job: {"text", "voice", "out", "seed"}. Writes <out>.wav (22.05 kHz
mono) with light noise added (about -38 dBFS, seeded) and a random lead-in,
so recordings are not studio-clean. Kept standalone: it must not import the
generator package.

Voices are the five Piper voices trained only on public-domain speech (see
SPEC section 9), downloaded from huggingface.co/rhasspy/piper-voices at a
pinned revision and checked against SHA-256. They are looked up in
$SOURCED_PIPER_VOICES (default ~/.cache/sourced/piper-voices).

Determinism: Piper's ONNX graphs draw noise with RandomNormalLike nodes that
carry no seed, so two runs differ. The worker writes a seed derived from
the job seed into those nodes (in memory, one session per job, one CPU
thread), which makes a job reproducible on the same machine and library
versions. Bit-identity across machines is not promised.

Setup:
  python3.11 -m venv ~/.cache/sourced/piper-venv
  ~/.cache/sourced/piper-venv/bin/pip install piper-tts==1.8.0 onnx soundfile
  ~/.cache/sourced/piper-venv/bin/python sourced/tts_worker.py --download
Keep the venv path short: espeak-ng ignores a data path longer than about
160 characters and then fails with "phontab: No such file or directory".
"""

import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

REVISION = "5041a7a49ae5b3a0f30e6837769eb03fdbb231bd"  # rhasspy/piper-voices, 2026-10-28
VOICES = {  # name -> (path in the repository, SHA-256 of the .onnx)
    "en_US-ljspeech-medium": ("en/en_US/ljspeech/medium",
                              "6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22"),
    "en_US-kristin-medium": ("en/en_US/kristin/medium",
                             "5849957f929cbf720c258f8458692d6103fff2f0e3d3b19c8259474bb06a18d4"),
    "en_US-norman-medium": ("en/en_US/norman/medium",
                            "b9739443232a80a59c7d18810dd856899bf16a7964725f5ab81ea49b1351cb71"),
    "en_US-john-medium": ("en/en_US/john/medium",
                          "789c6c875726e627ddee93d51d8727859abe9c091c3d141591f4b83c2072e988"),
    "en_GB-cori-medium": ("en/en_GB/cori/medium",
                          "1899f98e5fb8310154f3c2973f4b8a929ba7245e722b3d3a85680b833d95f10d"),
}
VOICE_DIR = Path(os.environ.get("SOURCED_PIPER_VOICES",
                                Path.home() / ".cache" / "sourced" / "piper-voices"))


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def download() -> None:
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    base = f"https://huggingface.co/rhasspy/piper-voices/resolve/{REVISION}"
    for name, (sub, digest) in VOICES.items():
        for remote, local in ((f"{name}.onnx", f"{name}.onnx"),
                              (f"{name}.onnx.json", f"{name}.onnx.json"),
                              ("MODEL_CARD", f"{name}.MODEL_CARD")):
            if not (VOICE_DIR / local).exists():
                urllib.request.urlretrieve(f"{base}/{sub}/{remote}", VOICE_DIR / local)
        if _sha256(VOICE_DIR / f"{name}.onnx") != digest:
            sys.exit(f"checksum mismatch for {name}.onnx")
        print(f"ok {name}", flush=True)


def _seeded_session(model, seed: int):
    import onnx
    import onnxruntime

    for node in model.graph.node:
        if node.op_type.startswith("Random"):
            for a in [a for a in node.attribute if a.name == "seed"]:
                node.attribute.remove(a)
            node.attribute.append(onnx.helper.make_attribute("seed", float(seed)))
    opts = onnxruntime.SessionOptions()
    opts.intra_op_num_threads = opts.inter_op_num_threads = 1
    return onnxruntime.InferenceSession(model.SerializeToString(), sess_options=opts,
                                        providers=["CPUExecutionProvider"])


def main() -> None:
    import numpy as np
    import onnx
    import soundfile as sf
    from piper import PiperVoice

    jobs = json.loads(Path(sys.argv[1]).read_text())
    loaded: dict = {}
    for j in jobs:
        name = j["voice"]
        if name not in VOICES:
            sys.exit(f"unknown voice {name!r}: expected one of {sorted(VOICES)}")
        if name not in loaded:
            path = VOICE_DIR / f"{name}.onnx"
            if not path.exists():
                sys.exit(f"{path} missing: run tts_worker.py --download")
            if _sha256(path) != VOICES[name][1]:
                sys.exit(f"checksum mismatch for {path}")
            loaded[name] = (PiperVoice.load(path), onnx.load(str(path)))
        voice, model = loaded[name]
        seed = int(hashlib.sha256(j["seed"].encode()).hexdigest()[:8], 16)
        voice.session = _seeded_session(model, seed % 2**31)
        sr = voice.config.sample_rate
        chunks = [c.audio_float_array.astype(np.float32) for c in voice.synthesize(j["text"])]
        audio = np.concatenate(chunks) if chunks else np.zeros(sr, dtype=np.float32)
        rng = np.random.default_rng(seed)
        lead = np.zeros(int(sr * rng.uniform(0.2, 0.6)), dtype=np.float32)
        audio = np.concatenate([lead, audio, lead[: sr // 4]])
        audio = audio + rng.normal(0, 0.0125, audio.shape).astype(np.float32)
        audio = np.clip(audio, -1, 1)
        sf.write(Path(j["out"]).with_suffix(".wav"), audio, sr, subtype="PCM_16")
        print(f"tts {Path(j['out']).name} {name} {len(audio) / sr:.1f}s", flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--download"]:
        download()
    else:
        main()
