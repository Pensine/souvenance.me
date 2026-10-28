"""Card data: what the conversation shows, not just tells.

Three cards, each for one act of remembering:
  · LISTEN — the original voice recording, its transcript scrolling word by
    word, where and when it was said;
  · MEMORY — a memory in its time and space: the photo, a small map of
    nearby localities, the life era, its continuity;
  · TIMELINE — a subject over time: what was, what changed and why,
    what is, what is coming.

This module only gathers data; rendering lives in pensine/widgets/.
Nothing here calls an external service: the map is drawn from local
GeoNames data, the photo is downscaled and embedded.
"""

from __future__ import annotations

import base64
import io
import json
import math
from datetime import datetime, timezone

from . import config, db, intentions, places, temporal


def _iso(d) -> str | None:
    return d.isoformat() if d else None


# --------------------------------------------------------------------------- media

def _media_rows(conn, memory_id: int) -> list[dict]:
    """The media a memory originates from, through its source events."""
    return conn.execute(
        """
        SELECT m.id, m.kind, m.storage_path, m.captured_at, m.duration_s, m.transcript,
               m.description, m.lat, m.lon, m.place, m.place_source,
               e.payload->>'filename' AS filename
        FROM memories mm
        JOIN events e ON e.id = ANY(mm.source_event_ids)
        JOIN media m ON m.id = e.media_id
        WHERE mm.id = %s ORDER BY m.id
        """,
        (memory_id,),
    ).fetchall()


def _media(conn, media_id: int):
    return conn.execute(
        """SELECT m.id, m.kind, m.storage_path, m.captured_at, m.duration_s, m.transcript,
                  m.description, m.lat, m.lon, m.place, m.place_source,
                  e.payload->>'filename' AS filename
           FROM media m LEFT JOIN events e ON e.media_id = m.id
           WHERE m.id = %s LIMIT 1""",
        (media_id,),
    ).fetchone()


def words(storage_path: str) -> list[dict]:
    """WhisperX timestamped words ({w, s, e}), or an empty list."""
    path = config.MEDIA_ROOT / f"{storage_path}.whisperx.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    out = []
    for seg in data.get("segments") or []:
        for w in seg.get("words") or []:
            if "start" in w and "end" in w and w.get("word"):
                out.append({"w": w["word"], "s": round(w["start"], 2), "e": round(w["end"], 2)})
    return out


def thumbnail(storage_path: str, max_px: int = 720) -> str | None:
    """Downscaled photo as a data: URL — the card frame loads nothing external."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    path = config.MEDIA_ROOT / storage_path
    if not path.exists():
        return None
    try:
        img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        img.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=78, optimize=True)
    except Exception:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


# --------------------------------------------------------------------------- place

def mini_map(lat: float, lon: float, radius_km: float = 30, limit: int = 7) -> dict | None:
    """A map without tiles: the point, and the nearby localities placed at
    their true distance and bearing. Drawn as SVG by the card, computed
    here from local GeoNames data — no map server ever sees the
    position."""
    idx = places._index(str(places.GEO_DIR))
    if idx is None or not places.valid(lat, lon):
        return None
    grid, _ = idx
    cy, cx = math.floor(lat), math.floor(lon)
    near = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for c in grid.get((cy + dy, cx + dx), ()):
                d = places.distance_km((lat, lon), (c[0], c[1]))
                if d <= radius_km:
                    near.append((d, c))
    near.sort(key=lambda x: x[0])
    near = near[:limit]
    # scale adapted to the spread: in a city, 30 km would cram everything into the centre
    far = max((d for d, _ in near), default=radius_km)
    radius_km = max(5, min(radius_km, math.ceil(far * 1.15)))
    k = math.cos(math.radians(lat))
    pts = [{"name": c[2], "km": round(d, 1),
            # east/north in km, relative to the point
            "x": round((c[1] - lon) * 111.32 * k, 2), "y": round((c[0] - lat) * 110.57, 2)}
           for d, c in near]
    return {"radius_km": radius_km, "points": pts}


def where(row) -> dict | None:
    if row is None or (row.get("lat") is None and not row.get("place")):
        return None
    out = {"label": row.get("place") or places.label(row.get("lat"), row.get("lon")),
           "source": places.SOURCE_LABELS.get(row.get("place_source"), row.get("place_source"))}
    if row.get("lat") is not None:
        out["lat"], out["lon"] = row["lat"], row["lon"]
        out["map"] = mini_map(row["lat"], row["lon"])
    return out


# --------------------------------------------------------------------------- cards

def listen(conn, *, memory_id: int = 0, media_id: int = 0, link=None) -> dict | None:
    """LISTEN: the original voice recording of a memory (or a given media item)."""
    memory = db.get_memory(conn, memory_id) if memory_id else None
    if memory_id and memory is None:
        return None
    media = None
    if media_id:
        media = _media(conn, media_id)
    elif memory:
        media = next((m for m in _media_rows(conn, memory_id)
                      if m["kind"] in ("audio", "video")), None)
    if media is None or media["kind"] not in ("audio", "video"):
        return None
    chapters = db.chapters(conn)
    when = media["captured_at"]
    w = words(media["storage_path"])
    return {
        "card": "listen",
        "media_id": media["id"],
        "memory": memory and {"id": memory["id"], "content": memory["content"]},
        "date": _iso(when), "quand": temporal.humanize_delta(when),
        "epoque": temporal.epoch(chapters, when),
        "ou": where(media),
        "audio_url": link(media["id"]) if link else None,
        "duration_s": media["duration_s"] or (w[-1]["e"] if w else None),
        # the words themselves are requested by the card (listen_words tool):
        # Claude receives the count and the text, not 800 timestamps
        "words_count": len(w),
        "transcript": media["transcript"],
    }


def memory(conn, memory_id: int, link=None) -> dict | None:
    """MEMORY: a memory in its time, its space and its continuity."""
    row = conn.execute(
        """SELECT id, type, content, confidence, valid_from, valid_to, superseded_by,
                  archived_at, revision_note, source_event_ids, lat, lon, place, place_source,
                  evidence
           FROM memories WHERE id = %s""", (memory_id,)).fetchone()
    if row is None:
        return None
    chapters = db.chapters(conn)
    media = _media_rows(conn, memory_id)
    photo = next((m for m in media if m["kind"] == "photo"), None)
    audio = next((m for m in media if m["kind"] in ("audio", "video")), None)
    lieu = where(row) or where(photo) or where(audio)
    before = conn.execute(
        "SELECT id, content, valid_to, revision_note FROM memories WHERE superseded_by = %s",
        (memory_id,)).fetchall()
    after = db.memory_snippets(conn, [row["superseded_by"]] if row["superseded_by"] else [])
    t = temporal.tense(row["valid_from"], row["valid_to"], row["superseded_by"])
    return {
        "card": "memory",
        "id": row["id"], "type": row["type"], "content": row["content"],
        "confidence": row["confidence"],
        "temps": t, "date": _iso(row["valid_from"]),
        "quand": temporal.humanize_delta(row["valid_from"]),
        "fin": _iso(row["valid_to"]), "raison": row["revision_note"],
        "archivee": row["archived_at"] is not None,
        "preuve": (row["evidence"] or {}).get("citations") or [],
        "controle": (row["evidence"] or {}).get("statut"),
        "epoque": temporal.epoch(chapters, row["valid_from"]),
        "ou": lieu,
        # the photo itself is requested by the card (memory_photo tool)
        "photo_media_id": photo["id"] if photo else None,
        "photo_description": photo["description"] if photo else None,
        "audio_media_id": audio["id"] if audio else None,
        "avant": [{"id": b["id"], "content": b["content"], "raison": b["revision_note"],
                   "fin": _iso(b["valid_to"])} for b in before],
        "apres": [{"id": i, "content": c} for i, c in after.items()],
    }


def timeline(conn, rows: list, subject: str = "", now: datetime | None = None) -> dict:
    """TIMELINE: memories about one subject, sorted into four tenses."""
    now = now or datetime.now(timezone.utc)
    chapters = db.chapters(conn)
    successors = db.memory_snippets(conn, [r["superseded_by"] for r in rows if r.get("superseded_by")])
    lanes = {"etait": [], "change": [], "est": [], "vient": []}
    for r in rows:
        t = temporal.tense(r["valid_from"], r.get("valid_to"), r.get("superseded_by"), now)
        item = {"id": r["id"], "content": r["content"], "type": r["type"],
                "date": _iso(r["valid_from"]), "quand": temporal.humanize_delta(r["valid_from"], now),
                "epoque": temporal.epoch(chapters, r["valid_from"]),
                "lieu": (where(r) or {}).get("label")}
        # an episode is a dated moment: after a month, it belongs to history
        # even if nothing has "replaced" it (a departure, a race)
        episode_ancien = (r["type"] == "episodic" and t == "present"
                          and (now - temporal._aware(r["valid_from"])).days > 30)
        if t == "past" or episode_ancien:
            lanes["etait"].append(item)
            if r.get("revision_note") or r.get("superseded_by"):
                ended = r.get("valid_to") or r.get("revised_at")
                lanes["change"].append({
                    "id": r["id"], "date": _iso(ended),
                    "quand": temporal.humanize_delta(ended, now) if ended else None,
                    "raison": r.get("revision_note"),
                    "de": r["content"],
                    "vers": successors.get(r.get("superseded_by")),
                    "vers_id": r.get("superseded_by")})
        elif t == "future":
            lanes["vient"].append(item)
        else:
            lanes["est"].append(item)
    # upcoming landmarks, only if they concern the subject: a planned race
    # has no business on the timeline of a work project
    terms = [t for t in subject.lower().split() if len(t) >= 4]
    for lm in conn.execute(
        """SELECT name, at_date, kind FROM landmarks
           WHERE at_date >= %s AND kind IN ('race','life_event','chapter_start')
           ORDER BY at_date LIMIT 20""", (now.date(),)).fetchall():
        if not any(t in lm["name"].lower() for t in terms):
            continue
        d = datetime.combine(lm["at_date"], datetime.min.time(), tzinfo=timezone.utc)
        lanes["vient"].append({"id": None, "content": lm["name"], "type": "jalon",
                               "date": _iso(d), "quand": temporal.humanize_delta(d, now),
                               "epoque": None, "lieu": None})
    # the subject's steps: open → "what is coming", closed → "what changed"
    for st in intentions.steps_for(conn, subject):
        state = intentions.status(st, now)
        mentioned = st["last_mentioned_at"] or st["created_at"]
        due = intentions.due_date(st)
        if state in ("fait", "abandonne"):
            lanes["change"].append({
                "id": None, "date": _iso(st["resolved_at"]),
                "quand": temporal.humanize_delta(st["resolved_at"], now),
                "raison": st["outcome_note"],
                "de": f"Planned: {st['content']}",
                "vers": "done" if state == "fait" else "abandoned",
                "vers_id": None, "intention_id": st["id"], "issue": state})
            continue
        if due:
            d = datetime.combine(due, datetime.min.time(), tzinfo=timezone.utc)
            when, quand = _iso(d), temporal.humanize_delta(d, now)
        else:
            # undated: sorted after the dated steps, by how long ago it was mentioned
            when, quand = None, f"mentioned {temporal.humanize_delta(mentioned, now)}"
        lanes["vient"].append({"id": None, "intention_id": st["id"], "content": st["content"],
                               "type": "etape", "date": when, "quand": quand,
                               "echeance": due.isoformat() if due else None,
                               "statut": state, "epoque": None, "lieu": None})
    for name, lane in lanes.items():
        if name == "vient":
            # dated first, in order; then the undated ones
            lane.sort(key=lambda i: (i.get("date") is None, i.get("date") or ""))
        else:
            lane.sort(key=lambda i: i.get("date") or "")
    return {"card": "timeline", "lanes": lanes, "now": _iso(now)}
