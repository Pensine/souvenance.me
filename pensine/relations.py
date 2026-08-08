"""État des liens : ce qui bouge entre deux personnes, et dans quel sens.

Le graphe temporel dit ce qui *est* — travaille chez X, habite à Y. Il ne dit
pas ce qui se passe entre deux personnes : une proximité qui se refroidit, une
tension qui monte, un lien qu'on croyait perdu et qui se rallume.

Deux axes, pour la même raison que la charge d'un souvenir :

    closeness   0 (distant) … 1 (intime)      — l'intensité du lien
    valence    -1 (tendu) … +1 (chaleureux)   — sa couleur

Une famille peut être proche et tendue ; un vieil ami perdu de vue, lointain et
chaleureux. Un curseur unique confondrait les deux.

Le point n'est pas l'état courant, c'est la **trajectoire**. On garde donc une
suite d'états datés : le nouveau ferme le précédent, il ne l'écrase pas. « Où
en est cette relation » se lit sur le dernier ; « qu'est-ce qui a changé » se
lit sur les deux derniers.
"""

# En deçà, la variation relève du bruit d'estimation : deux nuits de
# consolidation sur les mêmes faits ne donnent jamais exactement le même
# chiffre, et signaler ce frémissement comme une évolution serait mentir.
SIGNIFICANT_DELTA = 0.15


def set_state(conn, entity_id: int, *, closeness=None, valence=None,
              note: str = "", confidence: float = 0.5,
              valid_from=None, source_event_ids=None) -> int | None:
    """Enregistre un nouvel état et ferme le précédent.

    Renvoie None si aucun axe n'est renseigné : un état vide n'apprend rien et
    n'a pas à occuper une ligne dans l'histoire de la relation.
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
    """Les états successifs, du plus récent au plus ancien."""
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
    """Ce qui a changé entre les deux derniers états, en clair.

    `states` est la sortie de `history` (plus récent d'abord). Renvoie None
    quand il n'y a qu'un état, ou quand rien n'a bougé de façon significative —
    « rien n'a changé » n'est pas une nouvelle et n'a pas à être dit.
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
    """État courant du lien et son évolution, ou None si rien n'est connu."""
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
    """Applique les états de relation extraits par la consolidation.

    `items` : [{entity, closeness?, valence?, note?, confidence?}]
    `entity_ids` : noms en minuscules → id, tels que le graphe les a résolus.
    Une entité inconnue est ignorée : on n'invente pas de personne pour lui
    attribuer un climat.
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
    """Hors bornes ou non numérique : None. On refuse plutôt que de ramener
    dans l'intervalle — une valeur inventée sur un lien humain est pire que
    pas de valeur du tout."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return val if lo <= val <= hi else None
