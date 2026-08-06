#!/usr/bin/env python3
"""Ré-indexe toutes les mémoires avec le backend d'embeddings configuré.

Les mémoires sont des projections recalculables (couche 0) : changer de
modèle d'embeddings n'est pas une migration, c'est un recalcul. Cet outil :

1. aligne la dimension de `memories.embedding` sur le backend configuré
   (PENSINE_EMBEDDING_BACKEND / PENSINE_EMBEDDING_DIM) ;
2. recalcule le vecteur de chaque mémoire non remplacée ;
3. journalise l'opération dans l'audit.

Usage : ./.venv/bin/python scripts/reembed.py [--dry-run]
(le .env du projet est chargé par pensine.config — lançable tel quel)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import config, db, embeddings  # noqa: E402


def main() -> int:
    dry = "--dry-run" in sys.argv
    if not config.EMBEDDINGS_ENABLED:
        print("PENSINE_EMBEDDINGS=0 — rien à faire.")
        return 0

    probe = embeddings.embed("sonde de dimension", kind="document")
    if probe is None:
        print(f"ERREUR : le backend '{config.EMBEDDING_BACKEND}' ne charge pas "
              "(voir le warning ci-dessus) — aucune modification.")
        return 1
    dim = len(probe)
    if dim != config.EMBEDDING_DIM:
        print(f"ATTENTION : le modèle produit {dim}-d mais PENSINE_EMBEDDING_DIM="
              f"{config.EMBEDDING_DIM} — on suit le modèle ({dim}).")

    with db.connection() as conn:
        # pour le type vector, atttypmod EST la dimension (pas d'en-tête de 4
        # octets comme varchar)
        current = conn.execute(
            "SELECT atttypmod AS dim FROM pg_attribute "
            "WHERE attrelid = 'memories'::regclass AND attname = 'embedding'"
        ).fetchone()["dim"]
        rows = conn.execute(
            "SELECT id, content FROM memories WHERE superseded_by IS NULL ORDER BY id"
        ).fetchall()
        print(f"backend : {config.EMBEDDING_BACKEND} ({dim}-d) | colonne : "
              f"{current}-d | mémoires à recalculer : {len(rows)}")
        if dry:
            print("(--dry-run : aucune écriture)")
            return 0

        if current != dim:
            # le type change : les anciens vecteurs n'ont plus de sens, on repart
            conn.execute("ALTER TABLE memories ALTER COLUMN embedding "
                         f"TYPE VECTOR({dim}) USING NULL")
            print(f"colonne redimensionnée : {current}-d → {dim}-d")

        done = 0
        for r in rows:
            vec = embeddings.embed(r["content"], kind="document")
            if vec is None:
                print(f"  mémoire {r['id']} : embedding indisponible — ABANDON "
                      "(les vecteurs déjà écrits restent cohérents)")
                break
            conn.execute("UPDATE memories SET embedding = %s::vector WHERE id = %s",
                         (str(list(vec)), r["id"]))
            done += 1
        db.audit(conn, "consolidation", "reembed",
                 {"backend": config.EMBEDDING_BACKEND, "dim": dim,
                  "total": len(rows), "done": done})
        conn.commit()
        print(f"vecteurs recalculés : {done}/{len(rows)}")
        return 0 if done == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
