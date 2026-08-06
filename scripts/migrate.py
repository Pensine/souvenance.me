#!/usr/bin/env python3
"""Applique les migrations db/migrations/*.sql dans l'ordre, une seule fois
chacune (suivi dans schema_migrations). Idempotent : relançable sans risque."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import db  # noqa: E402

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"


def main() -> None:
    with db.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        applied = {r["filename"] for r in
                   conn.execute("SELECT filename FROM schema_migrations").fetchall()}
        conn.commit()

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            print(f"→ {path.name}")
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)",
                         (path.name,))
            conn.commit()
    print("Migrations à jour.")


if __name__ == "__main__":
    main()
