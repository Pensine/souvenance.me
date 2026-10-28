#!/usr/bin/env python3
"""Enrolment of a voiceprint — an EXPLICIT act (§8), never implicit.

Usage: enroll_speaker.py --name "First name" --kind person sample.wav
The sample: 30-60 s of clean, solo voice. The file is NOT kept (only the
192-d voiceprint is) — unless it also goes through Pensine."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import db  # noqa: E402
from pensine.graph import upsert_entity  # noqa: E402
from pensine.speakers import compute_voiceprint  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sample", type=Path, help="audio sample (wav/mp3/opus)")
    p.add_argument("--name", required=True, help="the person's name")
    p.add_argument("--kind", default="person")
    args = p.parse_args()

    if not args.sample.exists():
        sys.exit(f"Not found: {args.sample}")
    print(f"Computing {args.name}'s voiceprint…")
    vector = compute_voiceprint(args.sample)

    with db.connection() as conn:
        entity_id = upsert_entity(conn, args.name, args.kind)
        conn.execute(
            "INSERT INTO voiceprints (entity_id, embedding, sample_note) "
            "VALUES (%s, %s, %s)",
            (entity_id, str(vector), f"explicit enrolment: {args.sample.name}"),
        )
        db.audit(conn, "mcp", "voiceprint_enrolled",
                 {"entity_id": entity_id, "name": args.name})
        conn.commit()
    print(f"Voiceprint enrolled for {args.name} (entity {entity_id}). "
          "The next nightly cycles will identify this voice.")


if __name__ == "__main__":
    main()
