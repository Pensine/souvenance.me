#!/usr/bin/env python3
"""Persona ratification — the act by which the user becomes the author.

Installs a proposal (reread and amended by hand) as the current persona:
copy to persona/persona.md, Git commit, pointer in the database
(persona_versions, ratified_by_user=true). This is the ONLY write path for the
persona."""

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
    p.add_argument("proposal", help="file name in persona/propositions/ "
                                    "(or path of an amended file)")
    args = p.parse_args()

    src = Path(args.proposal)
    if not src.exists():
        src = ROOT / "persona" / "propositions" / args.proposal
    if not src.exists():
        sys.exit(f"Not found: {args.proposal}")

    print(f"You are ratifying: {src}")
    print("This version becomes YOUR reference narrative identity.")
    if input("Have you reread and amended it yourself? [yes/N] ").strip().lower() not in ("yes", "oui"):
        sys.exit("Ratification cancelled — reread it first. You are the final author.")

    PERSONA.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(["git", "add", str(PERSONA)], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m",
                    f"Persona ratified ({src.name})"], cwd=ROOT, check=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()

    with db.connection() as conn:
        conn.execute(
            "INSERT INTO persona_versions (git_commit, ratified_by_user) "
            "VALUES (%s, true)", (commit,))
        db.audit(conn, "mcp", "persona_ratified", {"git_commit": commit})
        conn.commit()
    print(f"Ratified — commit {commit[:8]}. get_persona() now serves this version.")


if __name__ == "__main__":
    main()
