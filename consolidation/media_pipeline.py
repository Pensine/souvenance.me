"""Pipeline média nocturne (couche 6, annexe C) — le retraitement intelligent.

Traite les médias en attente : audio/vidéo → WhisperX, photos → EXIF + vision,
PDF → Docling. Le fichier original n'est JAMAIS modifié — on n'écrit que les
fiches de catalogue (transcript, description, exif) accrochées au fichier.

Chaque brique dégrade proprement : si WhisperX/PIL/Docling/ffmpeg manque ou
casse, le média reste en attente et sera repris au cycle suivant. Pause,
jamais perte.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import config, db, llm  # noqa: E402

import contextlib


@contextlib.contextmanager
def _trusted_torch_load():
    """torch >= 2.6 refuse par défaut les checkpoints picklés à l'ancienne
    (weights_only=True) ; le modèle VAD embarqué par WhisperX en est un.
    On ne relâche cette protection QUE pour ce chargement-là : le checkpoint
    vient de la distribution WhisperX, pas d'une entrée utilisateur."""
    import torch

    original = torch.load

    def _forced(*args, **kwargs):
        # les couches intermédiaires (Lightning) passent weights_only=True
        # explicitement : un simple défaut par functools.partial serait écrasé
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
    """Traite tous les médias sans transcript/description. Retourne un bilan."""
    done, skipped = [], []
    rows = conn.execute(
        """
        SELECT id, kind, storage_path FROM media
        WHERE (kind IN ('audio','video') AND transcript IS NULL)
           OR (kind = 'photo' AND description IS NULL)
           OR (kind = 'pdf' AND transcript IS NULL)
        ORDER BY id LIMIT 50
        """
    ).fetchall()

    for row in rows:
        path = config.MEDIA_ROOT / row["storage_path"]
        if not path.exists():
            skipped.append((row["id"], "fichier absent"))
            continue
        try:
            handler = {"audio": _audio, "video": _video,
                       "photo": _photo, "pdf": _pdf}[row["kind"]]
            handler(conn, row["id"], path)
            done.append(row["id"])
        except Exception as exc:  # dégradation propre : repris au cycle suivant
            skipped.append((row["id"], f"{type(exc).__name__}: {exc}"))

    for media_id, reason in skipped:
        db.audit(conn, "consolidation", "media_skip",
                 {"media_id": media_id, "reason": str(reason)[:300]})
    return {"done": done, "skipped": skipped, "pending": len(rows)}


# -- Audio ---------------------------------------------------------------------

def _audio(conn, media_id: int, path: Path) -> None:
    transcript, duration = transcribe(path)
    speakers = _identify_speakers(conn, media_id, path)
    conn.execute(
        "UPDATE media SET transcript = %s, duration_s = COALESCE(duration_s, %s), "
        "speakers = COALESCE(%s, speakers) WHERE id = %s",
        (transcript, duration,
         json.dumps(speakers, ensure_ascii=False) if speakers else None, media_id),
    )


def _identify_speakers(conn, media_id: int, path: Path) -> list[dict] | None:
    """Diarisation + empreintes (phase 2). L'expéditeur du canal (event de
    dépôt) prime sur le ML — règle des tiers. Dégrade en None sans pyannote."""
    from pensine import speakers as spk
    from pensine.graph import upsert_entity

    sender_entity_id = None
    row = conn.execute(
        "SELECT payload->>'sender' AS sender FROM events "
        "WHERE media_id = %s AND kind = 'deposit' LIMIT 1", (media_id,)
    ).fetchone()
    if row and row["sender"]:
        sender_entity_id = upsert_entity(conn, row["sender"], "person")
    try:
        return spk.identify_segments(conn, path, sender_entity_id=sender_entity_id)
    except Exception:
        return None  # brique absente ou modèle non téléchargé : pause, pas perte


def transcribe(path: Path) -> tuple[str, int | None]:
    """WhisperX — transcript aligné. Le JSON complet (mots horodatés) est gardé
    à côté du fichier (même dossier, .whisperx.json) pour la replongée fine."""
    import whisperx  # import lourd, différé — ImportError = brique absente

    device = "cpu"
    # le contexte couvre TOUT le pipeline : le VAD de WhisperX charge son
    # checkpoint paresseusement, pendant transcribe(), pas à load_model()
    with _trusted_torch_load():
        model = whisperx.load_model("large-v3", device, compute_type="int8")
        audio = whisperx.load_audio(str(path))
        result = model.transcribe(audio, language="fr")
        align_model, metadata = whisperx.load_align_model(
            language_code=result["language"], device=device)
        aligned = whisperx.align(result["segments"], align_model, metadata,
                                 audio, device)
    sidecar = path.with_suffix(path.suffix + ".whisperx.json")
    sidecar.write_text(json.dumps(aligned, ensure_ascii=False), encoding="utf-8")
    text = " ".join(s["text"].strip() for s in aligned["segments"])
    duration = int(len(audio) / 16000) if len(audio) else None
    return text, duration


# -- Vidéo ---------------------------------------------------------------------

def _video(conn, media_id: int, path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        _ffmpeg("-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(wav))
        transcript, duration = transcribe(wav)

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


def extract_exif(path: Path) -> dict | None:
    """Date et GPS via PIL (brique optionnelle)."""
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
    from docling.document_converter import DocumentConverter  # brique optionnelle

    result = DocumentConverter().convert(str(path))
    text = result.document.export_to_markdown()
    conn.execute("UPDATE media SET transcript = %s WHERE id = %s",
                 (text[:100_000], media_id))
