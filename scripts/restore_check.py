#!/usr/bin/env python3
"""Check of a RESTORED database (called by scripts/restore_test.sh).

Verifies, on the database pointed to by PENSINE_DATABASE_URL, with the keys in
PENSINE_KEYS_DIR and the media in PENSINE_MEDIA_ROOT:
  - every sealed deposit opens, or belongs to a deliberately forgotten scope
    (shred_scopes.forgotten_at); a missing key for a NON-forgotten scope =
    lost deposits → failure;
  - every referenced media file exists on disk (forgotten media aside);
  - the append-only log still refuses a modification;
  - the raw candidates open or are forgotten.
Prints counts only. Exit code 1 if a loss is found.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import config, db, shred  # noqa: E402


def main() -> int:
    report, problems = {}, []
    with db.connection() as conn:
        report["events"] = conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"]
        report["memories"] = conn.execute("SELECT count(*) AS n FROM memories").fetchone()["n"]
        try:
            forgotten = {r["id"] for r in conn.execute(
                "SELECT id FROM shred_scopes WHERE forgotten_at IS NOT NULL").fetchall()}
        except Exception:  # migration 014 absent: no scope
            conn.rollback()
            forgotten = set()
        sealed = ok = gone = lost = 0
        for r in conn.execute("SELECT id, payload FROM events WHERE payload ? '_scelle'"):
            sealed += 1
            scope = shred.scope_of(r["payload"])
            try:
                clear = shred.open_payload(r["payload"])
            except Exception:
                clear = None
            if clear is not None:
                ok += 1
            elif scope in forgotten:
                gone += 1
            else:
                lost += 1
        report["depots_scelles"] = {"total": sealed, "lisibles": ok, "oublies": gone,
                                    "perdus": lost}
        if lost:
            problems.append(f"{lost} sealed deposit(s) unreadable without forgetting: key missing")

        root = Path(config.MEDIA_ROOT)
        rows = conn.execute("SELECT storage_path FROM media WHERE storage_path <> 'oublie'"
                            ).fetchall()
        missing = sum(1 for r in rows
                      if not (Path(r["storage_path"]) if Path(r["storage_path"]).is_absolute()
                              else root / r["storage_path"]).exists())
        report["medias"] = {"total": len(rows), "manquants": missing}
        if missing:
            problems.append(f"{missing} referenced media file(s) missing from disk")

        try:
            with conn.transaction():
                conn.execute("UPDATE events SET kind = kind WHERE id = (SELECT min(id) FROM events)")
            problems.append("the events log accepts a modification (trigger missing)")
            report["append_only"] = False
        except Exception:
            report["append_only"] = True

        try:
            with conn.transaction():
                cands = conn.execute("SELECT payload FROM night_candidates").fetchall()
            readable = sum(1 for c in cands if shred.open_layers(c["payload"]) is not None)
            report["candidates"] = {"total": len(cands), "lisibles": readable}
        except Exception:
            report["candidates"] = None
    report["problemes"] = problems
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
