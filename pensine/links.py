"""Liaisons entre souvenirs — le rappel de proche en proche.

Une recherche vectorielle trouve ce qui *ressemble* à la question. Une mémoire
humaine remonte aussi ce qui n'y ressemble pas mais s'y rattache : le nom d'un
lieu ramène une conversation qui n'en parle pas, une odeur ramène une année.
C'est ce que ce module ajoute — un réseau par-dessus l'index.

Deux mécanismes, empruntés au même principe :

    pose      deux mémoires nées du même événement sont liées d'office
              (même épisode)
    renforce  deux mémoires qui remontent ensemble voient leur lien grossir
              — ce qui s'active ensemble se lie

Et une contrepartie : un lien qu'on ne réactive pas s'affaiblit puis disparaît.
Les liens sont une projection, recalculable depuis le log ; les supprimer ne
coûte rien d'irremplaçable, et les garder tous ferait croître la table en n².
"""

from itertools import combinations

# Un lien naît faible et se renforce par paliers décroissants : les premières
# co-activations comptent plus que la millième, comme une courbe d'apprentissage.
INITIAL_STRENGTH = 0.1
REINFORCE_GAIN = 0.15
MAX_STRENGTH = 1.0

# Décroissance nocturne, après 30 jours sans réactivation. Un lien posé une
# fois et jamais rejoué disparaît en ~2 mois ; un lien porté à pleine force
# tient ~6 mois. L'écart est le point : ce qu'on rejoue reste, le reste
# s'efface, et « associé » continue de vouloir dire quelque chose.
DECAY_RATE = 0.98
PRUNE_BELOW = 0.05

# Expansion associative : au-delà, le rappel se dilue au lieu de s'enrichir.
DEFAULT_HOPS = 6
MIN_STRENGTH_TO_FOLLOW = 0.15


def _pairs(memory_ids):
    """Paires canoniques (a < b), sans doublon ni boucle."""
    unique = sorted({int(i) for i in memory_ids})
    return list(combinations(unique, 2))


def link(conn, memory_ids, kind: str = "shared_event") -> int:
    """Lie toutes les mémoires entre elles. Renforce si le lien existe déjà.

    Utilisé à la consolidation : les mémoires extraites d'un même événement
    appartiennent au même épisode et se rappelleront l'une l'autre.
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
    """Renforce les liens entre des mémoires qui viennent de remonter ensemble.

    N'est appelé que sur les résultats de la recherche elle-même, jamais sur
    les voisins ramenés par association : on sait que la question a activé les
    premiers, on ne sait pas si les seconds ont servi. Renforcer les deux
    densifierait le réseau sans preuve.
    """
    return link(conn, memory_ids, kind="co_recall")


def expand(conn, seed_ids, limit: int = DEFAULT_HOPS, exclude=None):
    """Voisins associatifs des mémoires trouvées — un seul saut.

    Renvoie les mémoires liées aux graines, les plus fortement liées d'abord,
    en excluant celles déjà remontées. C'est le rappel de proche en proche :
    ces souvenirs ne ressemblent pas forcément à la question, ils lui sont
    rattachés par l'expérience.
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
    """Un lien qu'on ne réactive pas s'affaiblit, puis disparaît.

    Sans cela le réseau ne ferait que densifier : tout finirait relié à tout,
    et « associé » perdrait son sens. L'oubli des liens est ce qui garde
    l'association informative.
    """
    conn.execute(
        "UPDATE memory_links SET strength = strength * %s "
        "WHERE last_reinforced_at IS NULL "
        "   OR last_reinforced_at < now() - INTERVAL '30 days'",
        (DECAY_RATE,),
    )
    conn.execute("DELETE FROM memory_links WHERE strength < %s", (PRUNE_BELOW,))
