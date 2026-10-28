"""Temporal knowledge graph (layer 1) — bi-temporal mechanics on PostgreSQL
(the founding document's "single database" choice; same properties as
Graphiti: validity intervals, invalidation of contradicted edges, queries of
the form "what did we know / what was true at time T").

Two time axes:
- valid_from / valid_to: WORLD time (when the fact was true)
- created_at / invalidated_at: SYSTEM time (when it learned/corrected it)
"""

from datetime import datetime, timezone


def upsert_entity(conn, name: str, kind: str) -> int:
    row = conn.execute(
        """
        INSERT INTO entities (name, kind) VALUES (%s, %s)
        ON CONFLICT (lower(name), kind) DO UPDATE SET name = entities.name
        RETURNING id
        """,
        (name.strip(), kind),
    ).fetchone()
    return row["id"]


def add_relation(
    conn, *, subject_id: int, predicate: str, object_id: int,
    valid_from: datetime, valid_to: datetime | None = None,
    exclusive: bool = False, source_event_ids: list[int] | None = None,
) -> int | None:
    """Add an edge. `exclusive=True`: the new fact replaces the active edges
    with the same (subject, predicate) pointing to a different object (e.g.
    "lives in") — they are closed (valid_to) and marked invalidated, never deleted."""
    if exclusive:
        conn.execute(
            """
            UPDATE relations
            SET valid_to = %s, invalidated_at = now()
            WHERE subject_id = %s AND predicate = %s AND valid_to IS NULL
              AND object_id != %s
            """,
            (valid_from, subject_id, predicate, object_id),
        )
    # Deduplication: an identical active edge is not recreated
    existing = conn.execute(
        """
        SELECT id FROM relations
        WHERE subject_id = %s AND predicate = %s AND object_id = %s
          AND valid_to IS NULL
        """,
        (subject_id, predicate, object_id),
    ).fetchone()
    if existing:
        return None
    row = conn.execute(
        """
        INSERT INTO relations (subject_id, predicate, object_id,
                               valid_from, valid_to, source_event_ids)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (subject_id, predicate, object_id, valid_from, valid_to,
         source_event_ids or []),
    ).fetchone()
    return row["id"]


def ingest(conn, entities: list[dict], relations: list[dict],
           source_event_ids: list[int]) -> dict:
    """Ingest a batch extracted by consolidation.
    entities : [{name, kind}] ; relations : [{subject, predicate, object,
    subject_kind?, object_kind?, valid_from?, exclusive?}]."""
    ids: dict[str, int] = {}
    for e in entities:
        if e.get("name") and e.get("kind"):
            ids[e["name"].strip().lower()] = upsert_entity(conn, e["name"], e["kind"])

    added = 0
    for r in relations:
        subj, obj = (r.get("subject") or "").strip(), (r.get("object") or "").strip()
        if not subj or not obj or not r.get("predicate"):
            continue
        sid = ids.get(subj.lower()) or upsert_entity(
            conn, subj, r.get("subject_kind", "person"))
        oid = ids.get(obj.lower()) or upsert_entity(
            conn, obj, r.get("object_kind", "place"))
        vf = r.get("valid_from")
        vf = datetime.fromisoformat(vf) if isinstance(vf, str) else \
            (vf or datetime.now(timezone.utc))
        if vf.tzinfo is None:
            vf = vf.replace(tzinfo=timezone.utc)
        if add_relation(conn, subject_id=sid, predicate=r["predicate"],
                        object_id=oid, valid_from=vf,
                        exclusive=bool(r.get("exclusive")),
                        source_event_ids=source_event_ids) is not None:
            added += 1
    # `entity_ids` is used to attach relationship state to the entities this
    # batch has just resolved (see pensine/relations.py): without it, names
    # would have to be re-resolved, risking duplicates.
    return {"entities": len(ids), "relations_added": added, "entity_ids": ids}


def neighborhood(conn, query: str, at: datetime | None = None, limit: int = 12):
    """The edges around the entities matching the query — as valid at time
    `at` (default: now). This is the "graph" building block of recall's
    hybrid search."""
    at = at or datetime.now(timezone.utc)
    return conn.execute(
        """
        SELECT s.id AS subject_id, s.name AS subject, s.kind AS subject_kind,
               r.predicate,
               o.id AS object_id, o.name AS object, o.kind AS object_kind,
               r.valid_from, r.valid_to
        FROM relations r
        JOIN entities s ON s.id = r.subject_id
        JOIN entities o ON o.id = r.object_id
        WHERE (s.name ILIKE '%%' || %s || '%%' OR o.name ILIKE '%%' || %s || '%%')
          AND r.valid_from <= %s
          AND (r.valid_to IS NULL OR r.valid_to > %s)
        ORDER BY r.valid_from DESC
        LIMIT %s
        """,
        (query, query, at, at, limit),
    ).fetchall()


def entity_history(conn, name: str):
    """The whole history of an entity, closed edges included —
    "what did we believe, what changed" (dynamic autobiography)."""
    return conn.execute(
        """
        SELECT s.name AS subject, r.predicate, o.name AS object,
               r.valid_from, r.valid_to, r.created_at, r.invalidated_at
        FROM relations r
        JOIN entities s ON s.id = r.subject_id
        JOIN entities o ON o.id = r.object_id
        WHERE s.name ILIKE %s OR o.name ILIKE %s
        ORDER BY r.valid_from
        """,
        (name, name),
    ).fetchall()
