#!/usr/bin/env python3
"""Take your context back: imports a ChatGPT or Claude export.

Usage:
  import_history.py ~/exports/chatgpt/conversations.json
  import_history.py ~/exports/claude/conversations.json --dry-run

Each conversation becomes an event (layer 0). The governor filters
(exclusion perimeter), the hash deduplicates: safe to rerun.
Nightly consolidation does the rest — at the next wake-up, the memory
knows years of you."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import db, importers  # noqa: E402
from pensine.governor import Governor  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("export", type=Path, help="conversations.json from the official export")
    p.add_argument("--dry-run", action="store_true",
                   help="analyse without writing anything")
    args = p.parse_args()

    if not args.export.exists():
        sys.exit(f"Not found: {args.export}")

    fmt, events = importers.parse_file(args.export)
    print(f"{fmt} export: {len(events)} conversations, "
          f"{sum(e['payload']['message_count'] for e in events)} messages.")
    if args.dry_run:
        for e in events[:5]:
            print(f"  · {e['occurred_at']:%Y-%m-%d}  {e['payload']['title'][:60]}")
        print("  … (--dry-run: nothing was written)")
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
    print(f"{written} conversations imported "
          f"({skipped} duplicates ignored, {len(events) - len(kept)} excluded "
          "by the constitution).")
    print("Nightly consolidation will replay them — or run "
          "consolidation/nightly.py now.")


if __name__ == "__main__":
    main()
