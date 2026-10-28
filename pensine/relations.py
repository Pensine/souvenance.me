"""State of relationships: what moves between two people, and in which direction.

The temporal graph says what *is* — works at X, lives in Y. It does not say
what happens between two people: a closeness that cools, a tension that
rises, a bond believed lost that rekindles.

Two axes, for the same reason as a memory's charge:

    closeness   0 (distant) … 1 (intimate)    — the intensity of the bond
    valence    -1 (tense) … +1 (warm)         — its color

A family can be close and tense; an old friend lost from view, distant and
warm. A single slider would conflate the two.

The point is not the current state, it is the **trajectory**. So we keep a
series of dated states: the new one closes the previous one, it does not
overwrite it. "Where does this relationship stand" is read from the latest;
"what has changed" is read from the last two.

The French keys and phrasings of `trajectory()` / `describe()` (`proximite`,
`climat`, `evolution`, "s'est rapprochée"…) are recall output and stay French.
"""

# Below this, the variation is estimation noise: two nights of consolidation
# on the same facts never give exactly the same number, and flagging that
# flutter as an evolution would be lying.
SIGNIFICANT_DELTA = 0.15


def set_state(conn, entity_id: int, *, closeness=None, valence=None,
              note: str = "", confidence: float = 0.5,
              valid_from=None, source_event_ids=None) -> int | None:
    """Record a new state and close the previous one.

    Returns None if neither axis is given: an empty state teaches nothing and
    has no business taking up a row in the relationship's history.
    """
    if closeness is None and valence is None:
        return None
    conn.execute(
        """
        UPDATE relation_states SET valid_to = COALESCE(%s, now())
        WHERE entity_id = %s AND valid_to IS NULL
        """,
        (valid_from, entity_id),
    )
    row = conn.execute(
        """
        INSERT INTO relation_states (entity_id, closeness, valence, note,
                                     confidence, valid_from, source_event_ids)
        VALUES (%s, %s, %s, %s, %s, COALESCE(%s, now()), %s)
        RETURNING id
        """,
        (entity_id, closeness, valence, note.strip() or None, confidence,
         valid_from, source_event_ids or []),
    ).fetchone()
    return row["id"]


def history(conn, entity_id: int, limit: int = 12):
    """The successive states, from most recent to oldest."""
    return conn.execute(
        """
        SELECT closeness, valence, note, valid_from, valid_to
        FROM relation_states WHERE entity_id = %s
        ORDER BY valid_from DESC LIMIT %s
        """,
        (entity_id, limit),
    ).fetchall()


def _axis_trend(now, before, rising: str, falling: str) -> str | None:
    if now is None or before is None:
        return None
    delta = now - before
    if abs(delta) < SIGNIFICANT_DELTA:
        return None
    return rising if delta > 0 else falling


def trajectory(states) -> dict | None:
    """What changed between the last two states, in plain words.

    `states` is the output of `history` (most recent first). Returns None when
    there is only one state, or when nothing moved significantly —
    "nothing changed" is not news and need not be said.
    """
    if states is None or len(states) < 2:
        return None
    now, before = states[0], states[1]
    moves = [
        _axis_trend(now["closeness"], before["closeness"],
                    "s'est rapprochée", "s'est distendue"),
        _axis_trend(now["valence"], before["valence"],
                    "s'est réchauffée", "s'est tendue"),
    ]
    moves = [m for m in moves if m]
    if not moves:
        return None
    return {"evolution": " et ".join(moves),
            "depuis": before["valid_from"],
            "note": now["note"]}


def describe(conn, entity_id: int) -> dict | None:
    """Current state of the relationship and its evolution, or None if nothing is known."""
    states = history(conn, entity_id, limit=2)
    if not states:
        return None
    now = states[0]
    out: dict = {}
    if now["closeness"] is not None:
        out["proximite"] = round(float(now["closeness"]), 2)
    if now["valence"] is not None:
        out["climat"] = round(float(now["valence"]), 2)
    if now["note"]:
        out["note"] = now["note"]
    trend = trajectory(states)
    if trend:
        out["evolution"] = trend["evolution"]
    return out or None


def ingest(conn, items: list[dict], entity_ids: dict, event_ids: list[int]) -> int:
    """Apply the relationship states extracted by consolidation.

    `items`: [{entity, closeness?, valence?, note?, confidence?}]
    `entity_ids`: lowercase names → id, as the graph resolved them.
    An unknown entity is ignored: we do not invent a person in order to
    assign them a climate.
    """
    applied = 0
    for it in items or []:
        name = str(it.get("entity", "")).strip().lower()
        eid = entity_ids.get(name)
        if not eid:
            continue
        closeness = _clamp(it.get("closeness"), 0.0, 1.0)
        valence = _clamp(it.get("valence"), -1.0, 1.0)
        if set_state(conn, eid, closeness=closeness, valence=valence,
                     note=str(it.get("note") or ""),
                     confidence=float(it.get("confidence") or 0.5),
                     source_event_ids=event_ids):
            applied += 1
    return applied


def _clamp(raw, lo: float, hi: float) -> float | None:
    """Out of range or non-numeric: None. We refuse rather than clamp into the
    interval — an invented value on a human bond is worse than no value at all."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return val if lo <= val <= hi else None
