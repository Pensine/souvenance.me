#!/usr/bin/env python3
"""Weekly recombination (Sunday 04:00) — the REM cycle.

Cross-links distant memories across domains, formulates trait hypotheses to
validate, proposes persona amendments — NEVER auto-ratified (the user is the
final author; layer 3).
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
    """Cross-domain sample: the most important + an old random draw."""
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
            print("Corpus too young to recombine.")
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
        print(f"REM paused ({exc}).")
        return

    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = PROPOSALS_DIR / f"{stamp}-rem.md"
    out.write_text(output, encoding="utf-8")

    with db.connection() as conn:
        db.audit(conn, "consolidation", "rem_weekly", {"proposal": str(out)})
        conn.commit()
    print(f"REM proposals written: {out} (to be ratified manually).")


if __name__ == "__main__":
    main()
