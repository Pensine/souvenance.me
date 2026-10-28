#!/usr/bin/env python3
"""Ingests a founding-interview transcript as events (phase 0).

Each session becomes an `interview/session` event; nightly consolidation
will extract the memories from it (biography, values, decision style).
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import db  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("transcript", type=Path, help="transcript text file")
    p.add_argument("--session", type=int, required=True, help="session number (1-4)")
    p.add_argument("--date", help="session date (ISO), default: now")
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
        print("Session already ingested (duplicate ignored).")
    else:
        print(f"Session {args.session} ingested (event {event_id}). "
              "Nightly consolidation will extract the memories from it.")


if __name__ == "__main__":
    main()
