"""Endpoint Pensine (annexe C) — un POST unique, authentifié par token.

Raccourci iOS « Twin » (share sheet universelle) → ce endpoint → stockage
(fichier original conservé tel quel, pour toujours) + event.
Le retraitement intelligent (WhisperX, vision, EXIF) est nocturne.

Sert aussi les liens médias signés temporaires de la replongée
(`recall(depth=source)` → /media/<token>).

Deux taps entre « ce vocal compte » et « c'est dans la Pensine ».
"""

import hashlib
import hmac
import mimetypes
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from . import config, db

app = FastAPI(title="Pensine", docs_url=None, redoc_url=None)

from .webapp import router as webapp_router  # noqa: E402
app.include_router(webapp_router)

KIND_BY_TYPE = {"audio": "audio", "image": "photo", "video": "video",
                "application/pdf": "pdf"}


def _kind(content_type: str | None, filename: str) -> str:
    ct = content_type or mimetypes.guess_type(filename)[0] or ""
    if ct == "application/pdf":
        return "pdf"
    return KIND_BY_TYPE.get(ct.split("/")[0], "pdf" if filename.endswith(".pdf") else "audio")


def _check_token(authorization: str | None) -> None:
    if not config.PENSINE_TOKEN:
        raise HTTPException(503, "PENSINE_DEPOSIT_TOKEN non configuré")
    provided = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(provided, config.PENSINE_TOKEN):
        raise HTTPException(401, "token invalide")


@app.post("/deposit")
async def deposit(
    file: UploadFile = File(...),
    note: str = Form(""),
    captured_at: str = Form(""),   # ISO 8601 si le raccourci la fournit
    sender: str = Form(""),        # métadonnée du canal (vocal WhatsApp transféré)
    authorization: str | None = Header(None),
):
    """Dépôt Pensine : geste délibéré uniquement (jamais de surveillance ambiante)."""
    _check_token(authorization)

    when = (datetime.fromisoformat(captured_at) if captured_at
            else datetime.now(timezone.utc))
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    raw = await file.read()
    kind = _kind(file.content_type, file.filename or "")
    digest = hashlib.sha256(raw).hexdigest()

    # Stockage : année/mois/hash.ext — le fichier original, jamais modifié
    ext = Path(file.filename or "").suffix or {"audio": ".opus", "photo": ".jpg",
                                               "video": ".mp4", "pdf": ".pdf"}[kind]
    rel = Path(f"{when:%Y/%m}") / f"{digest[:16]}{ext}"
    dest = config.MEDIA_ROOT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_bytes(raw)

    with db.connection() as conn:
        media_id = db.insert_media(conn, captured_at=when, kind=kind,
                                   storage_path=str(rel))
        event_id = db.append_event(
            conn, source="pensieve", kind="deposit", occurred_at=when,
            payload={"note": note, "sender": sender, "filename": file.filename,
                     "sha256": digest, "kind": kind},
            media_id=media_id,
        )
        db.audit(conn, "mcp", "pensieve_deposit",
                 {"media_id": media_id, "event_id": event_id, "kind": kind})
        conn.commit()

    return {"ok": True, "media_id": media_id, "event_id": event_id, "kind": kind}


@app.post("/log")
async def daily_log_gesture(
    text: str = Form(""),
    file: UploadFile | None = File(None),
    authorization: str | None = Header(None),
):
    """Le log de bord en un geste : raccourci iOS « Log » → on dicte, c'est
    tout. Texte (transcrit par iOS) ou audio brut — l'audio est transcrit
    par le cycle nocturne, puis consolidé comme un log de bord normal."""
    _check_token(authorization)
    when = datetime.now(timezone.utc)

    if file is not None:
        raw = await file.read()
        digest = hashlib.sha256(raw).hexdigest()
        ext = Path(file.filename or "").suffix or ".m4a"
        rel = Path(f"{when:%Y/%m}") / f"log-{digest[:16]}{ext}"
        dest = config.MEDIA_ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(raw)
        with db.connection() as conn:
            media_id = db.insert_media(conn, captured_at=when, kind="audio",
                                       storage_path=str(rel))
            event_id = db.append_event(
                conn, source="daily_log", kind="daily_log_voice",
                occurred_at=when,
                payload={"sha256": digest, "note": "log de bord vocal"},
                media_id=media_id,
            )
            db.audit(conn, "mcp", "daily_log_voice",
                     {"media_id": media_id, "event_id": event_id})
            conn.commit()
        return {"ok": True, "event_id": event_id,
                "note": "transcrit cette nuit, consolidé ensuite"}

    if not text.strip():
        raise HTTPException(422, "ni texte ni fichier audio")
    with db.connection() as conn:
        event_id = db.append_event(
            conn, source="daily_log", kind="daily_log",
            occurred_at=when, payload={"transcript": text},
        )
        db.audit(conn, "mcp", "daily_log_gesture", {"event_id": event_id})
        conn.commit()
    return {"ok": True, "event_id": event_id}


@app.get("/media/{token}")
def media(token: str):
    """Replongée : lien signé temporaire vers le fichier original."""
    if not config.MEDIA_LINK_SECRET:
        raise HTTPException(503, "PENSINE_MEDIA_LINK_SECRET non configuré")
    signer = TimestampSigner(config.MEDIA_LINK_SECRET)
    try:
        media_id = int(signer.unsign(token, max_age=config.MEDIA_LINK_TTL_S))
    except (SignatureExpired, BadSignature, ValueError):
        raise HTTPException(403, "lien expiré ou invalide")

    with db.connection() as conn:
        row = conn.execute("SELECT storage_path, kind FROM media WHERE id = %s",
                           (media_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    path = config.MEDIA_ROOT / row["storage_path"]
    if not path.exists():
        raise HTTPException(410, "fichier absent du stockage")
    return FileResponse(path)
