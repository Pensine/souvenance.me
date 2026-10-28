"""PostgreSQL access — layer 0 (events) and layer 1 (memories, graph).

Structural rule: `events` is append-only. This module deliberately exposes no
UPDATE/DELETE function on events (and an SQL trigger forbids it at the
database level).
"""

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from . import config, shred


@contextmanager
def connection():
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row) as conn:
        yield conn


def event_hash(source: str, kind: str, occurred_at: datetime, payload: dict) -> str:
    """Deduplication hash: the same fact perceived twice creates only one event."""
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
    scope: str | None = None,
) -> int | None:
    """Append a fact to the log. Returns the id, or None if a duplicate (already perceived).

    `origin` distinguishes what the user deliberately deposited ('declared')
    from what an assistant proposed and the user accepted ('proposed'). Without
    this distinction the two become indistinguishable the next day — and the
    question "what did the system retain on its own?" loses its answer. It
    does not enter the hash: provenance qualifies the fact, it does not change it.

    With PENSINE_SHRED=1, the payload is sealed under the key of `scope`
    (by default, a scope specific to this deposit): see pensine/shred.py.
    """
    if config.SHRED_ENABLED:
        scope = scope or shred.deposit_scope()
        h = shred.keyed_hash(scope, source, kind, occurred_at, payload)
        payload = shred.seal(payload, scope)
        shred.register(conn, scope)
    else:
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
    """Never-examined events — the "day" to replay.

    An event that produced nothing remains an examined event: without the
    marker, an empty log or a test would come back every night indefinitely,
    costing a model call each time and bloating the prompt of every
    subsequent cycle.

    The condition on `source_event_ids` remains as a second safety net for
    events consolidated before the markers existed. Transcribed/described
    media are joined: consolidation sees the content.
    Sealed deposits are rendered in clear (pensine/shred.py); a lost or
    destroyed key silences the deposit, it is not replayed.
    """
    rows = shred.open_rows(conn.execute(
        """
        SELECT e.id, e.occurred_at, e.source, e.kind, e.payload,
               m.transcript AS media_transcript, m.description AS media_description,
               m.exif AS media_exif, m.lat AS media_lat, m.lon AS media_lon,
               m.place AS media_place, m.place_source AS media_place_source
        FROM events e
        LEFT JOIN media m ON m.id = e.media_id
        WHERE NOT EXISTS (
            SELECT 1 FROM consolidation_marks cm WHERE cm.event_id = e.id
        )
        AND NOT EXISTS (
            SELECT 1 FROM memories mm WHERE e.id = ANY(mm.source_event_ids)
        )
        -- a media deposit waits for its reprocessing before being consolidated
        AND (e.media_id IS NULL
             OR m.transcript IS NOT NULL OR m.description IS NOT NULL)
        ORDER BY e.occurred_at
        LIMIT %s
        """,
        (limit,),
    ).fetchall())
    return [r for r in rows if not r.get("forgotten")]


def mark_examined(conn, event_ids: list[int], memory_ids: set[int]) -> None:
    """Record that a consolidation cycle has passed over these events.

    Only call after a successful consolidation: if the intelligent layer is
    unavailable, nothing is marked and the events come around again in the
    next cycle — the promise "the worst case is a pause" holds.
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
    """Layer 7: every action of the system leaves a trace."""
    conn.execute(
        "INSERT INTO audit_log (actor, action, detail) VALUES (%s, %s, %s)",
        (actor, action, json.dumps(detail or {}, ensure_ascii=False)),
    )


_SEARCH_COLS = """id, type, content, confidence, importance, valence, arousal,
              valid_from, valid_to, source_event_ids, superseded_by,
              archived_at, revised_at, revision_note, lat, lon, place, place_source,
              evidence"""


def _search_filters(include_past: bool, include_archived: bool,
                    window: tuple | None = None) -> tuple[list[str], list]:
    where, params = ["TRUE"], []
    if not include_past:
        where.append("superseded_by IS NULL")
    if not include_archived:
        where.append("archived_at IS NULL")
    if window:
        start, end = window
        if start is not None:
            where.append("valid_from >= %s")
            params.append(start)
        if end is not None:
            where.append("valid_from < %s")
            params.append(end)
    return where, params


def vector_candidates(conn, embedding, limit: int, where: list[str], params: list):
    return conn.execute(
        f"""
        SELECT {_SEARCH_COLS}, embedding <=> %s::vector AS distance
        FROM memories
        WHERE {" AND ".join(where)} AND embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
        """,
        (str(embedding), *params, str(embedding), limit),
    ).fetchall()


def lexical_candidates(conn, words: list[str], limit: int, where: list[str], params: list):
    """Full-text search weighted by word rarity (IDF, BM25-style).

    PostgreSQL's ts_rank ignores a word's frequency in the corpus: a first name
    present in half the memories would weigh as much as a place name cited
    once. So we first count, for each word, how many memories contain it (one
    query, served by the GIN index), then score each memory by the sum of the
    IDFs of the words it contains. Length barely breaks ties (normalized
    ts_rank), it does not decide.

    Raises psycopg.errors.UndefinedColumn if migration 013 is missing.
    """
    from . import retrieval

    words = [retrieval.lexeme(w) for w in words]
    if not words:
        return []
    probes = ", ".join(
        f"count(*) FILTER (WHERE content_tsv @@ to_tsquery('simple', %s)) AS df{i}"
        for i in range(len(words)))
    counts = conn.execute(
        f"SELECT count(*) AS total, {probes} FROM memories WHERE {' AND '.join(where)}",
        (*words, *params),
    ).fetchone()
    total, dfs = counts["total"], [counts[f"df{i}"] for i in range(len(words))]
    if not total:
        return []
    import math
    weighted = [(w, math.log(1 + (total - df + 0.5) / (df + 0.5)))
                for w, df in zip(words, dfs) if df]
    if not weighted:
        return []
    score = " + ".join(
        "(content_tsv @@ to_tsquery('simple', %s))::int * %s" for _ in weighted)
    any_word = " | ".join(w for w, _ in weighted)
    rows = conn.execute(
        f"""
        SELECT {_SEARCH_COLS}, NULL::real AS distance,
               ({score}) + 0.01 * ts_rank(content_tsv, to_tsquery('simple', %s), 1)
                 AS lexical_score
        FROM memories
        WHERE {" AND ".join(where)} AND content_tsv @@ to_tsquery('simple', %s)
        ORDER BY lexical_score DESC, importance DESC, id
        LIMIT %s
        """,
        (*[x for pair in weighted for x in pair], any_word, *params, any_word, limit),
    ).fetchall()
    # Keep only what truly matches: a memory that shares with the question
    # only an omnipresent first name is not a candidate, and rank fusion would
    # treat it as one.
    floor = retrieval.LEX_MIN_FRAC * sum(idf for _, idf in weighted)
    return [r for r in rows if r["lexical_score"] >= floor]


def _ilike_candidates(conn, query: str, limit: int, where: list[str], params: list):
    return conn.execute(
        f"""
        SELECT {_SEARCH_COLS}, NULL::real AS distance
        FROM memories
        WHERE {" AND ".join(where)}
          AND content ILIKE '%%' || %s || '%%'
        ORDER BY importance DESC
        LIMIT %s
        """,
        (*params, query, limit),
    ).fetchall()


def search_memories(conn, query: str, embedding: list[float] | None, limit: int = 8,
                    *, include_past: bool = False, include_archived: bool = False,
                    mark: bool = True, window: tuple | None = None,
                    mode: str | None = None, rerank: bool | None = None):
    """Hybrid search: vector AND full-text, merged by rank.

    By default, only the current memory: neither superseded nor archived.
    `include_past` also brings back what was true and no longer is — this is
    what makes it possible to answer "what did I think before?".
    `include_archived` brings back the memories set aside.
    `mark` records the access (fuel for active forgetting); disable it when
    the caller reranks the candidates and marks the ones it keeps itself.
    `window` (start, end): a period computed in code from the question
    (temporal.cues); it adds a targeted search on that period, merged with the
    others — it excludes nothing.
    `mode`: 'hybrid' or 'vector' (default: config.SEARCH_MODE).
    `rerank`: None follows the configuration (PENSINE_RERANKER), False skips it.

    Without embeddings, full-text alone; without migration 013, the vector
    alone, or the old ILIKE as a last resort.
    """
    import psycopg

    from . import retrieval

    mode = mode or config.SEARCH_MODE
    where, params = _search_filters(include_past, include_archived)

    if mode != "hybrid":
        if embedding is not None:
            rows = vector_candidates(conn, embedding, limit, where, params)
        else:
            rows = _ilike_candidates(conn, query, limit, where, params)
    else:
        pool = max(50, 2 * limit)
        words = retrieval.terms(query)
        lists = []
        if embedding is not None:
            lists.append(vector_candidates(conn, embedding, pool, where, params))
        lexical_ok = True
        try:
            with conn.transaction():
                lists.append(lexical_candidates(conn, words, pool, where, params))
        except psycopg.errors.UndefinedColumn:
            lexical_ok = False  # migration 013 missing: do without
        if window:
            # the period named by the question: its best candidates enter the
            # fusion, those from elsewhere are not discarded
            w_where, w_params = _search_filters(include_past, include_archived, window)
            if embedding is not None:
                lists.append(vector_candidates(conn, embedding, pool, w_where, w_params))
            if lexical_ok and words:
                with conn.transaction():
                    lists.append(lexical_candidates(conn, words, pool, w_where, w_params))
        if embedding is None and not lexical_ok:
            lists.append(_ilike_candidates(conn, query, limit, where, params))
        weights = [retrieval.VECTOR_WEIGHT if lst and lst[0].get("distance") is not None
                   else 1.0 for lst in lists]
        rows = retrieval.fuse([lst for lst in lists if lst],
                              weights=[w for w, lst in zip(weights, lists) if lst])
        if rerank is not False:
            rows = retrieval.rerank(query, rows)
        rows = rows[:limit]
    if rows and mark:
        mark_accessed(conn, [r["id"] for r in rows])
    return rows


def present_knowledge(conn, embeddings_list: list, per_item: int = 5, cap: int = 40):
    """What is true today and resembles what is coming in.

    Given to nightly consolidation so that it can say "this replaces that".
    Without this context, it only saw the day: information from June that
    became false in October stayed true forever.
    Without embeddings, we fall back on the most recent present memories.
    """
    present = """superseded_by IS NULL AND archived_at IS NULL
                 AND (valid_to IS NULL OR valid_to > now()) AND valid_from <= now()"""
    seen: dict[int, dict] = {}
    vectors = [v for v in embeddings_list if v is not None]
    for v in vectors:
        for r in conn.execute(
            f"""SELECT id, type, content, valid_from FROM memories
                WHERE {present} AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector LIMIT %s""",
            (str(list(v)), per_item),
        ).fetchall():
            seen.setdefault(r["id"], r)
            if len(seen) >= cap:
                return list(seen.values())
    if not vectors:
        return conn.execute(
            f"""SELECT id, type, content, valid_from FROM memories
                WHERE {present} ORDER BY valid_from DESC, id DESC LIMIT %s""",
            (cap,),
        ).fetchall()
    return list(seen.values())


def mark_accessed(conn, ids: list[int]) -> None:
    """An effective recall reinforces: it slows the active forgetting of these memories."""
    if ids:
        conn.execute(
            """
            UPDATE memories
            SET access_count = access_count + 1, last_accessed_at = now()
            WHERE id = ANY(%s)
            """,
            (ids,),
        )


def chapters(conn) -> list[dict]:
    """Starts and ends of life chapters, in order."""
    return conn.execute(
        """SELECT name, at_date, kind FROM landmarks
           WHERE kind IN ('chapter_start', 'chapter_end') ORDER BY at_date, id"""
    ).fetchall()


def landmarks(conn) -> list[dict]:
    """All the named landmarks: the question can refer to them ("before X")."""
    return conn.execute("SELECT name, at_date, kind FROM landmarks ORDER BY at_date").fetchall()


def memory_snippets(conn, ids: list[int]) -> dict[int, str]:
    """Short content of a few memories, to say "replaced by …"."""
    if not ids:
        return {}
    return {r["id"]: r["content"] for r in conn.execute(
        "SELECT id, content FROM memories WHERE id = ANY(%s)", (sorted(set(ids)),)
    ).fetchall()}


def get_memory(conn, memory_id: int):
    return conn.execute(
        """SELECT id, type, content, confidence, importance, valid_from, valid_to,
                  superseded_by, archived_at, source_event_ids
           FROM memories WHERE id = %s""",
        (memory_id,),
    ).fetchone()


def close_memory(conn, memory_id: int, *, ended_at, reason: str,
                 successor_id: int | None = None) -> None:
    """Close a memory: it was true until `ended_at`. Never erased."""
    conn.execute(
        """
        UPDATE memories
        SET valid_to = COALESCE(LEAST(valid_to, %s), %s),
            superseded_by = COALESCE(%s, superseded_by),
            revised_at = now(), revision_note = %s
        WHERE id = %s
        """,
        (ended_at, ended_at, successor_id, reason, memory_id),
    )


def set_archived(conn, memory_id: int, *, archived: bool, reason: str) -> None:
    """Set a memory aside (or bring it back), without touching its truth."""
    conn.execute(
        """
        UPDATE memories
        SET archived_at = CASE WHEN %s THEN now() ELSE NULL END,
            revised_at = now(),
            revision_note = COALESCE(NULLIF(%s, ''), revision_note)
        WHERE id = %s
        """,
        (archived, reason, memory_id),
    )


def recent_memories(conn, limit: int = 8):
    """The most recent live memories, by validity date.

    Vector search sorts by resemblance and the mirror by importance: neither
    says "here is what is new". Without this view, fresh but modest memories
    stayed invisible. Pure read: it does not mark access, it is not a recall.
    """
    return conn.execute(
        """
        SELECT id, type, content, valid_from, source_event_ids
        FROM memories
        WHERE superseded_by IS NULL
        ORDER BY valid_from DESC, id DESC
        LIMIT %s
        """,
        (limit,),
    ).fetchall()


# Actions by which an agent reads memory (not those where it writes to it).
READ_ACTIONS = ("recall", "mirror", "curate", "listen", "memory_card", "timeline")


def agent_reads(conn, limit: int = 200):
    """What agents have read, from most recent to oldest.

    Market agents keep a memory you cannot read. Here, the opposite: every
    read is logged, and that log can be consulted. The memories read are
    resolved to text; a memory that has since disappeared stays listed by its
    identifier rather than erasing the trace.
    """
    rows = conn.execute(
        """
        SELECT at, action, detail FROM audit_log
        WHERE actor = 'mcp' AND action = ANY(%s)
        ORDER BY at DESC LIMIT %s
        """,
        (list(READ_ACTIONS), limit),
    ).fetchall()
    ids = sorted({i for r in rows for i in ((r["detail"] or {}).get("memory_ids") or [])})
    contents = {}
    if ids:
        contents = {m["id"]: m["content"] for m in conn.execute(
            "SELECT id, content FROM memories WHERE id = ANY(%s)", (ids,)
        ).fetchall()}
    return [
        {"at": r["at"], "action": r["action"], "detail": r["detail"] or {},
         "memories": [{"id": i, "content": contents.get(i)}
                      for i in ((r["detail"] or {}).get("memory_ids") or [])]}
        for r in rows
    ]


def source_events(conn, event_ids: list[int]):
    """Original fragments (depth=source): events + attached media.
    A forgotten deposit comes back with an empty payload and `forgotten=True`."""
    if not event_ids:
        return []
    return shred.open_rows(conn.execute(
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
    ).fetchall())
