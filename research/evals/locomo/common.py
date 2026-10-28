"""Foundation of the LoCoMo harness: isolated environment, dataset, frozen clock.

Safety: the scripts set PENSINE_DATABASE_URL themselves, to the throwaway
database (port 5442) — never read from a .env. It is structurally
impossible to touch a production Pensine by accident.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
DATA = HERE / "data" / "locomo10.json"
RESULTS = HERE / "results"

DB_PORT = int(os.environ.get("LOCOMO_DB_PORT", "5442"))


def db_url(conv: int, dbname: str | None = None) -> str:
    return (f"postgresql://locomo:locomo@127.0.0.1:{DB_PORT}/"
            f"{dbname or f'locomo_c{conv}'}")


def use_conv(conv: int) -> None:
    """Point pensine at the database of conversation <conv>.

    Call it before the first import of pensine (config reads the environment
    at import time); it also handles the case where pensine.config is already
    loaded, since db.connection() re-reads config.DATABASE_URL on every call.
    """
    url = db_url(conv)
    os.environ["PENSINE_DATABASE_URL"] = url
    os.environ["PENSINE_CONSTITUTION"] = str(HERE / "constitution-eval.yaml")
    os.environ.setdefault("PENSINE_OWNER_NAME", "Eval")
    if "pensine.config" in sys.modules:
        sys.modules["pensine.config"].DATABASE_URL = url
    for p in (str(REPO), str(REPO / "consolidation")):
        if p not in sys.path:
            sys.path.insert(0, p)  # consolidation/: import media_pipeline (nightly.py)


def ensure_db(conv: int) -> None:
    """Create locomo_c<conv> if missing, apply schema + migrations (idempotent)."""
    import psycopg

    name = f"locomo_c{conv}"
    with psycopg.connect(db_url(conv, "locomo"), autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname = %s",
                         (name,)).fetchone():
            c.execute(f'CREATE DATABASE "{name}"')
    with psycopg.connect(db_url(conv)) as c:
        if not c.execute("SELECT 1 FROM information_schema.tables"
                         " WHERE table_name = 'events'").fetchone():
            c.execute((REPO / "db" / "schema.sql").read_text(encoding="utf-8"))
        c.commit()
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "migrate.py")],
        env={**os.environ, "PENSINE_DATABASE_URL": db_url(conv)},
        check=True, stdout=subprocess.DEVNULL,
    )


def freeze_time(at: datetime) -> None:
    """Freeze datetime.now() in nightly and pensine.temporal.

    The corpus is dated 2023: without this, {{TODAY}} would be today's real
    date, the valid_from fallback would date memories to today, and
    recall's time frame would say "3 years ago" about facts the
    conversation is living in the present.
    """
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: N805
            return at.astimezone(tz) if tz else at.replace(tzinfo=None)

    import nightly
    from pensine import temporal
    nightly.datetime = Frozen
    temporal.datetime = Frozen


def check_backend() -> None:
    """Fail right away rather than after a 30-minute timeout.

    The trap we hit: on macOS, the Claude desktop app installs a
    `claude` binary that takes precedence in the PATH and opens a window
    instead of answering. Consolidation waited for the full timeout.
    """
    import shutil

    from pensine import config

    if config.LLM_BACKEND != "claude-cli":
        return
    path = shutil.which(config.CLAUDE_BIN)
    if not path:
        sys.exit(f"CLI not found ({config.CLAUDE_BIN}) — set PENSINE_CLAUDE_BIN, "
                 "or PENSINE_LLM_BACKEND=api|ollama")
    if "/Claude.app/" in path:
        sys.exit(
            f"\"{config.CLAUDE_BIN}\" points to the desktop app "
            f"({path}): it opens a window, it does not answer.\n"
            "Use the CLI, for example:\n"
            "  PENSINE_CLAUDE_BIN=~/.local/bin/claude ...")


def load_dataset() -> list[dict]:
    if not DATA.exists():
        sys.exit("dataset missing — run ./download.sh first")
    return json.loads(DATA.read_text(encoding="utf-8"))


def parse_session_dt(s: str) -> datetime:
    """"1:56 pm on 8 May, 2023" → UTC datetime (the benchmark has no time zone)."""
    return datetime.strptime(s.strip(), "%I:%M %p on %d %B, %Y").replace(
        tzinfo=timezone.utc)


def sessions(sample: dict) -> list[tuple[int, datetime, list[dict]]]:
    """A conversation's sessions, in chronological order."""
    conv = sample["conversation"]
    out = []
    for key, turns in conv.items():
        m = re.fullmatch(r"session_(\d+)", key)
        if m and isinstance(turns, list):
            n = int(m.group(1))
            out.append((n, parse_session_dt(conv[f"session_{n}_date_time"]), turns))
    return sorted(out, key=lambda x: x[1])


def session_transcript(turns: list[dict]) -> str:
    """One turn per line; the 1,226 turns with an image keep their caption."""
    lines = []
    for t in turns:
        line = f"{t['speaker']}: {t.get('text', '')}"
        if t.get("blip_caption"):
            line += f" [shares a photo: {t['blip_caption']}]"
        lines.append(line)
    return "\n".join(lines)


def speakers(sample: dict) -> tuple[str, str]:
    return sample["conversation"]["speaker_a"], sample["conversation"]["speaker_b"]
