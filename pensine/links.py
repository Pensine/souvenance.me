"""Links between memories — associative, step-by-step recall.

A vector search finds what *resembles* the question. A human memory also
surfaces what does not resemble it but is connected to it: the name of a
place brings back a conversation that never mentions it, a smell brings back a
year. That is what this module adds — a network on top of the index.

Two mechanisms, borrowed from the same principle:

    lay        two memories born from the same event are linked outright
               (same episode)
    reinforce  two memories that surface together see their link grow
               — what fires together wires together

And a counterpart: a link that is not reactivated weakens and then disappears.
Links are a projection, recomputable from the log; deleting them costs nothing
irreplaceable, and keeping them all would make the table grow as n².
"""

from itertools import combinations

# A link is born weak and strengthens in diminishing steps: the first
# co-activations matter more than the thousandth, like a learning curve.
INITIAL_STRENGTH = 0.1
REINFORCE_GAIN = 0.15
MAX_STRENGTH = 1.0

# Nightly decay, after 30 days without reactivation. A link laid once and never
# replayed disappears in ~2 months; a link at full strength lasts ~6 months.
# The gap is the point: what gets replayed stays, the rest fades, and
# "associated" keeps meaning something.
DECAY_RATE = 0.98
PRUNE_BELOW = 0.05

# Associative expansion: beyond this, recall dilutes instead of enriching.
DEFAULT_HOPS = 6
MIN_STRENGTH_TO_FOLLOW = 0.15


def _pairs(memory_ids):
    """Canonical pairs (a < b), no duplicates or self-loops."""
    unique = sorted({int(i) for i in memory_ids})
    return list(combinations(unique, 2))


def link(conn, memory_ids, kind: str = "shared_event") -> int:
    """Link all the memories to one another. Reinforces if the link already exists.

    Used at consolidation: memories extracted from the same event belong to
    the same episode and will recall one another.
    """
    pairs = _pairs(memory_ids)
    if not pairs:
        return 0
    for a, b in pairs:
        conn.execute(
            """
            INSERT INTO memory_links (source_id, target_id, kind, strength)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_id, target_id) DO UPDATE
            SET strength = LEAST(%s, memory_links.strength + %s),
                last_reinforced_at = now()
            """,
            (a, b, kind, INITIAL_STRENGTH, MAX_STRENGTH, REINFORCE_GAIN),
        )
    return len(pairs)


def reinforce(conn, memory_ids) -> int:
    """Reinforce the links between memories that have just surfaced together.

    Only called on the search results themselves, never on the neighbors
    brought back by association: we know the question activated the former, we
    do not know whether the latter were useful. Reinforcing both would densify
    the network without evidence.
    """
    return link(conn, memory_ids, kind="co_recall")


def expand(conn, seed_ids, limit: int = DEFAULT_HOPS, exclude=None):
    """Associative neighbors of the memories found — a single hop.

    Returns the memories linked to the seeds, most strongly linked first,
    excluding those already surfaced. This is step-by-step recall: these
    memories do not necessarily resemble the question, they are tied to it by
    experience.
    """
    seeds = [int(i) for i in seed_ids]
    if not seeds or limit <= 0:
        return []
    excluded = set(seeds) | {int(i) for i in (exclude or [])}
    return conn.execute(
        """
        SELECT m.id, m.type, m.content, m.confidence, m.importance,
               m.valence, m.arousal, m.valid_from, m.valid_to,
               m.source_event_ids, NULL::real AS distance,
               MAX(l.strength) AS lien
        FROM memory_links l
        JOIN memories m ON m.id = CASE
            WHEN l.source_id = ANY(%s) THEN l.target_id ELSE l.source_id END
        WHERE (l.source_id = ANY(%s) OR l.target_id = ANY(%s))
          AND l.strength >= %s
          AND m.superseded_by IS NULL
          AND NOT (m.id = ANY(%s))
        GROUP BY m.id, m.type, m.content, m.confidence, m.importance,
                 m.valence, m.arousal, m.valid_from, m.valid_to, m.source_event_ids
        ORDER BY lien DESC, m.importance DESC
        LIMIT %s
        """,
        (seeds, seeds, seeds, MIN_STRENGTH_TO_FOLLOW, sorted(excluded), limit),
    ).fetchall()


def decay(conn) -> None:
    """A link that is not reactivated weakens, then disappears.

    Without this the network would only densify: everything would end up
    linked to everything, and "associated" would lose its meaning. Forgetting
    links is what keeps association informative.
    """
    conn.execute(
        "UPDATE memory_links SET strength = strength * %s "
        "WHERE last_reinforced_at IS NULL "
        "   OR last_reinforced_at < now() - INTERVAL '30 days'",
        (DECAY_RATE,),
    )
    conn.execute("DELETE FROM memory_links WHERE strength < %s", (PRUNE_BELOW,))
