#!/usr/bin/env python3
"""Enrôlement d'une empreinte vocale — acte EXPLICITE (§8), jamais implicite.

Usage : enroll_speaker.py --name "Prénom" --kind person échantillon.wav
L'échantillon : 30-60 s de voix seule, propre. Le fichier n'est PAS conservé
(seule l'empreinte 192-d l'est) — sauf s'il passe aussi par la Pensine."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import db  # noqa: E402
from pensine.graph import upsert_entity  # noqa: E402
from pensine.speakers import compute_voiceprint  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("sample", type=Path, help="échantillon audio (wav/mp3/opus)")
    p.add_argument("--name", required=True, help="nom de la personne")
    p.add_argument("--kind", default="person")
    args = p.parse_args()

    if not args.sample.exists():
        sys.exit(f"Introuvable : {args.sample}")
    print(f"Calcul de l'empreinte de {args.name}…")
    vector = compute_voiceprint(args.sample)

    with db.connection() as conn:
        entity_id = upsert_entity(conn, args.name, args.kind)
        conn.execute(
            "INSERT INTO voiceprints (entity_id, embedding, sample_note) "
            "VALUES (%s, %s, %s)",
            (entity_id, str(vector), f"enrôlement explicite : {args.sample.name}"),
        )
        db.audit(conn, "mcp", "voiceprint_enrolled",
                 {"entity_id": entity_id, "name": args.name})
        conn.commit()
    print(f"Empreinte enrôlée pour {args.name} (entity {entity_id}). "
          "Les prochains cycles nocturnes identifieront cette voix.")


if __name__ == "__main__":
    main()
