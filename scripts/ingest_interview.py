#!/usr/bin/env python3
"""Ingère un transcript d'interview fondatrice comme events (phase 0).

Chaque session devient un event `interview/session` ; la consolidation
nocturne en extraira les mémoires (biographie, valeurs, style de décision).
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import db  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("transcript", type=Path, help="fichier texte du transcript")
    p.add_argument("--session", type=int, required=True, help="n° de session (1-4)")
    p.add_argument("--date", help="date de la session (ISO), défaut : maintenant")
    args = p.parse_args()

    text = args.transcript.read_text(encoding="utf-8")
    when = (datetime.fromisoformat(args.date) if args.date
            else datetime.now(timezone.utc))
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)

    with db.connection() as conn:
        event_id = db.append_event(
            conn, source="interview", kind="session", occurred_at=when,
            payload={"session": args.session, "transcript": text},
        )
        db.audit(conn, "mcp", "ingest_interview",
                 {"session": args.session, "event_id": event_id})
        conn.commit()

    if event_id is None:
        print("Session déjà ingérée (doublon ignoré).")
    else:
        print(f"Session {args.session} ingérée (event {event_id}). "
              "La consolidation nocturne en extraira les mémoires.")


if __name__ == "__main__":
    main()
