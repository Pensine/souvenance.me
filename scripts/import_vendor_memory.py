#!/usr/bin/env python3
"""Import what an assistant remembers about you (memory and projects).

Usage:
  import_vendor_memory.py ~/exports/claude-2026-10/            # unzipped export
  import_vendor_memory.py claude-memory.md                      # copied-out memory
  import_vendor_memory.py ~/exports/claude-2026-10/ --dry-run   # preview, nothing written

Three ways to get Claude's memory, from the most complete to the simplest:
  1. Settings → Privacy → Export data: the archive contains the conversations,
     the projects and, since October 2026, a folder of memory documents.
     Unzip it and pass the folder.
  2. Settings → Memory: copy what is displayed into a text file.
  3. Ask Claude: "Write out verbatim everything you remember about me, one
     entry per line, with the date when you know it." Save the reply as .md —
     repeat until it says it is complete.

Each item becomes a second-hand event, filtered by your constitution and
deduplicated: safe to rerun. The export's conversations are handled
separately with scripts/import_history.py.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import db, vendor_memory  # noqa: E402
from pensine.governor import Governor  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", type=Path, help="unzipped export folder, or file")
    p.add_argument("--vendor", default="claude")
    p.add_argument("--dry-run", action="store_true", help="analyse without writing anything")
    p.add_argument("--exclude", action="append", default=[], metavar="MOTIF",
                   help="skip files whose path contains this pattern "
                        "(repeatable) — to set aside without touching the constitution")
    args = p.parse_args()
    if not args.path.exists():
        sys.exit(f"Not found: {args.path}")

    entries, projects, notes = vendor_memory.read_path(args.path)
    if args.exclude:
        def _out(f):
            return any(m.lower() in (f or "").lower() for m in args.exclude)
        held = sum(1 for e in entries if _out(e.get("file")))
        entries = [e for e in entries if not _out(e.get("file"))]
        projects = [p for p in projects if not _out(p.get("_file"))]
        notes.append(f"{held} items set aside by --exclude {args.exclude}")
    events = vendor_memory.to_events(entries, projects, args.vendor)
    words = sum(len(e["text"].split()) for e in entries)
    words_txt = f"{words:,}".replace(",", "\u202f")
    print(f"{len(entries)} memory items (~{words_txt} words), {len(projects)} projects.")
    for n in notes:
        print(f"  · {n}")
    by_file = Counter(e.get("file") for e in entries)
    for f, n in by_file.most_common(8):
        print(f"  · {f}: {n} items")

    if args.dry_run:
        for e in entries[:6]:
            print(f"  « {e['text'][:90]} »" + (f"  [{e['section']}]" if e.get("section") else ""))
        for pr in projects[:6]:
            print(f"  project: {pr.get('name')}")
        print("  … (--dry-run: nothing was written)")
        return

    governor = Governor()
    with db.connection() as conn:
        kept = governor.filter_events(conn, events)
        written = dup = 0
        for e in kept:
            if db.append_event(conn, source=e["source"], kind=e["kind"],
                               occurred_at=e["occurred_at"], payload=e["payload"]):
                written += 1
            else:
                dup += 1
        db.audit(conn, "mcp", "import_vendor_memory",
                 {"vendor": args.vendor, "written": written, "duplicates": dup,
                  "excluded": len(events) - len(kept)})
        conn.commit()
    print(f"{written} items imported ({dup} duplicates, "
          f"{len(events) - len(kept)} excluded by the constitution).")
    print("Before consolidation, measure the gap: scripts/vendor_mirror.py")


if __name__ == "__main__":
    main()
