"""Episodic → semantic promotion: what repeats becomes what we know.

Systems consolidation. An episode tells something once; when several old
episodes say the same thing, the pattern they draw is durable knowledge — and
that knowledge existed nowhere in the system, which froze a memory's type at
extraction time.

What this module deliberately does not do:

    it deletes no episode. The gist is added, it does not replace. The
    abstraction may be wrong; the episodes, for their part, are attested.
    Keeping them allows correcting it later, and answering "because of what?"

    it does not invent affect. The gist's charge is the mean of what was
    actually felt in the episodes — computed in code, not guessed by the model.

Traceability: the gist inherits the union of its episodes' source events, and
a `gist` link ties it to each of them. The chain down to the substrate stays
intact.
"""

import json
from pathlib import Path

from . import affect, embeddings, links, llm

PROMPT_PATH = (Path(__file__).resolve().parent.parent
               / "consolidation" / "prompts" / "gist.md")

# Maturation window: the current month is not abstracted. A pattern is judged
# with hindsight — too early, a coincidence gets frozen into a character trait.
MATURATION_DAYS = 30

# Max cosine distance between the seed and an episode of the same group.
# Beyond it, they are no longer variants of the same thing.
MAX_DISTANCE = 0.35

# Three occurrences make a pattern. Two make a coincidence.
MIN_EPISODES = 3
MAX_EPISODES = 12

# Per night: abstraction is slow, as in a brain.
MAX_CLUSTERS_PER_NIGHT = 3

_UNGISTED = """
    NOT EXISTS (SELECT 1 FROM memory_links l
                WHERE l.kind = 'gist'
                  AND (l.source_id = m.id OR l.target_id = m.id))
"""


def _seed(conn, skip: list[int]):
    """The oldest mature episode that has not yet given rise to an abstraction.

    `skip` excludes the seeds already tried tonight that remained too
    isolated. Without it a lone episode, forever the oldest non-abstracted
    one, would block any later promotion.
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
    """The seed and its neighbors — the episodes that talk about the same thing."""
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
    """Gist charge = mean of what was felt, not an invention.

    Episodes with no known affect do not count in the mean: they do not pull
    toward neutral, they abstain.
    """
    def mean(key: str) -> float | None:
        vals = [e[key] for e in episodes if e.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    return mean("valence"), mean("arousal")


def _abstract(episodes: list[dict], owner: str, constitution: str) -> dict | None:
    """Ask the model for the abstraction. `None` if no pattern emerges."""
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
        return None   # "no pattern" is a valid answer, not a failure
    return {"content": str(text).strip(),
            "confidence": float(out.get("confidence", 0.5))}


def _write(conn, gist: dict, episodes: list[dict]) -> int:
    """Write the semantic knowledge and attach it to its episodes."""
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
         min(e["valid_from"] for e in episodes),   # true since the first episode
         sources),
    ).fetchone()

    # One `gist` link per episode: it marks the episode as abstracted (it will
    # not come up again) and lets you trace from the general back to the
    # lived experience that produced it.
    for e in episodes:
        links.link(conn, [row["id"], e["id"]], kind="gist")
    return row["id"]


def promote(conn, owner: str, constitution: str) -> dict:
    """One round of systems consolidation. Returns what was abstracted.

    A seed that is too isolated, or a group where the model sees no pattern, is
    set aside for tonight only: nothing marks it in the database. It will come
    up again when other nearby episodes have matured — abstraction bides its
    time rather than forcing a pattern.
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
            # "no pattern" is a valid model answer, not a failure
            skipped.append(seed["id"])
            continue
        written.append(_write(conn, gist, episodes))
    return {"gists_written": len(written), "clusters_skipped": len(skipped)}
