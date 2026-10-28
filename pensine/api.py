"""Pensine endpoint (appendix C) — a single POST, authenticated by token.

iOS "Twin" shortcut (universal share sheet) → this endpoint → storage
(original file kept as is, forever) + event.
The smart reprocessing (WhisperX, vision, EXIF) runs at night.

Also serves the temporary signed media links used to dive back in
(`recall(depth=source)` → /media/<token>).

Two taps between "this voice memo matters" and "it is in the Pensine".
"""

import hashlib
import hmac
import mimetypes
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from . import config, db, places, shred

app = FastAPI(title="Pensine", docs_url=None, redoc_url=None)

from .webapp import router as webapp_router  # noqa: E402
app.include_router(webapp_router)

KIND_BY_TYPE = {"audio": "audio", "image": "photo", "video": "video",
                "application/pdf": "pdf"}


TEXT_TYPES = {"application/json", "application/xml", "application/x-yaml",
              "application/yaml"}
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml"}
GENERIC_TYPES = {"", "application/octet-stream", "binary/octet-stream"}


def _kind(content_type: str | None, filename: str) -> str:
    """The kind of the deposit. A text is a text, no longer an "audio" waiting
    for an impossible transcription; an unknown file is archived as is
    ("file"). Only a deposit with no clue at all (generic type, no name or
    telling extension) stays "audio": that is what the iOS shortcut sends
    for a voice memo."""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in GENERIC_TYPES:
        ct = (mimetypes.guess_type(filename)[0] or "").lower()
        if not ct and Path(filename).suffix.lower() in TEXT_SUFFIXES:
            ct = "text/plain"  # the mimetypes table varies from one system to another
    if not ct:
        return "pdf" if filename.lower().endswith(".pdf") else \
            ("file" if Path(filename).suffix else "audio")
    if ct == "application/pdf":
        return "pdf"
    if ct.startswith("text/") or ct in TEXT_TYPES:
        return "text"
    return KIND_BY_TYPE.get(ct.split("/")[0], "file")


def _check_token(authorization: str | None) -> None:
    if not config.PENSINE_TOKEN:
        raise HTTPException(503, "PENSINE_DEPOSIT_TOKEN not configured")
    provided = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(provided, config.PENSINE_TOKEN):
        raise HTTPException(401, "invalid token")


def _lieu(lat: str, lon: str, place: str) -> dict | None:
    """Position sent with a deposit: valid coordinates and/or a stated place."""
    out = {}
    if lat.strip() and lon.strip():
        try:
            la, lo = float(lat.replace(",", ".")), float(lon.replace(",", "."))
        except ValueError:
            la = lo = None
        if la is not None and places.valid(la, lo):
            out.update(lat=round(la, 6), lon=round(lo, 6), source="raccourci")
    if place.strip():
        # the iPhone sends the address over several lines: one is enough
        out["place"] = places.one_line(place)[:200]
        out.setdefault("source", "declare")
    return out or None


def _locate_media(conn, media_id: int, lieu: dict | None, audio_filename: str | None) -> None:
    """The place of a media item at deposit time: the position sent, otherwise the Dictaphone file name."""
    place_from_name = places.from_filename(audio_filename)
    if not lieu and not place_from_name:
        return
    lieu = lieu or {"place": place_from_name, "source": "nom_dictaphone"}
    conn.execute(
        "UPDATE media SET lat = %s, lon = %s, place = %s, place_source = %s WHERE id = %s",
        (lieu.get("lat"), lieu.get("lon"), lieu.get("place") or place_from_name,
         lieu.get("source"), media_id),
    )


@app.post("/deposit")
async def deposit(
    file: UploadFile = File(...),
    note: str = Form(""),
    captured_at: str = Form(""),   # ISO 8601 if the shortcut provides it
    sender: str = Form(""),        # channel metadata (forwarded WhatsApp voice note)
    lat: str = Form(""),           # position at deposit time (iOS shortcut)
    lon: str = Form(""),
    place: str = Form(""),         # place stated by the person, in plain text
    sujet: str = Form(""),         # forgetting scope (PENSINE_SHRED=1): forget this subject in one go
    authorization: str | None = Header(None),
):
    """Pensine deposit: deliberate gesture only (never ambient surveillance)."""
    _check_token(authorization)

    when = (datetime.fromisoformat(captured_at) if captured_at
            else datetime.now(timezone.utc))
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    raw = await file.read()
    if not raw:
        # A shortcut whose "file" variable is empty sends a form part with
        # no bytes: refuse outright rather than archive an empty media item
        # that would wait for an impossible transcription.
        raise HTTPException(422, "empty file")
    kind = _kind(file.content_type, file.filename or "")
    digest = hashlib.sha256(raw).hexdigest()

    # Storage: year/month/hash.ext — the original file, never modified
    ext = Path(file.filename or "").suffix or {"audio": ".opus", "photo": ".jpg",
                                               "video": ".mp4", "pdf": ".pdf",
                                               "text": ".txt", "file": ".bin"}[kind]
    rel = Path(f"{when:%Y/%m}") / f"{digest[:16]}{ext}"
    dest = config.MEDIA_ROOT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        dest.write_bytes(raw)

    lieu = _lieu(lat, lon, place)
    with db.connection() as conn:
        media_id = db.insert_media(conn, captured_at=when, kind=kind,
                                   storage_path=str(rel))
        if kind == "text":
            # a text is its own transcript: readable as of tonight
            conn.execute("UPDATE media SET transcript = %s WHERE id = %s",
                         (raw.decode("utf-8", "replace")[:100_000], media_id))
        _locate_media(conn, media_id, lieu, file.filename if kind == "audio" else None)
        event_id = db.append_event(
            conn, source="pensieve", kind="deposit", occurred_at=when,
            payload={"note": note, "sender": sender, "filename": file.filename,
                     "sha256": digest, "kind": kind, **({"lieu": lieu} if lieu else {})},
            media_id=media_id,
            scope=shred.subject_scope(sujet) if sujet.strip() and config.SHRED_ENABLED else None,
        )
        db.audit(conn, "mcp", "pensieve_deposit",
                 {"media_id": media_id, "event_id": event_id, "kind": kind})
        conn.commit()

    return {"ok": True, "media_id": media_id, "event_id": event_id, "kind": kind}


@app.post("/log")
async def daily_log_gesture(
    text: str = Form(""),
    file: UploadFile | None = File(None),
    lat: str = Form(""),
    lon: str = Form(""),
    place: str = Form(""),
    authorization: str | None = Header(None),
):
    """The logbook in one gesture: iOS "Log" shortcut → you dictate, that is
    all. Text (transcribed by iOS) or raw audio — the audio is transcribed
    by the nightly cycle, then consolidated like a normal logbook entry."""
    _check_token(authorization)
    when = datetime.now(timezone.utc)
    lieu = _lieu(lat, lon, place)

    raw = await file.read() if file is not None else b""
    if file is not None and raw:
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
            _locate_media(conn, media_id, lieu, file.filename)
            event_id = db.append_event(
                conn, source="daily_log", kind="daily_log_voice",
                occurred_at=when,
                payload={"sha256": digest, "note": "log de bord vocal",
                         **({"lieu": lieu} if lieu else {})},
                media_id=media_id,
            )
            db.audit(conn, "mcp", "daily_log_voice",
                     {"media_id": media_id, "event_id": event_id})
            conn.commit()
        return {"ok": True, "event_id": event_id,
                "note": "transcribed tonight, consolidated afterwards"}

    # an empty file (unfilled shortcut variable) counts for nothing: fall
    # back on the text, and with no text refuse rather than archive nothing
    if not text.strip():
        raise HTTPException(422, "neither text nor audio file")
    with db.connection() as conn:
        event_id = db.append_event(
            conn, source="daily_log", kind="daily_log",
            occurred_at=when, payload={"transcript": text,
                                       **({"lieu": lieu} if lieu else {})},
        )
        db.audit(conn, "mcp", "daily_log_gesture", {"event_id": event_id})
        conn.commit()
    return {"ok": True, "event_id": event_id}


@app.get("/media/{token}")
def media(token: str):
    """Dive back in: temporary signed link to the original file."""
    if not config.MEDIA_LINK_SECRET:
        raise HTTPException(503, "PENSINE_MEDIA_LINK_SECRET not configured")
    signer = TimestampSigner(config.MEDIA_LINK_SECRET)
    try:
        media_id = int(signer.unsign(token, max_age=config.MEDIA_LINK_TTL_S))
    except (SignatureExpired, BadSignature, ValueError):
        raise HTTPException(403, "link expired or invalid")

    with db.connection() as conn:
        row = conn.execute("SELECT storage_path, kind FROM media WHERE id = %s",
                           (media_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    path = config.MEDIA_ROOT / row["storage_path"]
    if not path.exists():
        raise HTTPException(410, "file missing from storage")
    return FileResponse(path)
