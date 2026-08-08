"""Promotion épisodique → sémantique : ce qui se répète devient ce qu'on sait.

Consolidation systémique. Un épisode raconte une fois ; quand plusieurs
épisodes anciens disent la même chose, le motif qu'ils dessinent est une
connaissance durable — et cette connaissance n'existait nulle part dans le
système, qui figeait le type d'une mémoire au moment de l'extraction.

Ce que ce module ne fait pas, volontairement :

    il ne supprime aucun épisode. Le gist s'ajoute, il ne remplace pas.
    L'abstraction peut être fausse ; les épisodes, eux, sont attestés. Les
    garder permet de la corriger plus tard, et de répondre « à cause de quoi ? »

    il n'invente pas d'affect. La charge du gist est la moyenne de ce qui a
    réellement été ressenti dans les épisodes — calculée en code, pas devinée
    par le modèle.

Traçabilité : le gist hérite de l'union des events sources de ses épisodes, et
un lien `gist` le rattache à chacun d'eux. La chaîne jusqu'au substrat reste
entière.
"""

import json
from pathlib import Path

from . import affect, embeddings, links, llm

PROMPT_PATH = (Path(__file__).resolve().parent.parent
               / "consolidation" / "prompts" / "gist.md")

# Fenêtre de maturation : on n'abstrait pas le mois en cours. Un motif se juge
# avec du recul — trop tôt, on fige une coïncidence en trait de caractère.
MATURATION_DAYS = 30

# Distance cosinus max entre la graine et un épisode du même groupe. Au-delà,
# ce ne sont plus des variantes d'une même chose.
MAX_DISTANCE = 0.35

# Trois occurrences font un motif. Deux font une coïncidence.
MIN_EPISODES = 3
MAX_EPISODES = 12

# Par nuit : l'abstraction est lente, comme dans un cerveau.
MAX_CLUSTERS_PER_NIGHT = 3

_UNGISTED = """
    NOT EXISTS (SELECT 1 FROM memory_links l
                WHERE l.kind = 'gist'
                  AND (l.source_id = m.id OR l.target_id = m.id))
"""


def _seed(conn, skip: list[int]):
    """Le plus ancien épisode mûr qui n'a pas encore donné lieu à abstraction.

    `skip` écarte les graines déjà essayées cette nuit et restées trop
    isolées. Sans cela un épisode solitaire, éternellement le plus ancien
    non abstrait, bloquerait toute promotion ultérieure.
    """
    return conn.execute(
        f"""
        SELECT m.id, m.content, m.embedding
        FROM memories m
        WHERE m.type = 'episodic' AND m.superseded_by IS NULL
          AND m.embedding IS NOT NULL
          AND m.valid_from < now() - INTERVAL '{MATURATION_DAYS} days'
          AND {_UNGISTED}
          AND NOT (m.id = ANY(%s))
        ORDER BY m.valid_from
        LIMIT 1
        """,
        (skip,),
    ).fetchone()


def _cluster(conn, seed) -> list[dict]:
    """La graine et ses proches — les épisodes qui parlent de la même chose."""
    rows = conn.execute(
        f"""
        SELECT m.id, m.content, m.valence, m.arousal, m.importance,
               m.valid_from, m.source_event_ids
        FROM memories m
        WHERE m.type = 'episodic' AND m.superseded_by IS NULL
          AND m.embedding IS NOT NULL
          AND m.valid_from < now() - INTERVAL '{MATURATION_DAYS} days'
          AND {_UNGISTED}
          AND m.embedding <=> %s::vector <= %s
        ORDER BY m.embedding <=> %s::vector
        LIMIT %s
        """,
        (seed["embedding"], MAX_DISTANCE, seed["embedding"], MAX_EPISODES),
    ).fetchall()
    return [dict(r) for r in rows]


def _mean_affect(episodes: list[dict]) -> tuple[float | None, float | None]:
    """Charge du gist = moyenne de ce qui a été ressenti, pas une invention.

    Les épisodes sans affect connu ne comptent pas dans la moyenne : ils ne
    tirent pas vers le neutre, ils s'abstiennent.
    """
    def mean(key: str) -> float | None:
        vals = [e[key] for e in episodes if e.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    return mean("valence"), mean("arousal")


def _abstract(episodes: list[dict], owner: str, constitution: str) -> dict | None:
    """Demande l'abstraction au modèle. `None` si aucun motif ne se dégage."""
    payload = json.dumps(
        [{"content": e["content"], "quand": str(e["valid_from"].date())}
         for e in episodes],
        ensure_ascii=False,
    )
    prompt = (PROMPT_PATH.read_text(encoding="utf-8")
              .replace("{{OWNER}}", owner)
              .replace("{{CONSTITUTION}}", constitution)
              .replace("{{EPISODES}}", payload))
    out = llm.extract_json(llm.complete(prompt))
    if not isinstance(out, dict):
        return None
    text = out.get("gist")
    if not text or not str(text).strip():
        return None   # « aucun motif » est une réponse valide, pas un échec
    return {"content": str(text).strip(),
            "confidence": float(out.get("confidence", 0.5))}


def _write(conn, gist: dict, episodes: list[dict]) -> int:
    """Écrit la connaissance sémantique et la rattache à ses épisodes."""
    valence, arousal = _mean_affect(episodes)
    sources = sorted({eid for e in episodes
                      for eid in (e["source_event_ids"] or [])})
    vec = embeddings.embed(gist["content"], kind="document")
    row = conn.execute(
        """
        INSERT INTO memories (type, content, embedding, confidence, importance,
                              valence, arousal, valid_from, source_event_ids)
        VALUES ('semantic', %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (gist["content"], str(list(vec)) if vec else None,
         gist["confidence"],
         max(e["importance"] for e in episodes),
         valence, arousal,
         min(e["valid_from"] for e in episodes),   # vrai depuis le premier épisode
         sources),
    ).fetchone()

    # Un lien `gist` par épisode : il marque l'épisode comme abstrait (il ne
    # repassera pas) et permet de remonter du général au vécu qui l'a produit.
    for e in episodes:
        links.link(conn, [row["id"], e["id"]], kind="gist")
    return row["id"]


def promote(conn, owner: str, constitution: str) -> dict:
    """Un tour de consolidation systémique. Renvoie ce qui a été abstrait.

    Une graine trop isolée, ou un groupe où le modèle ne voit aucun motif, est
    écartée pour cette nuit seulement : rien ne la marque en base. Elle
    repassera quand d'autres épisodes proches auront mûri — l'abstraction
    attend son heure plutôt que de forcer un motif.
    """
    written: list[int] = []
    skipped: list[int] = []
    for _ in range(MAX_CLUSTERS_PER_NIGHT):
        seed = _seed(conn, skipped)
        if seed is None:
            break
        episodes = _cluster(conn, seed)
        if len(episodes) < MIN_EPISODES:
            skipped.append(seed["id"])
            continue
        gist = _abstract(episodes, owner, constitution)
        if gist is None:
            # « aucun motif » est une réponse valide du modèle, pas un échec
            skipped.append(seed["id"])
            continue
        written.append(_write(conn, gist, episodes))
    return {"gists_written": len(written), "clusters_skipped": len(skipped)}
