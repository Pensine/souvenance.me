"""Nightly media pipeline (layer 6, appendix C) — the intelligent reprocessing.

Processes pending media: audio/video → Whisper (WhisperX, faster-whisper
or mlx-whisper), photos → EXIF + vision,
PDF → Docling. The original file is NEVER modified — we only write the
catalogue records (transcript, description, exif) attached to the file.

Each component degrades cleanly: if WhisperX/PIL/Docling/ffmpeg is missing or
breaks, the media stays pending and is picked up again on the next cycle.
Pause, never loss.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import config, db, llm, places, shred  # noqa: E402

import contextlib


@contextlib.contextmanager
def _trusted_torch_load():
    """torch >= 2.6 refuses old-style pickled checkpoints by default
    (weights_only=True); the VAD model bundled with WhisperX is one.
    We relax this protection ONLY for that load: the checkpoint comes from
    the WhisperX distribution, not from user input."""
    import torch

    original = torch.load

    def _forced(*args, **kwargs):
        # the intermediate layers (Lightning) pass weights_only=True
        # explicitly: a plain default via functools.partial would be overridden
        kwargs["weights_only"] = False
        return original(*args, **kwargs)

    torch.load = _forced
    try:
        yield
    finally:
        torch.load = original


VISION_PROMPT = (
    "Décris cette image factuellement pour l'index d'une mémoire personnelle : "
    "qui/quoi (sans deviner les identités), où (si visible), ambiance, texte "
    "lisible. 3 phrases maximum, en français. Aucun jugement."
)


def process_pending(conn) -> dict:
    """Process all media without transcript/description. Returns a report."""
    done, skipped = [], []
    # without a transcription engine, voice notes and videos wait without
    # occupying the batch: the photos and PDFs behind them still go through
    sound = "kind IN ('audio','video')" if transcribe_backend() != "none" else "FALSE"
    rows = conn.execute(
        f"""
        SELECT id, kind, storage_path FROM media
        WHERE ({sound} AND transcript IS NULL)
           OR (kind = 'photo' AND description IS NULL)
           OR (kind = 'pdf' AND transcript IS NULL)
        ORDER BY id LIMIT 50
        """
    ).fetchall()

    for row in rows:
        path = config.MEDIA_ROOT / row["storage_path"]
        if not path.exists():
            skipped.append((row["id"], "file missing"))
            continue
        try:
            handler = {"audio": _audio, "video": _video,
                       "photo": _photo, "pdf": _pdf}[row["kind"]]
            handler(conn, row["id"], path)
            done.append(row["id"])
        except Exception as exc:  # clean degradation: picked up again next cycle
            skipped.append((row["id"], f"{type(exc).__name__}: {exc}"))

    for media_id, reason in skipped:
        db.audit(conn, "consolidation", "media_skip",
                 {"media_id": media_id, "reason": str(reason)[:300]})
    return {"done": done, "skipped": skipped, "pending": len(rows)}


def locate(conn) -> int:
    """Name the places of media, locally (GeoNames), and recover the Voice
    Memos addresses of memos already deposited. Rerunnable: only touches
    what does not have a name yet."""
    named = 0
    for r in conn.execute(
        "SELECT id, lat, lon FROM media WHERE lat IS NOT NULL AND place IS NULL"
    ).fetchall():
        name = places.label(r["lat"], r["lon"])
        if name:
            conn.execute("UPDATE media SET place = %s WHERE id = %s", (name, r["id"]))
            named += 1
    for r in conn.execute(
        """SELECT m.id, e.payload FROM media m
           JOIN events e ON e.media_id = m.id
           WHERE m.kind = 'audio' AND m.place IS NULL AND m.lat IS NULL"""
    ).fetchall():
        # payload opened in Python: a sealed deposit has no readable field in SQL
        name = places.from_filename((shred.open_payload(r["payload"]) or {}).get("filename"))
        if name:
            conn.execute("UPDATE media SET place = %s, place_source = 'nom_dictaphone' "
                         "WHERE id = %s", (name, r["id"]))
            named += 1
    # memories without a place inherit that of their first located media
    # (catches up memories written before places existed)
    named += conn.execute(
        """
        UPDATE memories mm SET lat = src.lat, lon = src.lon, place = src.place,
                               place_source = src.place_source
        FROM (
            SELECT DISTINCT ON (mm2.id) mm2.id, m.lat, m.lon, m.place, m.place_source
            FROM memories mm2
            JOIN events e ON e.id = ANY(mm2.source_event_ids)
            JOIN media m ON m.id = e.media_id
            WHERE mm2.place IS NULL AND mm2.lat IS NULL
              AND (m.place IS NOT NULL OR m.lat IS NOT NULL)
            ORDER BY mm2.id, e.id
        ) src
        WHERE mm.id = src.id
        """
    ).rowcount
    return named


# -- Audio ---------------------------------------------------------------------

# One transcription per process: WhisperX (large-v3) and its alignment model
# take several GB, which torch does not always give back to the system.
# Three memos in the same process were enough, on 24 October 2026, to climb
# to 6.6 GB and get killed by the kernel — on a shared server.
# A child process per file returns all its memory when it exits.
TRANSCRIBE_TIMEOUT_S = 3600


def transcribe_isolated(path: Path) -> tuple[str, int | None]:
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--transcribe", str(path)],
        capture_output=True, text=True, timeout=TRANSCRIBE_TIMEOUT_S,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise RuntimeError(f"transcription failed ({proc.returncode}): {' | '.join(tail)}")
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    return out["text"], out["duration"]


def _audio(conn, media_id: int, path: Path) -> None:
    transcript, duration = transcribe_isolated(path)
    speakers = _identify_speakers(conn, media_id, path)
    conn.execute(
        "UPDATE media SET transcript = %s, duration_s = COALESCE(duration_s, %s), "
        "speakers = COALESCE(%s, speakers) WHERE id = %s",
        (transcript, duration,
         json.dumps(speakers, ensure_ascii=False) if speakers else None, media_id),
    )


def _identify_speakers(conn, media_id: int, path: Path) -> list[dict] | None:
    """Diarization + voiceprints (phase 2). The channel sender (deposit
    event) takes precedence over ML — third-party rule. Degrades to None
    without pyannote."""
    from pensine import speakers as spk
    from pensine.graph import upsert_entity

    sender_entity_id = None
    row = conn.execute(
        "SELECT payload FROM events "
        "WHERE media_id = %s AND kind = 'deposit' LIMIT 1", (media_id,)
    ).fetchone()
    sender = (shred.open_payload(row["payload"]) or {}).get("sender") if row else None
    if sender:
        sender_entity_id = upsert_entity(conn, sender, "person")
    try:
        return spk.identify_segments(conn, path, sender_entity_id=sender_entity_id)
    except Exception:
        return None  # component missing or model not downloaded: pause, not loss


TRANSCRIBE_BACKENDS = ("whisperx", "faster-whisper", "mlx-whisper", "none")
_MODULES = {"whisperx": "whisperx", "faster-whisper": "faster_whisper",
            "mlx-whisper": "mlx_whisper"}


def transcribe_backend() -> str:
    """The chosen engine (PENSINE_TRANSCRIBE_BACKEND), otherwise the first
    one installed: WhisperX (finest word-level alignment), mlx-whisper on
    Apple Silicon Macs, faster-whisper elsewhere; "none" if none."""
    import importlib.util
    import platform

    if config.TRANSCRIBE_BACKEND:
        return config.TRANSCRIBE_BACKEND
    order = ["whisperx", "faster-whisper"]
    if sys.platform == "darwin" and platform.machine() == "arm64":
        order.insert(1, "mlx-whisper")
    for name in order:
        if importlib.util.find_spec(_MODULES[name]) is not None:
            return name
    return "none"


def whisper_device() -> str:
    """cuda if an NVIDIA GPU responds (ctranslate2 serves WhisperX as well as
    faster-whisper, and can be queried without loading torch), otherwise cpu."""
    if config.WHISPER_DEVICE:
        return config.WHISPER_DEVICE
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def whisper_settings(backend: str) -> tuple[str, str, str]:
    """(model, device, precision). WhisperX without GPU: large-v3 / cpu /
    int8, the server's historical setting. faster-whisper without GPU takes
    large-v3-turbo, almost as accurate and several times faster."""
    device = whisper_device()
    gpu = device == "cuda"
    defaults = {"whisperx": "large-v3",
                "faster-whisper": "large-v3" if gpu else "large-v3-turbo",
                "mlx-whisper": "mlx-community/whisper-large-v3-turbo"}
    model = config.WHISPER_MODEL or defaults.get(backend, "large-v3")
    compute = config.WHISPER_COMPUTE_TYPE or ("float16" if gpu else "int8")
    return model, device, compute


def transcribe(path: Path) -> tuple[str, int | None]:
    """Transcript, and next to the file (same folder, .whisperx.json) the
    timestamped words for fine-grained re-diving — same shape whichever
    engine: {"segments": [{start, end, text, words: [{word, start, end}]}]}."""
    backend = transcribe_backend()
    if backend == "whisperx":
        aligned, duration = _whisperx(path)
    elif backend == "faster-whisper":
        aligned, duration = _faster_whisper(path)
    elif backend == "mlx-whisper":
        aligned, duration = _mlx_whisper(path)
    elif backend == "none":
        raise RuntimeError("transcription disabled (PENSINE_TRANSCRIBE_BACKEND=none "
                           "or no engine installed)")
    else:
        raise RuntimeError(f"unknown transcription engine: {backend} "
                           f"(expected: {', '.join(TRANSCRIBE_BACKENDS)})")
    sidecar = path.with_suffix(path.suffix + ".whisperx.json")
    sidecar.write_text(json.dumps(aligned, ensure_ascii=False), encoding="utf-8")
    text = " ".join(s["text"].strip() for s in aligned["segments"])
    return text, duration


def _whisperx(path: Path) -> tuple[dict, int | None]:
    """WhisperX — transcript, then forced alignment (fine timestamped words)."""
    import whisperx  # heavy import, deferred — ImportError = component missing

    name, device, compute = whisper_settings("whisperx")
    # the context covers the WHOLE pipeline: WhisperX's VAD loads its
    # checkpoint lazily, during transcribe(), not at load_model()
    with _trusted_torch_load():
        model = whisperx.load_model(name, device, compute_type=compute)
        audio = whisperx.load_audio(str(path))
        # detected on the first 30 seconds, unless a language is forced
        result = model.transcribe(audio, language=config.TRANSCRIBE_LANGUAGE)
        align_model, metadata = whisperx.load_align_model(
            language_code=result["language"], device=device)
        aligned = whisperx.align(result["segments"], align_model, metadata,
                                 audio, device)
    aligned["language"] = result["language"]
    duration = int(len(audio) / 16000) if len(audio) else None
    return aligned, duration


def _faster_whisper(path: Path) -> tuple[dict, int | None]:
    """faster-whisper — no torch; word timestamps from the decoder."""
    from faster_whisper import WhisperModel

    name, device, compute = whisper_settings("faster-whisper")
    model = WhisperModel(name, device=device, compute_type=compute)
    segments, info = model.transcribe(str(path), language=config.TRANSCRIBE_LANGUAGE,
                                      word_timestamps=True, vad_filter=True)
    segs = [{"start": s.start, "end": s.end, "text": s.text,
             "words": [{"word": w.word.strip(), "start": w.start, "end": w.end,
                        "score": w.probability} for w in (s.words or [])]}
            for s in segments]
    duration = int(info.duration) if getattr(info, "duration", None) else None
    return {"segments": segs, "language": info.language}, duration


def _mlx_whisper(path: Path) -> tuple[dict, int | None]:
    """mlx-whisper — Whisper on the GPU of Apple Silicon Macs."""
    import mlx_whisper

    name, _device, _compute = whisper_settings("mlx-whisper")
    result = mlx_whisper.transcribe(str(path), path_or_hf_repo=name,
                                    word_timestamps=True,
                                    language=config.TRANSCRIBE_LANGUAGE)
    segs = [{"start": s["start"], "end": s["end"], "text": s["text"],
             "words": [{"word": w["word"].strip(), "start": w["start"], "end": w["end"],
                        "score": w.get("probability")} for w in s.get("words") or []]}
            for s in result.get("segments") or []]
    duration = int(segs[-1]["end"]) if segs else None
    return {"segments": segs, "language": result.get("language")}, duration


# -- Video ---------------------------------------------------------------------

def _video(conn, media_id: int, path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        _ffmpeg("-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(wav))
        transcript, duration = transcribe_isolated(wav)

        keyframe = Path(tmp) / "frame.jpg"
        _ffmpeg("-i", str(path), "-vf", "thumbnail", "-frames:v", "1", str(keyframe))
        description = llm.describe_image(keyframe, prompt=VISION_PROMPT)

    conn.execute(
        "UPDATE media SET transcript = %s, description = %s, "
        "duration_s = COALESCE(duration_s, %s) WHERE id = %s",
        (transcript, description, duration, media_id),
    )


def _ffmpeg(*args: str) -> None:
    proc = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args],
                          capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg : {proc.stderr[:300]}")


# -- Photo ---------------------------------------------------------------------

def _photo(conn, media_id: int, path: Path) -> None:
    exif = extract_exif(path)
    description = llm.describe_image(path, prompt=VISION_PROMPT)
    conn.execute(
        "UPDATE media SET description = %s, exif = COALESCE(exif, %s) WHERE id = %s",
        (description, json.dumps(exif, ensure_ascii=False) if exif else None, media_id),
    )
    if exif and places.valid(exif.get("lat"), exif.get("lon")):
        # the photo's GPS wins over nothing, never over a sent position
        conn.execute(
            "UPDATE media SET lat = %s, lon = %s, place_source = 'gps_photo' "
            "WHERE id = %s AND lat IS NULL",
            (exif["lat"], exif["lon"], media_id),
        )


def extract_exif(path: Path) -> dict | None:
    """Date and GPS via PIL (optional component)."""
    try:
        from PIL import ExifTags, Image
    except ImportError:
        return None
    try:
        img = Image.open(path)
        raw = img.getexif()
    except Exception:
        return None
    if not raw:
        return None
    out = {}
    tags = {ExifTags.TAGS.get(k): v for k, v in raw.items()}
    if tags.get("DateTimeOriginal") or tags.get("DateTime"):
        out["datetime"] = str(tags.get("DateTimeOriginal") or tags.get("DateTime"))
    gps_ifd = raw.get_ifd(ExifTags.IFD.GPSInfo) if hasattr(ExifTags, "IFD") else None
    if gps_ifd:
        gps = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
        lat, lon = gps.get("GPSLatitude"), gps.get("GPSLongitude")
        if lat and lon:
            def to_deg(v):
                return float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
            out["lat"] = round(to_deg(lat) * (-1 if gps.get("GPSLatitudeRef") == "S" else 1), 6)
            out["lon"] = round(to_deg(lon) * (-1 if gps.get("GPSLongitudeRef") == "W" else 1), 6)
    return out or None


# -- PDF -----------------------------------------------------------------------

def _pdf(conn, media_id: int, path: Path) -> None:
    from docling.document_converter import DocumentConverter  # optional component

    result = DocumentConverter().convert(str(path))
    text = result.document.export_to_markdown()
    conn.execute("UPDATE media SET transcript = %s WHERE id = %s",
                 (text[:100_000], media_id))


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "--transcribe":
    # child process: one transcription, then the memory is returned to the system
    _text, _duration = transcribe(Path(sys.argv[2]))
    print(json.dumps({"text": _text, "duration": _duration}, ensure_ascii=False))
