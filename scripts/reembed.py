#!/usr/bin/env python3
"""Re-indexes all memories with the configured embeddings backend.

Memories are recomputable projections (layer 0): changing the embeddings
model is not a migration, it is a recomputation. This tool:

1. aligns the dimension of `memories.embedding` with the configured backend
   (PENSINE_EMBEDDING_BACKEND / PENSINE_EMBEDDING_DIM);
2. recomputes the vector of every non-superseded memory;
3. logs the operation in the audit.

Usage: ./.venv/bin/python scripts/reembed.py [--dry-run]
(the project's .env is loaded by pensine.config — runnable as is)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import config, db, embeddings  # noqa: E402


def main() -> int:
    dry = "--dry-run" in sys.argv
    if not config.EMBEDDINGS_ENABLED:
        print("PENSINE_EMBEDDINGS=0 — nothing to do.")
        return 0

    probe = embeddings.embed("dimension probe", kind="document")
    if probe is None:
        print(f"ERROR: the backend '{config.EMBEDDING_BACKEND}' does not load "
              "(see the warning above) — no change made.")
        return 1
    dim = len(probe)
    if dim != config.EMBEDDING_DIM:
        print(f"WARNING: the model produces {dim}-d but PENSINE_EMBEDDING_DIM="
              f"{config.EMBEDDING_DIM} — following the model ({dim}).")

    with db.connection() as conn:
        # for the vector type, atttypmod IS the dimension (no 4-byte header
        # as with varchar)
        current = conn.execute(
            "SELECT atttypmod AS dim FROM pg_attribute "
            "WHERE attrelid = 'memories'::regclass AND attname = 'embedding'"
        ).fetchone()["dim"]
        rows = conn.execute(
            "SELECT id, content FROM memories WHERE superseded_by IS NULL ORDER BY id"
        ).fetchall()
        print(f"backend: {config.EMBEDDING_BACKEND} ({dim}-d) | column: "
              f"{current}-d | memories to recompute: {len(rows)}")
        if dry:
            print("(--dry-run: nothing written)")
            return 0

        if current != dim:
            # the type changes: the old vectors are meaningless, start afresh
            conn.execute("ALTER TABLE memories ALTER COLUMN embedding "
                         f"TYPE VECTOR({dim}) USING NULL")
            print(f"column resized: {current}-d → {dim}-d")

        done = 0
        for r in rows:
            vec = embeddings.embed(r["content"], kind="document")
            if vec is None:
                print(f"  memory {r['id']}: embedding unavailable — ABORTING "
                      "(the vectors already written remain consistent)")
                break
            conn.execute("UPDATE memories SET embedding = %s::vector WHERE id = %s",
                         (str(list(vec)), r["id"]))
            done += 1
        db.audit(conn, "consolidation", "reembed",
                 {"backend": config.EMBEDDING_BACKEND, "dim": dim,
                  "total": len(rows), "done": done})
        conn.commit()
        print(f"vectors recomputed: {done}/{len(rows)}")
        return 0 if done == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
