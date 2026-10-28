"""Transcription engine choice: same timestamped-words sidecar whatever
the engine, and the server's historical setting (WhisperX, large-v3,
cpu, int8) holds when nothing is specified."""

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))
import media_pipeline  # noqa: E402

from pensine import config  # noqa: E402


@pytest.fixture
def clean(monkeypatch):
    for k in ("TRANSCRIBE_BACKEND", "WHISPER_MODEL", "WHISPER_DEVICE",
              "WHISPER_COMPUTE_TYPE"):
        monkeypatch.setattr(config, k, "")
    monkeypatch.setattr(config, "TRANSCRIBE_LANGUAGE", None)
    # no GPU in tests, whatever the host
    monkeypatch.setitem(sys.modules, "ctranslate2",
                        types.SimpleNamespace(get_cuda_device_count=lambda: 0))
    return monkeypatch


def test_choix_explicite(clean):
    clean.setattr(config, "TRANSCRIBE_BACKEND", "none")
    assert media_pipeline.transcribe_backend() == "none"


def test_auto_prefere_whisperx(clean):
    import importlib.util
    clean.setattr(importlib.util, "find_spec",
                  lambda name: object() if name in ("whisperx", "faster_whisper") else None)
    assert media_pipeline.transcribe_backend() == "whisperx"


def test_auto_rien_d_installe(clean):
    import importlib.util
    clean.setattr(importlib.util, "find_spec", lambda name: None)
    assert media_pipeline.transcribe_backend() == "none"


def test_reglage_historique_whisperx_sans_gpu(clean):
    assert media_pipeline.whisper_settings("whisperx") == ("large-v3", "cpu", "int8")


def test_gpu_detecte(clean):
    clean.setitem(sys.modules, "ctranslate2",
                  types.SimpleNamespace(get_cuda_device_count=lambda: 1))
    assert media_pipeline.whisper_settings("faster-whisper") == ("large-v3", "cuda", "float16")


def test_reglages_explicites_gagnent(clean):
    clean.setattr(config, "WHISPER_MODEL", "small")
    clean.setattr(config, "WHISPER_DEVICE", "cpu")
    clean.setattr(config, "WHISPER_COMPUTE_TYPE", "float32")
    assert media_pipeline.whisper_settings("whisperx") == ("small", "cpu", "float32")


def test_none_refuse_et_ne_cree_rien(clean, tmp_path):
    clean.setattr(config, "TRANSCRIBE_BACKEND", "none")
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="disabled"):
        media_pipeline.transcribe(audio)
    assert not (tmp_path / "a.m4a.whisperx.json").exists()


def test_whisperx_garde_l_alignement(clean, tmp_path):
    seen = {}

    class Model:
        def transcribe(self, audio, language=None):
            return {"language": "fr", "segments": [{"text": " brut "}]}

    fake = types.SimpleNamespace(
        load_model=lambda name, device, compute_type: seen.update(
            model=(name, device, compute_type)) or Model(),
        load_audio=lambda p: [0.0] * 32000,
        load_align_model=lambda language_code, device: ("align", {"lang": language_code}),
        align=lambda segs, m, meta, audio, device: seen.update(aligned=True) or {
            "segments": [{"start": 0.0, "end": 1.2, "text": " Bonjour Camille ",
                          "words": [{"word": "Bonjour", "start": 0.0, "end": 0.5},
                                    {"word": "Camille", "start": 0.6, "end": 1.2}]}]},
    )
    clean.setitem(sys.modules, "whisperx", fake)
    clean.setitem(sys.modules, "torch", types.SimpleNamespace(load=lambda *a, **k: None))
    clean.setattr(config, "TRANSCRIBE_BACKEND", "whisperx")
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"x")
    assert media_pipeline.transcribe(audio) == ("Bonjour Camille", 2)
    assert seen["model"] == ("large-v3", "cpu", "int8") and seen["aligned"]
    side = json.loads((tmp_path / "a.m4a.whisperx.json").read_text())
    assert side["language"] == "fr" and side["segments"][0]["words"][1]["word"] == "Camille"


def test_faster_whisper_meme_sidecar(clean, tmp_path):
    from pensine import cards

    W = types.SimpleNamespace
    seen = {}

    class WhisperModel:
        def __init__(self, name, device, compute_type):
            seen["model"] = (name, device, compute_type)

        def transcribe(self, path, language=None, word_timestamps=False, vad_filter=False):
            seen["words"] = word_timestamps
            seg = W(start=0.0, end=1.0, text=" Salut ",
                    words=[W(word=" Salut", start=0.1, end=0.9, probability=0.98)])
            return iter([seg]), W(language="fr", duration=1.4)

    clean.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=WhisperModel))
    clean.setattr(config, "TRANSCRIBE_BACKEND", "faster-whisper")
    clean.setattr(config, "MEDIA_ROOT", tmp_path)
    audio = tmp_path / "b.m4a"
    audio.write_bytes(b"x")
    assert media_pipeline.transcribe(audio) == ("Salut", 1)
    assert seen["model"] == ("large-v3-turbo", "cpu", "int8") and seen["words"]
    # the word-by-word re-dive reads this sidecar like WhisperX's
    assert cards.words("b.m4a") == [{"w": "Salut", "s": 0.1, "e": 0.9}]


def test_mlx_whisper_meme_sidecar(clean, tmp_path):
    seen = {}

    def transcribe(path, path_or_hf_repo, word_timestamps, language):
        seen["repo"] = path_or_hf_repo
        return {"language": "en", "segments": [
            {"start": 0.0, "end": 2.5, "text": " Hello ",
             "words": [{"word": " Hello", "start": 0.2, "end": 0.7, "probability": 0.9}]}]}

    clean.setitem(sys.modules, "mlx_whisper", types.SimpleNamespace(transcribe=transcribe))
    clean.setattr(config, "TRANSCRIBE_BACKEND", "mlx-whisper")
    audio = tmp_path / "c.m4a"
    audio.write_bytes(b"x")
    assert media_pipeline.transcribe(audio) == ("Hello", 2)
    assert seen["repo"] == "mlx-community/whisper-large-v3-turbo"
    side = json.loads((tmp_path / "c.m4a.whisperx.json").read_text())
    assert side["segments"][0]["words"][0] == {"word": "Hello", "start": 0.2,
                                               "end": 0.7, "score": 0.9}


def test_sans_moteur_les_vocaux_ne_bloquent_pas_le_lot(clean):
    clean.setattr(config, "TRANSCRIBE_BACKEND", "none")
    seen = {}

    class Conn:
        def execute(self, sql, *a):
            seen["sql"] = sql
            return types.SimpleNamespace(fetchall=lambda: [])

    media_pipeline.process_pending(Conn())
    assert "kind IN ('audio','video')" not in seen["sql"]
    assert "kind = 'photo'" in seen["sql"]
