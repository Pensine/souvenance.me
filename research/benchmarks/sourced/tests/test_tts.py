"""TTS worker and voice regeneration tests. No model is ever loaded: torch,
chatterbox, perth and soundfile are replaced by small fakes."""

import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sourced import tts_worker as tw  # noqa: E402
from sourced.world import VOICES  # noqa: E402

SCRIPT = ROOT / "scripts" / "regen_voices.sh"


# --- fakes -----------------------------------------------------------------

class FakeTensor:
    def __init__(self, a):
        self.a = a

    def squeeze(self, _):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.a


class FakeModel:
    sr = 24000
    loads = []

    def __init__(self):
        self.conds = None
        self.prepared = []
        self.calls = []

    @classmethod
    def from_local(cls, folder, device):
        cls.loads.append((Path(folder), device))
        cls.last = cls()
        return cls.last

    def prepare_conditionals(self, path, exaggeration):
        self.prepared.append(Path(path).stem)
        self.conds = ("conds", Path(path).stem)

    def generate(self, text, **params):
        self.calls.append((text, self.conds, params, FakeTorch.seed))
        rng = np.random.default_rng(FakeTorch.seed)  # output depends on the seed only
        return FakeTensor(rng.uniform(-0.5, 0.5, 2400).astype(np.float32))


class FakeTorch(types.ModuleType):
    seed = None
    threads = None

    def __init__(self):
        super().__init__("torch")
        self.backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: False))

    def manual_seed(self, s):
        FakeTorch.seed = s

    def set_num_threads(self, n):
        FakeTorch.threads = n


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    written = {}

    def sf_write(path, audio, sr, subtype):
        written[Path(path).name] = (np.array(audio), sr, subtype)
        Path(path).write_bytes(b"RIFF")

    perth = types.ModuleType("perth")
    perth.PerthImplicitWatermarker = type("PerthImplicitWatermarker", (), {})
    chatterbox = types.ModuleType("chatterbox")
    chatterbox_tts = types.ModuleType("chatterbox.tts")
    chatterbox_tts.ChatterboxTTS = FakeModel
    soundfile = types.ModuleType("soundfile")
    soundfile.write = sf_write
    for name, mod in {"torch": FakeTorch(), "perth": perth, "chatterbox": chatterbox,
                      "chatterbox.tts": chatterbox_tts, "soundfile": soundfile}.items():
        monkeypatch.setitem(sys.modules, name, mod)
    model_dir = tmp_path / "snapshot"
    model_dir.mkdir()
    monkeypatch.setattr(tw, "_chatterbox_dir", lambda local_only: model_dir)
    FakeModel.loads = []
    return types.SimpleNamespace(written=written, perth=perth, model_dir=model_dir, tmp=tmp_path)


def jobs_for(tmp, voices):
    return [{"text": f"Line {i}.", "voice": v, "out": str(tmp / f"D{i:04d}_voice.m4a"),
             "seed": f"1:D{i:04d}"} for i, v in enumerate(voices, 1)]


# --- pins ------------------------------------------------------------------

def test_slots_are_the_same_everywhere():
    assert VOICES == tw.SLOTS == list(tw.REFS) == list(tw.PIPER_VOICES)


def test_reference_clips_match_their_pins_and_refs_md():
    refs_md = (tw.REF_DIR / "REFS.md").read_text()
    for slot, digest in tw.REFS.items():
        clip = tw.REF_DIR / f"{slot}.wav"
        assert tw._sha256(clip) == digest
        assert f"`{slot}.wav`" in refs_md and digest in refs_md
    assert "librivox.org/pages/public-domain" in refs_md


def test_model_pins_are_full_hashes():
    assert len(tw.CHATTERBOX_REVISION) == 40
    assert all(len(d) == 64 for d in tw.CHATTERBOX_FILES.values())
    assert set(tw.CHATTERBOX_FILES) >= {"ve.safetensors", "t3_cfg.safetensors",
                                       "s3gen.safetensors", "tokenizer.json"}


# --- Chatterbox backend, mocked --------------------------------------------

def test_chatterbox_writes_every_job_with_progress(fakes, capsys):
    jobs = jobs_for(fakes.tmp, ["female_a", "male_b", "female_a"])
    tw.chatterbox_main(jobs, "cpu", 2)
    out = capsys.readouterr().out
    assert "clip 1/3" in out and "clip 3/3" in out and "peak RSS" in out
    m = FakeModel.last
    assert FakeModel.loads == [(fakes.model_dir, "cpu")]
    assert m.prepared == ["female_a", "male_b"]           # one conditioning per clip
    assert [c[1][1] for c in m.calls] == ["female_a", "male_b", "female_a"]
    assert all(c[2] == tw.CHATTERBOX_PARAMS for c in m.calls)
    assert [c[3] for c in m.calls] == [tw.job_seed(j["seed"]) % 2**31 for j in jobs]
    assert FakeTorch.threads == 2
    assert sorted(fakes.written) == [f"D000{i}_voice.wav" for i in (1, 2, 3)]
    audio, sr, subtype = fakes.written["D0001_voice.wav"]
    assert sr == 24000 and subtype == "PCM_16" and len(audio) > 2400  # lead-in added


def test_chatterbox_is_seeded_per_job(fakes):
    jobs = jobs_for(fakes.tmp, ["female_b", "female_b"])
    tw.chatterbox_main(jobs, "cpu", 1)
    first = {k: v[0].copy() for k, v in fakes.written.items()}
    tw.chatterbox_main(jobs, "cpu", 1)
    assert all(np.array_equal(first[k], fakes.written[k][0]) for k in first)
    assert not np.array_equal(first["D0001_voice.wav"][:2000], first["D0002_voice.wav"][:2000])


def test_chatterbox_refuses_without_watermarker(fakes):
    fakes.perth.PerthImplicitWatermarker = None
    with pytest.raises(SystemExit, match="watermark"):
        tw.chatterbox_main(jobs_for(fakes.tmp, ["male_a"]), "cpu", 1)
    assert FakeModel.loads == []


def test_chatterbox_refuses_a_tampered_model_file(monkeypatch, tmp_path):
    bad = tmp_path / "ve.safetensors"
    bad.write_bytes(b"not the model")
    hub = types.ModuleType("huggingface_hub")
    hub.hf_hub_download = lambda repo, name, revision, local_files_only: str(bad)
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    with pytest.raises(SystemExit, match="checksum mismatch"):
        tw._chatterbox_dir(local_only=True)


def test_chatterbox_pins_the_revision(monkeypatch, tmp_path):
    seen = []

    def download(repo, name, revision, local_files_only):
        seen.append((repo, revision, local_files_only))
        p = tmp_path / name
        p.write_bytes(b"x")
        return str(p)
    hub = types.ModuleType("huggingface_hub")
    hub.hf_hub_download = download
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setattr(tw, "_sha256", lambda p: tw.CHATTERBOX_FILES[Path(p).name])
    assert tw._chatterbox_dir(local_only=True) == tmp_path
    assert seen == [(tw.CHATTERBOX_REPO, tw.CHATTERBOX_REVISION, True)] * len(tw.CHATTERBOX_FILES)


def test_unknown_voice_is_refused(fakes):
    with pytest.raises(SystemExit, match="unknown voice"):
        tw.chatterbox_main(jobs_for(fakes.tmp, ["en_US-ljspeech-medium"]), "cpu", 1)


def test_cli_defaults_to_chatterbox_on_cpu(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(tw, "chatterbox_main", lambda j, d, t: seen.update(engine="c", device=d))
    monkeypatch.setattr(tw, "piper_main", lambda j: seen.update(engine="p"))
    f = tmp_path / "jobs.json"
    f.write_text("[]")
    tw.main([str(f)])
    assert seen == {"engine": "c", "device": "cpu"}
    tw.main(["--engine", "piper", str(f)])
    assert seen["engine"] == "p"


# --- generator side --------------------------------------------------------

def test_media_passes_engine_and_device(monkeypatch, tmp_path):
    from sourced import media

    calls = []

    def run(cmd, check):
        calls.append(cmd)
        if cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"m4a")
        else:
            for j in json.loads(Path(cmd[-1]).read_text()):
                Path(j["out"]).with_suffix(".wav").write_bytes(b"wav")
    monkeypatch.setattr(media.subprocess, "run", run)
    jobs = jobs_for(tmp_path, ["female_gb"])
    media.render_voices(jobs, "/venv/bin/python", tmp_path, engine="piper", device="mps")
    worker = calls[0]
    assert worker[1].endswith("tts_worker.py")
    assert worker[2:6] == ["--engine", "piper", "--device", "mps"]
    assert Path(jobs[0]["out"]).exists() and not Path(jobs[0]["out"]).with_suffix(".wav").exists()


# --- regen_voices.sh: never runs a model here ------------------------------

def run_script(env, *args):
    e = {**os.environ, **env}
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=e,
                          timeout=300)


def test_regen_refuses_when_memory_is_short():
    r = run_script({"SOURCED_MEM_FREE_PCT": "39", "TTS_PYTHON": "/nonexistent"})
    assert r.returncode == 3 and "refusing to start" in r.stderr


def test_regen_dry_run_states_the_command():
    r = run_script({"SOURCED_MEM_FREE_PCT": "90", "TTS_PYTHON": "/nonexistent"}, "--dry-run")
    assert r.returncode == 0
    assert "--seed 1 --days 14 --facts 30 --changes 4" in r.stdout
    assert "--tts-engine chatterbox" in r.stdout and "HF_HUB_OFFLINE=1" in r.stdout


FAKE_WORKER = '''
import json, math, struct, sys, wave
from pathlib import Path
args = [a for a in sys.argv[1:] if a != "-I"]
if "--check" in args:
    print("ok fake"); sys.exit()
jobs = json.loads(Path(args[-1]).read_text())
for i, j in enumerate(jobs, 1):
    with wave.open(str(Path(j["out"]).with_suffix(".wav")), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(k / 9)))
                               for k in range(4800)))
    print(f"clip {i}/{len(jobs)} fake", flush=True)
print("done", flush=True)
'''


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg needed")
def test_regen_end_to_end_with_a_fake_tts(tmp_path):
    """The whole script on a copy of the benchmark, with a TTS that writes a
    tone: checks the non-audio comparison and the copy of the 7 clips."""
    pytest.importorskip("PIL")
    bench = tmp_path / "sourced-bench"
    shutil.copytree(ROOT, bench, ignore=shutil.ignore_patterns("__pycache__", "results", "runs"))
    worker = tmp_path / "fake_worker.py"
    worker.write_text(FAKE_WORKER)
    fake_py = tmp_path / "fake-python"
    fake_py.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{worker}" "$@"\n')
    fake_py.chmod(0o755)
    before = {p.name: p.read_bytes() for p in (bench / "sample" / "deposits").iterdir()}
    r = subprocess.run(["bash", str(bench / "scripts" / "regen_voices.sh")], capture_output=True,
                       text=True, timeout=300,
                       env={**os.environ, "SOURCED_MEM_FREE_PCT": "90", "TTS_PYTHON": str(fake_py),
                            "PYTHON": sys.executable, "SOURCED_CHATTERBOX_HOME": str(tmp_path)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "clip 7/7" in r.stdout and "done: 7 voice clips" in r.stdout
    after = {p.name: p.read_bytes() for p in (bench / "sample" / "deposits").iterdir()}
    changed = sorted(n for n in before if before[n] != after[n])
    assert len(changed) == 7 and all(n.endswith(".m4a") for n in changed)
    manifest = json.loads((bench / "sample" / "manifest.json").read_text())
    assert manifest["audio"].startswith("chatterbox-tts 0.1.7")
