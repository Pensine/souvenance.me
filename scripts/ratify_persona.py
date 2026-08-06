#!/usr/bin/env python3
"""Ratification du persona — l'acte par lequel l'utilisateur devient l'auteur.

Installe une proposition (relue et amendée à la main) comme persona courant :
copie vers persona/persona.md, commit Git, pointeur en base (persona_versions,
ratified_by_user=true). C'est la SEULE voie d'écriture du persona."""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PERSONA = ROOT / "persona" / "persona.md"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("proposal", help="nom du fichier dans persona/propositions/ "
                                    "(ou chemin d'un fichier amendé)")
    args = p.parse_args()

    src = Path(args.proposal)
    if not src.exists():
        src = ROOT / "persona" / "propositions" / args.proposal
    if not src.exists():
        sys.exit(f"Introuvable : {args.proposal}")

    print(f"Vous ratifiez : {src}")
    print("Cette version devient VOTRE identité narrative de référence.")
    if input("Vous l'avez relue et amendée vous-même ? [oui/N] ").strip().lower() != "oui":
        sys.exit("Ratification annulée — relisez d'abord. Vous êtes l'auteur final.")

    PERSONA.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(["git", "add", str(PERSONA)], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m",
                    f"Persona ratifié ({src.name})"], cwd=ROOT, check=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()

    with db.connection() as conn:
        conn.execute(
            "INSERT INTO persona_versions (git_commit, ratified_by_user) "
            "VALUES (%s, true)", (commit,))
        db.audit(conn, "mcp", "persona_ratified", {"git_commit": commit})
        conn.commit()
    print(f"Ratifié — commit {commit[:8]}. get_persona() sert désormais cette version.")


if __name__ == "__main__":
    main()
