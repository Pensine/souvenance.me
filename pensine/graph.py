"""Graphe de connaissances temporel (couche 1) — mécanique bi-temporelle
sur PostgreSQL (choix « base unique » du document fondateur ; mêmes propriétés
que Graphiti : intervalles de validité, invalidation des arêtes contredites,
requête « que savait-on / qu'était vrai au temps T »).

Deux axes de temps :
- valid_from / valid_to : le temps du MONDE (quand le fait était vrai)
- created_at / invalidated_at : le temps du SYSTÈME (quand il l'a appris/corrigé)
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
    """Ajoute une arête. `exclusive=True` : le nouveau fait remplace les arêtes
    actives de même (sujet, prédicat) vers un autre objet (ex. « habite à ») —
    elles sont fermées (valid_to) et marquées invalidées, jamais supprimées."""
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
    # Déduplication : l'arête active identique n'est pas recréée
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
    """Ingestion d'un lot extrait par la consolidation.
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
    return {"entities": len(ids), "relations_added": added}


def neighborhood(conn, query: str, at: datetime | None = None, limit: int = 12):
    """Les arêtes autour des entités qui matchent la requête — telles que
    valides au temps `at` (défaut : maintenant). C'est la brique « graphe »
    de la recherche hybride de recall."""
    at = at or datetime.now(timezone.utc)
    return conn.execute(
        """
        SELECT s.name AS subject, s.kind AS subject_kind, r.predicate,
               o.name AS object, o.kind AS object_kind,
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
    """Toute l'histoire d'une entité, arêtes fermées comprises —
    « que croyait-on, qu'est-ce qui a changé » (autobiographie dynamique)."""
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
