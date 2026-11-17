"""Temporal knowledge graph (layer 1) — bi-temporal mechanics on PostgreSQL
(the founding document's "single database" choice; same properties as
Graphiti: validity intervals, invalidation of contradicted edges, queries of
the form "what did we know / what was true at time T").

Two time axes:
- valid_from / valid_to: WORLD time (when the fact was true)
- created_at / invalidated_at: SYSTEM time (when it learned/corrected it)
"""

from datetime import datetime, timezone

from . import identity


def resolve_entity(conn, name: str, kind: str) -> tuple[int, int | None]:
    """The entity a mention designates, created if none: (entity_id, alias_id).

    An active identity claim wins (pensine/identity.py): once "my sister
    Priya" is admitted, "my sister" lands on Priya. `alias_id` names the claim
    used, None when the mention matched by name or created the entity."""
    hit = identity.resolve(conn, name, kind)
    if hit:
        return hit
    return _insert_entity(conn, name, kind), None


def resolve_subject(conn, mention: str) -> tuple[int, int | None] | None:
    """The person a memory is about, from the subject as consolidation wrote
    it ("Priya", "my sister"): (entity_id, alias_id) or None.

    Same resolution as edges (an active claim first, then the name), with
    one difference: a mention that an active claim gives to two people
    resolves to nothing instead of creating a third entity named after the
    role. A memory with no subject is honest; one on the wrong person is an
    attribution error."""
    mention = (mention or "").strip()
    if not mention:
        return None
    if len(identity.resolve_alias(conn, mention, "person")) > 1:
        return None
    return resolve_entity(conn, mention, "person")


def upsert_entity(conn, name: str, kind: str) -> int:
    return resolve_entity(conn, name, kind)[0]


def _insert_entity(conn, name: str, kind: str) -> int:
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
    via_alias_ids: list[int] | None = None,
) -> int | None:
    """Add an edge. `exclusive=True`: the new fact replaces the active edges
    with the same (subject, predicate) pointing to a different object (e.g.
    "lives in") — they are closed (valid_to) and marked invalidated, never deleted.
    `via_alias_ids`: the identity claims a side was resolved through, so that
    retracting one can say which edges it carried."""
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
    if via_alias_ids:
        row = conn.execute(
            """
            INSERT INTO relations (subject_id, predicate, object_id, valid_from,
                                   valid_to, source_event_ids, via_alias_ids)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (subject_id, predicate, object_id, valid_from, valid_to,
             source_event_ids or [], sorted(set(via_alias_ids))),
        ).fetchone()
        return row["id"]
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
           source_event_ids: list[int], aliases: list[dict] | None = None,
           events: list[dict] | None = None) -> dict:
    """Ingest a batch extracted by consolidation.
    entities : [{name, kind}] ; relations : [{subject, predicate, object,
    subject_kind?, object_kind?, valid_from?, exclusive?}] ;
    aliases : [{name, alias, excerpt|preuve, alias_kind?, role_of_owner?,
    kind?, confidence?, source_event_id?}] — identity claims, admitted or left
    pending by pensine/identity.py BEFORE the mentions are resolved, so that
    "my sister" in tonight's relations already lands on Priya.
    `events`: the deposits of the batch (the claims' excerpts are checked
    against them)."""
    alias_report = _ingest_aliases(conn, aliases or [], source_event_ids, events or [])
    ids: dict[str, int] = {}
    via: dict[str, int] = {}

    def resolve(name: str, kind: str) -> int:
        key = name.strip().lower()
        if key not in ids:
            eid, alias_id = resolve_entity(conn, name, kind)
            ids[key] = eid
            if alias_id:
                via[key] = alias_id
        return ids[key]

    for e in entities:
        if e.get("name") and e.get("kind"):
            resolve(e["name"], e["kind"])

    added = 0
    for r in relations:
        subj, obj = (r.get("subject") or "").strip(), (r.get("object") or "").strip()
        if not subj or not obj or not r.get("predicate"):
            continue
        sid = resolve(subj, r.get("subject_kind", "person"))
        oid = resolve(obj, r.get("object_kind", "place"))
        vf = r.get("valid_from")
        vf = datetime.fromisoformat(vf) if isinstance(vf, str) else \
            (vf or datetime.now(timezone.utc))
        if vf.tzinfo is None:
            vf = vf.replace(tzinfo=timezone.utc)
        through = [via[k] for k in (subj.lower(), obj.lower()) if k in via]
        if add_relation(conn, subject_id=sid, predicate=r["predicate"],
                        object_id=oid, valid_from=vf,
                        exclusive=bool(r.get("exclusive")),
                        source_event_ids=source_event_ids,
                        via_alias_ids=through) is not None:
            added += 1
    # `entity_ids` is used to attach relationship state to the entities this
    # batch has just resolved (see pensine/relations.py): without it, names
    # would have to be re-resolved, risking duplicates.
    return {"entities": len(ids), "relations_added": added, "entity_ids": ids,
            **alias_report}


def _ingest_aliases(conn, aliases: list[dict], source_event_ids: list[int],
                    events: list[dict]) -> dict:
    """Propose each claim against the deposit its excerpt comes from. A claim
    citing a deposit outside the batch, or none, is checked against nothing
    and stays pending."""
    if not aliases:
        return {}
    from . import evidence
    by_id = {e["id"]: e for e in events if "id" in e and e["id"] in source_event_ids}
    admitted = pending = 0
    for a in aliases:
        name, alias = (a.get("name") or "").strip(), (a.get("alias") or "").strip()
        excerpt = a.get("excerpt") or a.get("preuve") or ""
        if isinstance(excerpt, list):
            excerpt = next((x for x in excerpt if isinstance(x, str)), "")
        if not name or not alias:
            continue
        sid = a.get("source_event_id")
        try:
            sid = int(sid) if sid is not None else None
        except (TypeError, ValueError):
            sid = None
        if sid not in by_id:  # the model's id is wrong or missing: find the deposit
            sid = next((i for i, e in by_id.items()
                        if evidence.quote_found(excerpt, evidence.source_text(e))), None)
        kind = a.get("kind") or "person"
        alias_kind = a.get("alias_kind") if a.get("alias_kind") in identity.ALIAS_KINDS \
            else ("role" if a.get("role_of_owner") else "name")
        try:
            conf = min(max(float(a.get("confidence", 0.5)), 0.0), 1.0)
        except (TypeError, ValueError):
            conf = 0.5
        out = identity.propose(
            conn, entity_id=upsert_entity(conn, name, kind),
            alias=alias, excerpt=excerpt, source_event_id=sid, confidence=conf,
            alias_kind=alias_kind, role_of_owner=a.get("role_of_owner"),
            event=by_id.get(sid))
        if out["status"] == "active":
            admitted += 1
        else:
            pending += 1
    return {"aliases_admitted": admitted, "aliases_pending": pending}


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
    "what did we believe, what changed" (dynamic autobiography).
    The name may be an alias with an active claim ("my sister"); each edge
    says which claims it was attached through (`via_alias_ids`), and
    `identity.claims` gives their excerpts."""
    hit = identity.resolve(conn, name, None)
    ids = [hit[0]] if hit else []
    return conn.execute(
        """
        SELECT s.name AS subject, r.predicate, o.name AS object,
               r.valid_from, r.valid_to, r.created_at, r.invalidated_at,
               r.via_alias_ids
        FROM relations r
        JOIN entities s ON s.id = r.subject_id
        JOIN entities o ON o.id = r.object_id
        WHERE s.name ILIKE %s OR o.name ILIKE %s
           OR s.id = ANY(%s) OR o.id = ANY(%s)
        ORDER BY r.valid_from
        """,
        (name, name, ids, ids),
    ).fetchall()
