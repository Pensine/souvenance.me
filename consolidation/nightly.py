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

from pensine import config, db, embeddings, graph, llm, percepteurs  # noqa: E402
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


def unconsolidated_events(conn):
    """Events jamais cités par une mémoire — le « jour » à rejouer.
    Les médias transcrits/décrits sont joints : la consolidation voit le contenu."""
    return conn.execute(
        """
        SELECT e.id, e.occurred_at, e.source, e.kind, e.payload,
               m.transcript AS media_transcript, m.description AS media_description,
               m.exif AS media_exif
        FROM events e
        LEFT JOIN media m ON m.id = e.media_id
        WHERE NOT EXISTS (
            SELECT 1 FROM memories mm WHERE e.id = ANY(mm.source_event_ids)
        )
        -- un dépôt média attend son retraitement avant d'être consolidé
        AND (e.media_id IS NULL
             OR m.transcript IS NOT NULL OR m.description IS NOT NULL)
        ORDER BY e.occurred_at
        LIMIT 200
        """
    ).fetchall()


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
    n = write_memories(conn, out.get("memories") or [])
    g = graph.ingest(conn, out.get("entities") or [], out.get("relations") or [],
                     event_ids)
    return {"memories_written": n, **g}


def write_memories(conn, items: list[dict]) -> int:
    written = 0
    for m in items:
        if m.get("type") not in MEMORY_TYPES or not m.get("content"):
            continue  # sortie LLM invalide : on écarte, le brut reste dans events
        vec = embeddings.embed(m["content"], kind="document")
        conn.execute(
            """
            INSERT INTO memories (type, content, embedding, confidence, importance,
                                  valid_from, valid_to, source_event_ids)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (m["type"], m["content"], str(list(vec)) if vec else None,
             float(m.get("confidence", 0.5)), float(m.get("importance", 0.5)),
             m.get("valid_from") or datetime.now(timezone.utc),
             m.get("valid_to"), m.get("source_event_ids", [])),
        )
        written += 1
    return written


def forgetting_decay(conn) -> None:
    """Oubli actif : décroissance = récence × fréquence d'accès × importance.
    On ne supprime rien — on baisse l'importance ; la compression en gists
    des souvenirs anciens viendra dans une itération suivante."""
    conn.execute(
        """
        UPDATE memories
        SET importance = GREATEST(0.05, importance * 0.995)
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

        events = unconsolidated_events(conn)
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
        db.audit(conn, "consolidation", "nightly", {
            "perceived": perceived,
            "media_done": len(media_report["done"]),
            "media_skipped": len(media_report["skipped"]),
            "events": len(events),
            **result,
        })
        conn.commit()
        print(f"{perceived} events perçus, {len(media_report['done'])} médias "
              f"traités, {len(events)} events rejoués → "
              f"{result['memories_written']} mémoires, "
              f"{result['relations_added']} arêtes de graphe.")


if __name__ == "__main__":
    main()
