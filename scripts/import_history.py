#!/usr/bin/env python3
"""Reprendre son contexte : importe un export ChatGPT ou Claude.

Usage :
  import_history.py ~/exports/chatgpt/conversations.json
  import_history.py ~/exports/claude/conversations.json --dry-run

Chaque conversation devient un event (couche 0). Le gouverneur filtre
(périmètre d'exclusion), le hash déduplique : relançable sans risque.
La consolidation nocturne fera le reste — au prochain réveil, la mémoire
connaît des années de vous."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import db, importers  # noqa: E402
from pensine.governor import Governor  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("export", type=Path, help="conversations.json de l'export officiel")
    p.add_argument("--dry-run", action="store_true",
                   help="analyse sans rien écrire")
    args = p.parse_args()

    if not args.export.exists():
        sys.exit(f"Introuvable : {args.export}")

    fmt, events = importers.parse_file(args.export)
    print(f"Export {fmt} : {len(events)} conversations, "
          f"{sum(e['payload']['message_count'] for e in events)} messages.")
    if args.dry_run:
        for e in events[:5]:
            print(f"  · {e['occurred_at']:%Y-%m-%d}  {e['payload']['title'][:60]}")
        print("  … (--dry-run : rien n'a été écrit)")
        return

    governor = Governor()
    with db.connection() as conn:
        kept = governor.filter_events(conn, events)
        written = skipped = 0
        for e in kept:
            if db.append_event(conn, source=e["source"], kind=e["kind"],
                               occurred_at=e["occurred_at"], payload=e["payload"]):
                written += 1
            else:
                skipped += 1
        db.audit(conn, "mcp", "import_history",
                 {"format": fmt, "written": written, "duplicates": skipped,
                  "excluded": len(events) - len(kept)})
        conn.commit()
    print(f"{written} conversations importées "
          f"({skipped} doublons ignorés, {len(events) - len(kept)} exclues "
          "par la constitution).")
    print("La consolidation nocturne les rejouera — ou lancez "
          "consolidation/nightly.py maintenant.")


if __name__ == "__main__":
    main()
