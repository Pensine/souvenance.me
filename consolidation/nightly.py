#!/usr/bin/env python3
"""Consolidation nocturne (03:00) — hippocampe → cortex.

Orchestration en code, intelligence via l'adaptateur compute (claude CLI
sous abonnement, ou API — pensine/llm.py). Étapes :
  1. percepteurs actifs (agenda ICS, mails si configurés) → events,
     filtrés par le gouverneur constitutionnel
  2. pipeline média : WhisperX, EXIF, vision, Docling sur les dépôts en attente
  3. rejeu du jour : events non consolidés (médias inclus) → extraction,
     généralisation, scoring, contradictions
  4. écriture des memories + embeddings BGE-M3
  5. décroissance d'oubli (récence × fréquence d'accès × importance)

Si la couche intelligente casse : rien n'est perdu, les events s'accumulent,
la consolidation rattrape à la reprise. Le pire scénario est une pause.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import (affect, config, db, embeddings, gist, graph,  # noqa: E402
                     links, llm, percepteurs, relations)
from pensine.governor import Governor  # noqa: E402

import media_pipeline  # noqa: E402

PROMPT = (Path(__file__).parent / "prompts" / "nightly.md").read_text(encoding="utf-8")

MEMORY_TYPES = {"episodic", "semantic", "procedural", "reflection"}


def perceive(conn, governor: Governor) -> int:
    """Étape 1 — les percepteurs tirent, le gouverneur filtre, le log s'append."""
    candidates, errors = percepteurs.pull_all()
    for name, err in errors:
        db.audit(conn, "consolidation", "percepteur_error",
                 {"percepteur": name, "error": err[:300]})
    kept = governor.filter_events(conn, candidates)
    written = 0
    for e in kept:
        if db.append_event(conn, source=e["source"], kind=e["kind"],
                           occurred_at=e["occurred_at"], payload=e["payload"]):
            written += 1
    return written



def _slim(e: dict) -> dict:
    """Compresse les gros payloads (imports de conversations) pour le prompt :
    le log garde tout, la consolidation voit un condensé suffisant."""
    payload = e["payload"] if isinstance(e["payload"], dict) else json.loads(e["payload"])
    if "messages" in payload and isinstance(payload["messages"], list):
        text, budget = [], 4000
        for m in payload["messages"]:
            line = f"{m.get('role', '?')}: {m.get('text', '')}"[:600]
            budget -= len(line)
            if budget < 0:
                text.append(f"… ({payload.get('message_count')} messages au total)")
                break
            text.append(line)
        payload = {**{k: v for k, v in payload.items() if k != "messages"},
                   "condense": "\n".join(text)}
    return {**e, "payload": payload}


def consolidate(conn, governor: Governor, events) -> dict:
    events_json = json.dumps(
        [{**_slim(dict(e)), "occurred_at": e["occurred_at"].isoformat()}
         for e in events],
        ensure_ascii=False, default=str,
    )
    prompt = (PROMPT
              .replace("{{OWNER}}", config.OWNER_NAME)
              .replace("{{CONSTITUTION}}", governor.constitution_text())
              .replace("{{TODAY}}", datetime.now(timezone.utc).date().isoformat())
              .replace("{{EVENTS}}", events_json))
    raw = llm.complete(prompt)
    out = llm.extract_json(raw)
    if isinstance(out, list):  # compat : ancien format (tableau de memories)
        out = {"memories": out, "entities": [], "relations": []}
    event_ids = [e["id"] for e in events]
    written = write_memories(conn, out.get("memories") or [])
    posed = link_episodes(conn, written)
    g = graph.ingest(conn, out.get("entities") or [], out.get("relations") or [],
                     event_ids)
    states = relations.ingest(conn, out.get("relation_states") or [],
                              g.pop("entity_ids", {}), event_ids)
    db.mark_examined(conn, event_ids, {m["id"] for m in written})
    return {"memories_written": len(written), "links_posed": posed,
            "relation_states": states, **g}



def write_memories(conn, items: list[dict]) -> list[dict]:
    """Écrit les mémoires et renvoie leur id + events sources.

    Les ids servent à poser les liens du même épisode : deux mémoires nées du
    même événement se rappelleront l'une l'autre (voir pensine/links.py).
    """
    written: list[dict] = []
    for m in items:
        if m.get("type") not in MEMORY_TYPES or not m.get("content"):
            continue  # sortie LLM invalide : on écarte, le brut reste dans events
        vec = embeddings.embed(m["content"], kind="document")
        valence, arousal = affect.parse(m)
        sources = m.get("source_event_ids") or []
        row = conn.execute(
            """
            INSERT INTO memories (type, content, embedding, confidence, importance,
                                  valence, arousal,
                                  valid_from, valid_to, source_event_ids)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (m["type"], m["content"], str(list(vec)) if vec else None,
             float(m.get("confidence", 0.5)), float(m.get("importance", 0.5)),
             valence, arousal,
             m.get("valid_from") or datetime.now(timezone.utc),
             m.get("valid_to"), sources),
        ).fetchone()
        written.append({"id": row["id"], "source_event_ids": sources})
    return written


def link_episodes(conn, written: list[dict]) -> int:
    """Relie les mémoires qui partagent un événement source.

    Un événement produit souvent plusieurs mémoires — un fait, une réflexion,
    une relation. Elles appartiennent au même moment vécu ; les lier permet à
    l'une de ramener les autres, même si la question ne ressemble qu'à une
    seule d'entre elles.
    """
    by_event: dict[int, list[int]] = {}
    for m in written:
        for eid in m["source_event_ids"]:
            by_event.setdefault(eid, []).append(m["id"])
    posed = 0
    for ids in by_event.values():
        if len(ids) > 1:
            posed += links.link(conn, ids, kind="shared_event")
    return posed


def forgetting_decay(conn) -> None:
    """Oubli actif : décroissance freinée par la charge affective ET par le type.

    Deux modulations, chacune tirée d'un effet documenté.

    L'intensité d'abord : un souvenir chargé résiste à l'oubli — c'est l'un des
    effets les mieux établis de la mémoire humaine. Un arousal inconnu (NULL)
    prend le taux de base ; l'ignorance ne protège ni ne pénalise.

    Le type ensuite : ce qui périme et ce qui persiste ne sont pas la même
    chose. Un épisode est un *état* — daté, remplaçable, il s'efface. Une
    connaissance sémantique ou une heuristique procédurale est une
    *disposition* — elle tient. Faire décroître un trait de caractère au même
    rythme qu'un déjeuner était le défaut de la version précédente.

        épisodique   0,995 → ~16 % d'importance après un an sans rappel
        réflexion    0,997 → ~33 %
        sémantique   0,999 → ~69 %
        procédural   0,999 → ~69 %

    On ne supprime rien : l'importance baisse, la mémoire reste. Ce qui se
    répète, en revanche, remonte d'un cran — voir pensine/gist.py.
    """
    conn.execute(
        """
        UPDATE memories
        -- Plafond strictement < 1 : sans lui, une disposition très chargée
        -- verrait son importance croître à chaque nuit au lieu de décroître.
        SET importance = GREATEST(0.05, importance * LEAST(0.9995,
            CASE type
                WHEN 'semantic'   THEN 0.999
                WHEN 'procedural' THEN 0.999
                WHEN 'reflection' THEN 0.997
                ELSE 0.995
            END
            + 0.004 * COALESCE(arousal, 0.0)))
        WHERE superseded_by IS NULL
          AND (last_accessed_at IS NULL OR last_accessed_at < now() - INTERVAL '30 days')
          AND valid_from < now() - INTERVAL '30 days'
        """
    )


def main() -> None:
    governor = Governor()
    with db.connection() as conn:
        perceived = perceive(conn, governor)
        media_report = media_pipeline.process_pending(conn)
        conn.commit()  # les acquis (events, transcripts) survivent à un échec LLM

        events = db.unconsolidated_events(conn)
        if not events:
            db.audit(conn, "consolidation", "nightly_noop",
                     {"perceived": perceived})
            conn.commit()
            print("Rien à consolider.")
            return

        try:
            result = consolidate(conn, governor, events)
        except llm.LLMUnavailable as exc:
            db.audit(conn, "consolidation", "nightly_paused", {"reason": str(exc)})
            conn.commit()
            print(f"Consolidation en pause ({exc}) — les events s'accumulent, "
                  "rattrapage au prochain cycle.")
            return

        forgetting_decay(conn)
        links.decay(conn)
        promoted = gist.promote(conn, config.OWNER_NAME, governor.constitution_text())
        db.audit(conn, "consolidation", "nightly", {
            "perceived": perceived,
            "media_done": len(media_report["done"]),
            "media_skipped": len(media_report["skipped"]),
            "events": len(events),
            **result,
            **promoted,
        })
        conn.commit()
        print(f"{perceived} events perçus, {len(media_report['done'])} médias "
              f"traités, {len(events)} events rejoués → "
              f"{result['memories_written']} mémoires, "
              f"{result['relations_added']} arêtes de graphe.")


if __name__ == "__main__":
    main()
