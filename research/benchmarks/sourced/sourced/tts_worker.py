"""TTS worker, run inside a TTS environment, never inside the generator's.

    python tts_worker.py [--engine chatterbox|piper] [--device cpu|mps] jobs.json
    python tts_worker.py [--engine ...] --download   # fetch the pinned files once
    python tts_worker.py [--engine ...] --check      # verify files, load no model

Each job: {"text", "voice", "out", "seed"}. `voice` is one of the five slots
of world.VOICES. Writes <out>.wav (mono, the engine's sample rate) with light
noise added (about -38 dBFS, seeded) and a random lead-in, so recordings are
not studio-clean. Kept standalone: it must not import the generator package.

Engines (SPEC sections 3.3 and 9):

- chatterbox (default): Chatterbox TTS by Resemble AI, MIT, zero-shot
  cloning from a ~10 s public-domain LibriVox clip per slot (voices/refs/,
  listed in voices/refs/REFS.md). chatterbox-tts and the model revision are
  pinned; every model file and reference clip is checked against SHA-256
  before the model is loaded. Every output carries Resemble's Perth
  watermark, imperceptible, which marks the audio as synthetic; the worker
  refuses to run if the watermarker is unavailable.
- piper: the previous engine, kept as a fallback. Five Piper voices trained
  only on public-domain speech, pinned revision, SHA-256 checked.

Determinism: seeds are derived from the job seed (Python, NumPy and torch for
Chatterbox; the ONNX random nodes for Piper). On CPU with the same library
versions a job is meant to be reproducible on the same machine. MPS is faster
but not promised reproducible. Bit-identity across machines is not promised.

Setup (Chatterbox):
  python3.11 -m venv ~/.cache/sourced/chatterbox/venv
  ~/.cache/sourced/chatterbox/venv/bin/pip install chatterbox-tts==0.1.7 resemble-perth==1.0.1
  HF_HOME=~/.cache/sourced/chatterbox/hf \\
      ~/.cache/sourced/chatterbox/venv/bin/python sourced/tts_worker.py --download
Setup (Piper):
  python3.11 -m venv ~/.cache/sourced/piper-venv
  ~/.cache/sourced/piper-venv/bin/pip install piper-tts==1.8.0 onnx soundfile
  ~/.cache/sourced/piper-venv/bin/python sourced/tts_worker.py --engine piper --download
Keep the venv paths short: espeak-ng ignores a data path longer than about
160 characters and then fails with "phontab: No such file or directory".
"""

import argparse
import hashlib
import json
import os
import random
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLOTS = ["female_a", "female_b", "male_a", "male_b", "female_gb"]  # = world.VOICES
ENGINES = ("chatterbox", "piper")

# --- Chatterbox ------------------------------------------------------------

CHATTERBOX_VERSION = "0.1.7"  # chatterbox-tts on PyPI
CHATTERBOX_REPO = "ResembleAI/chatterbox"
CHATTERBOX_REVISION = "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"  # checked 2026-10-28
CHATTERBOX_FILES = {  # the files ChatterboxTTS.from_local reads -> SHA-256
    "ve.safetensors": "f0921cab452fa278bc25cd23ffd59d36f816d7dc5181dd1bef9751a7fb61f63c",
    "t3_cfg.safetensors": "914cb1696f47527fe8852ca8f1fe1fa63cb34f76f9c715e84e067b744dd0da81",
    "s3gen.safetensors": "2b78103c654207393955e4900aac14a12de8ef25f4b09424f1ef91941f161d4e",
    "tokenizer.json": "d71e3a44eabb1784df9a68e9f95b251ecbf1a7af6a9f50835856b2ca9d8c14a5",
    "conds.pt": "6552d70568833628ba019c6b03459e77fe71ca197d5c560cef9411bee9d87f4e",
}
REF_DIR = HERE / "voices" / "refs"
REFS = {  # slot -> SHA-256 of voices/refs/<slot>.wav (sources in REFS.md)
    "female_a": "83698655c117b1943712cda52d69b82bbc781a2f2fbafd4d0628983333e9bac0",
    "female_b": "688b0efd976f0030b08a4448a1da3f5c3555186f831e678a7dc5d398c0ee02d6",
    "male_a": "99ec7aa340553c399285bcaaf4f8a72bf12a26787f81b05a4ce933a559feacf8",
    "male_b": "4faf8facd1d960b64df79e68003be748d5413193e0fab5d8a92a90eff9fa0a60",
    "female_gb": "8a422687c8a54d9e31b1c71e0cf5f594b04a2a42576f52f2fa6ced198982fa19",
}
# chatterbox-tts defaults, written down so a release states them.
CHATTERBOX_PARAMS = {"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8}
MODEL_SEED = 0  # torch seed set before the model is built

# --- Piper (fallback) ------------------------------------------------------

PIPER_REVISION = "5041a7a49ae5b3a0f30e6837769eb03fdbb231bd"  # rhasspy/piper-voices, 2026-10-28
PIPER_VOICES = {  # slot -> (Piper voice, path in the repository, SHA-256 of the .onnx)
    "female_a": ("en_US-ljspeech-medium", "en/en_US/ljspeech/medium",
                 "6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22"),
    "female_b": ("en_US-kristin-medium", "en/en_US/kristin/medium",
                 "5849957f929cbf720c258f8458692d6103fff2f0e3d3b19c8259474bb06a18d4"),
    "male_a": ("en_US-norman-medium", "en/en_US/norman/medium",
               "b9739443232a80a59c7d18810dd856899bf16a7964725f5ab81ea49b1351cb71"),
    "male_b": ("en_US-john-medium", "en/en_US/john/medium",
               "789c6c875726e627ddee93d51d8727859abe9c091c3d141591f4b83c2072e988"),
    "female_gb": ("en_GB-cori-medium", "en/en_GB/cori/medium",
                  "1899f98e5fb8310154f3c2973f4b8a929ba7245e722b3d3a85680b833d95f10d"),
}
PIPER_DIR = Path(os.environ.get("SOURCED_PIPER_VOICES",
                                Path.home() / ".cache" / "sourced" / "piper-voices"))


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def job_seed(seed: str) -> int:
    return int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)


def peak_rss_mb() -> float:
    import resource

    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / 2**20 if sys.platform == "darwin" else r / 1024  # bytes on macOS, KiB on Linux


def _check_jobs(jobs: list) -> None:
    for j in jobs:
        if j["voice"] not in SLOTS:
            sys.exit(f"unknown voice {j['voice']!r}: expected one of {SLOTS}")


def _finish(audio, sr: int, seed: int, out: str) -> float:
    """Lead-in, light seeded noise, clip, 16-bit WAV. Returns the duration."""
    import numpy as np
    import soundfile as sf

    rng = np.random.default_rng(seed)
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    lead = np.zeros(int(sr * rng.uniform(0.2, 0.6)), dtype=np.float32)
    audio = np.concatenate([lead, audio, lead[: sr // 4]])
    audio = audio + rng.normal(0, 0.0125, audio.shape).astype(np.float32)
    audio = np.clip(audio, -1, 1)
    sf.write(Path(out).with_suffix(".wav"), audio, sr, subtype="PCM_16")
    return len(audio) / sr


# --- Chatterbox ------------------------------------------------------------

def _chatterbox_dir(local_only: bool) -> Path:
    """Folder of the pinned snapshot in the Hugging Face cache ($HF_HOME),
    every file checked against SHA-256."""
    from huggingface_hub import hf_hub_download

    folder = None
    for name, digest in CHATTERBOX_FILES.items():
        path = Path(hf_hub_download(CHATTERBOX_REPO, name, revision=CHATTERBOX_REVISION,
                                    local_files_only=local_only))
        if _sha256(path) != digest:
            sys.exit(f"checksum mismatch for {path}")
        folder = path.parent
    return folder


def _check_refs() -> None:
    for slot, digest in REFS.items():
        p = REF_DIR / f"{slot}.wav"
        if not p.exists() or _sha256(p) != digest:
            sys.exit(f"reference clip {p} missing or checksum mismatch")


def _require_watermark() -> None:
    import perth

    if getattr(perth, "PerthImplicitWatermarker", None) is None:
        sys.exit("resemble-perth watermarker unavailable: refusing to write unmarked audio")


def _seed_all(seed: int) -> None:
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed % 2**32)
    torch.manual_seed(seed)


def chatterbox_check(local_only: bool = True) -> Path:
    """Reference clips, watermarker and model files. Loads no model."""
    _check_refs()
    _require_watermark()
    folder = _chatterbox_dir(local_only)
    print(f"ok chatterbox {CHATTERBOX_REPO}@{CHATTERBOX_REVISION[:7]} "
          f"({len(CHATTERBOX_FILES)} files, {len(REFS)} reference clips)", flush=True)
    return folder


def chatterbox_main(jobs: list, device: str, threads: int) -> None:
    import torch
    from chatterbox.tts import ChatterboxTTS

    _check_jobs(jobs)
    folder = chatterbox_check(local_only=True)
    if device == "mps" and not torch.backends.mps.is_available():
        sys.exit("MPS requested but not available; use --device cpu")
    torch.set_num_threads(threads)
    _seed_all(MODEL_SEED)
    t0 = time.monotonic()
    model = ChatterboxTTS.from_local(folder, device)
    print(f"model loaded in {time.monotonic() - t0:.1f}s on {device}, "
          f"peak RSS {peak_rss_mb():.0f} MB", flush=True)
    conds: dict = {}
    for i, j in enumerate(jobs, 1):
        t1 = time.monotonic()
        slot = j["voice"]
        if slot not in conds:  # one conditioning per reference clip
            model.prepare_conditionals(str(REF_DIR / f"{slot}.wav"),
                                       exaggeration=CHATTERBOX_PARAMS["exaggeration"])
            conds[slot] = model.conds
        model.conds = conds[slot]
        seed = job_seed(j["seed"])
        _seed_all(seed % 2**31)
        wav = model.generate(j["text"], **CHATTERBOX_PARAMS)
        dur = _finish(wav.squeeze(0).cpu().numpy(), model.sr, seed, j["out"])
        print(f"clip {i}/{len(jobs)} {Path(j['out']).name} {slot} {dur:.1f}s audio "
              f"in {time.monotonic() - t1:.1f}s, peak RSS {peak_rss_mb():.0f} MB", flush=True)


# --- Piper -----------------------------------------------------------------

def piper_download() -> None:
    PIPER_DIR.mkdir(parents=True, exist_ok=True)
    base = f"https://huggingface.co/rhasspy/piper-voices/resolve/{PIPER_REVISION}"
    for name, sub, digest in PIPER_VOICES.values():
        for remote, local in ((f"{name}.onnx", f"{name}.onnx"),
                              (f"{name}.onnx.json", f"{name}.onnx.json"),
                              ("MODEL_CARD", f"{name}.MODEL_CARD")):
            if not (PIPER_DIR / local).exists():
                urllib.request.urlretrieve(f"{base}/{sub}/{remote}", PIPER_DIR / local)
        if _sha256(PIPER_DIR / f"{name}.onnx") != digest:
            sys.exit(f"checksum mismatch for {name}.onnx")
        print(f"ok {name}", flush=True)


def piper_check() -> None:
    for name, _, digest in PIPER_VOICES.values():
        p = PIPER_DIR / f"{name}.onnx"
        if not p.exists():
            sys.exit(f"{p} missing: run tts_worker.py --engine piper --download")
        if _sha256(p) != digest:
            sys.exit(f"checksum mismatch for {p}")
    print(f"ok piper rhasspy/piper-voices@{PIPER_REVISION[:7]}", flush=True)


def _seeded_session(model, seed: int):
    """Piper's ONNX graphs draw noise with RandomNormalLike nodes that carry
    no seed; write one in (in memory, one session per job, one CPU thread)."""
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


def piper_main(jobs: list) -> None:
    import numpy as np
    import onnx
    from piper import PiperVoice

    _check_jobs(jobs)
    loaded: dict = {}
    for i, j in enumerate(jobs, 1):
        name, _, digest = PIPER_VOICES[j["voice"]]
        if name not in loaded:
            path = PIPER_DIR / f"{name}.onnx"
            if not path.exists():
                sys.exit(f"{path} missing: run tts_worker.py --engine piper --download")
            if _sha256(path) != digest:
                sys.exit(f"checksum mismatch for {path}")
            loaded[name] = (PiperVoice.load(path), onnx.load(str(path)))
        voice, model = loaded[name]
        seed = job_seed(j["seed"])
        voice.session = _seeded_session(model, seed % 2**31)
        sr = voice.config.sample_rate
        chunks = [c.audio_float_array.astype(np.float32) for c in voice.synthesize(j["text"])]
        audio = np.concatenate(chunks) if chunks else np.zeros(sr, dtype=np.float32)
        dur = _finish(audio, sr, seed, j["out"])
        print(f"clip {i}/{len(jobs)} {Path(j['out']).name} {name} {dur:.1f}s", flush=True)


# --- entry point -----------------------------------------------------------

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="SOURCED TTS worker")
    ap.add_argument("jobs", nargs="?")
    ap.add_argument("--engine", choices=ENGINES, default="chatterbox")
    ap.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    ap.add_argument("--threads", type=int, default=int(os.environ.get("SOURCED_TTS_THREADS", 4)),
                    help="torch CPU threads, Chatterbox (default $SOURCED_TTS_THREADS or 4)")
    ap.add_argument("--download", action="store_true", help="fetch the pinned files")
    ap.add_argument("--check", action="store_true", help="verify files, load no model")
    a = ap.parse_args(argv)
    if a.download:
        chatterbox_check(local_only=False) if a.engine == "chatterbox" else piper_download()
        return
    if a.check:
        chatterbox_check() if a.engine == "chatterbox" else piper_check()
        return
    if not a.jobs:
        ap.error("jobs file required")
    jobs = json.loads(Path(a.jobs).read_text())
    t0 = time.monotonic()
    if a.engine == "chatterbox":
        chatterbox_main(jobs, a.device, a.threads)
    else:
        piper_main(jobs)
    print(f"done {len(jobs)} clips in {time.monotonic() - t0:.1f}s, "
          f"peak RSS {peak_rss_mb():.0f} MB", flush=True)


if __name__ == "__main__":
    main()
