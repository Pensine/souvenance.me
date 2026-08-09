"""Accès PostgreSQL — couche 0 (events) et couche 1 (memories, graphe).

Règle structurelle : `events` est append-only. Ce module n'expose
volontairement aucune fonction d'UPDATE/DELETE sur les events
(et un trigger SQL l'interdit au niveau base).
"""

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from . import config


@contextmanager
def connection():
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row) as conn:
        yield conn


def event_hash(source: str, kind: str, occurred_at: datetime, payload: dict) -> str:
    """Hash de déduplication : un même fait perçu deux fois ne crée qu'un event."""
    blob = json.dumps(
        {"s": source, "k": kind, "o": occurred_at.isoformat(), "p": payload},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def append_event(
    conn,
    *,
    source: str,
    kind: str,
    occurred_at: datetime,
    payload: dict,
    media_id: int | None = None,
    origin: str = "declared",
) -> int | None:
    """Ajoute un fait au log. Retourne l'id, ou None si doublon (déjà perçu).

    `origin` distingue ce que l'utilisateur a délibérément déposé ('declared')
    de ce qu'un assistant a proposé et qu'il a accepté ('proposed'). Sans cette
    distinction, les deux deviennent indiscernables dès le lendemain — et la
    question « qu'est-ce que le système a retenu de lui-même ? » perd sa
    réponse. Elle n'entre pas dans le hash : la provenance qualifie le fait,
    elle ne le change pas.
    """
    h = event_hash(source, kind, occurred_at, payload)
    row = conn.execute(
        """
        INSERT INTO events (occurred_at, source, kind, payload, media_id, hash, origin)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (hash) DO NOTHING
        RETURNING id
        """,
        (occurred_at, source, kind, json.dumps(payload, ensure_ascii=False),
         media_id, h, origin),
    ).fetchone()
    return row["id"] if row else None


def insert_media(
    conn, *, captured_at: datetime, kind: str, storage_path: str,
    duration_s: int | None = None, exif: dict | None = None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO media (captured_at, kind, storage_path, duration_s, exif)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
        """,
        (captured_at, kind, storage_path, duration_s,
         json.dumps(exif, ensure_ascii=False) if exif else None),
    ).fetchone()
    return row["id"]


def unconsolidated_events(conn, limit: int = 200):
    """Events jamais examinés — le « jour » à rejouer.

    Un événement qui n'a rien produit reste un événement examiné : sans le
    marqueur, un log vide ou un test reviendrait chaque nuit indéfiniment,
    coûtant un appel au modèle à chaque fois et gonflant le prompt de tous les
    cycles suivants.

    La condition sur `source_event_ids` reste en second filet pour les
    événements consolidés avant l'existence des marqueurs. Les médias
    transcrits/décrits sont joints : la consolidation voit le contenu.
    """
    return conn.execute(
        """
        SELECT e.id, e.occurred_at, e.source, e.kind, e.payload,
               m.transcript AS media_transcript, m.description AS media_description,
               m.exif AS media_exif
        FROM events e
        LEFT JOIN media m ON m.id = e.media_id
        WHERE NOT EXISTS (
            SELECT 1 FROM consolidation_marks cm WHERE cm.event_id = e.id
        )
        AND NOT EXISTS (
            SELECT 1 FROM memories mm WHERE e.id = ANY(mm.source_event_ids)
        )
        -- un dépôt média attend son retraitement avant d'être consolidé
        AND (e.media_id IS NULL
             OR m.transcript IS NOT NULL OR m.description IS NOT NULL)
        ORDER BY e.occurred_at
        LIMIT %s
        """,
        (limit,),
    ).fetchall()


def mark_examined(conn, event_ids: list[int], memory_ids: set[int]) -> None:
    """Trace le passage d'un cycle de consolidation sur ces événements.

    À n'appeler qu'après une consolidation réussie : si la couche intelligente
    est indisponible, rien n'est marqué et les événements repassent au cycle
    suivant — la promesse « le pire scénario est une pause » tient.
    """
    if not event_ids:
        return
    produced = set()
    if memory_ids:
        rows = conn.execute(
            "SELECT DISTINCT unnest(source_event_ids) AS eid FROM memories "
            "WHERE id = ANY(%s)",
            (sorted(memory_ids),),
        ).fetchall()
        produced = {r["eid"] for r in rows}
    for eid in event_ids:
        conn.execute(
            "INSERT INTO consolidation_marks (event_id, produced_memory) "
            "VALUES (%s, %s) ON CONFLICT (event_id) DO NOTHING",
            (eid, eid in produced),
        )


def audit(conn, actor: str, action: str, detail: dict | None = None) -> None:
    """Couche 7 : chaque action du système laisse une trace."""
    conn.execute(
        "INSERT INTO audit_log (actor, action, detail) VALUES (%s, %s, %s)",
        (actor, action, json.dumps(detail or {}, ensure_ascii=False)),
    )


def search_memories(conn, query: str, embedding: list[float] | None, limit: int = 8):
    """Recherche hybride v1 : vecteur si embedding fourni, sinon plein-texte.

    Marque l'accès (access_count / last_accessed_at) — carburant de l'oubli actif.
    """
    if embedding is not None:
        rows = conn.execute(
            """
            SELECT id, type, content, confidence, importance, valence, arousal,
                   valid_from, valid_to,
                   source_event_ids, embedding <=> %s::vector AS distance
            FROM memories
            WHERE superseded_by IS NULL AND embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (str(embedding), str(embedding), limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, type, content, confidence, importance, valence, arousal,
                   valid_from, valid_to,
                   source_event_ids, NULL::real AS distance
            FROM memories
            WHERE superseded_by IS NULL
              AND content ILIKE '%%' || %s || '%%'
            ORDER BY importance DESC
            LIMIT %s
            """,
            (query, limit),
        ).fetchall()
    if rows:
        conn.execute(
            """
            UPDATE memories
            SET access_count = access_count + 1, last_accessed_at = now()
            WHERE id = ANY(%s)
            """,
            ([r["id"] for r in rows],),
        )
    return rows


def source_events(conn, event_ids: list[int]):
    """Fragments originaux (depth=source) : events + média rattaché."""
    if not event_ids:
        return []
    return conn.execute(
        """
        SELECT e.id, e.occurred_at, e.source, e.kind, e.payload,
               m.id AS media_id, m.kind AS media_kind, m.storage_path,
               m.transcript, m.description
        FROM events e
        LEFT JOIN media m ON m.id = e.media_id
        WHERE e.id = ANY(%s)
        ORDER BY e.occurred_at
        """,
        (event_ids,),
    ).fetchall()
