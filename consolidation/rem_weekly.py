#!/usr/bin/env python3
"""Recombinaison hebdomadaire (dimanche 04:00) — le cycle REM.

Croise des souvenirs distants entre domaines, formule des hypothèses de
traits à valider, propose des amendements du persona — JAMAIS auto-ratifiés
(l'utilisateur est l'auteur final ; couche 3).
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pensine import config, db, llm  # noqa: E402
from pensine.governor import Governor  # noqa: E402

PROMPT = (Path(__file__).parent / "prompts" / "rem.md").read_text(encoding="utf-8")
PROPOSALS_DIR = Path(__file__).resolve().parent.parent / "persona" / "propositions"


def sample_memories(conn):
    """Échantillon inter-domaines : les plus importantes + un tirage ancien."""
    return conn.execute(
        """
        (SELECT id, type, content, valid_from FROM memories
         WHERE superseded_by IS NULL ORDER BY importance DESC LIMIT 40)
        UNION
        (SELECT id, type, content, valid_from FROM memories
         WHERE superseded_by IS NULL AND valid_from < now() - INTERVAL '90 days'
         ORDER BY md5(id::text) LIMIT 20)
        """
    ).fetchall()


def main() -> None:
    governor = Governor()
    with db.connection() as conn:
        rows = sample_memories(conn)
        if len(rows) < 5:
            db.audit(conn, "consolidation", "rem_noop", {"memories": len(rows)})
            conn.commit()
            print("Corpus trop jeune pour recombiner.")
            return
        corpus = json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str)

    prompt = (PROMPT
              .replace("{{OWNER}}", config.OWNER_NAME)
              .replace("{{CONSTITUTION}}", governor.constitution_text())
              .replace("{{MEMORIES}}", corpus))
    try:
        output = llm.complete(prompt)
    except llm.LLMUnavailable as exc:
        with db.connection() as conn:
            db.audit(conn, "consolidation", "rem_paused", {"reason": str(exc)})
            conn.commit()
        print(f"REM en pause ({exc}).")
        return

    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = PROPOSALS_DIR / f"{stamp}-rem.md"
    out.write_text(output, encoding="utf-8")

    with db.connection() as conn:
        db.audit(conn, "consolidation", "rem_weekly", {"proposal": str(out)})
        conn.commit()
    print(f"Propositions REM écrites : {out} (à ratifier manuellement).")


if __name__ == "__main__":
    main()
