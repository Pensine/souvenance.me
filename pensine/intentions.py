"""What is coming: the next steps, from their birth to their outcome.

A step is born from a deposit ("next step: call Charles"), spotted by nightly
consolidation. It attaches to a due date if one is stated, otherwise to a
subject. It closes when a later deposit says it was done — or abandoned, and
why.

Statuses, computed at read time (nothing is stored that could go stale):
  ouverte      in progress
  en_suspens   open, but no news since STALE_DAYS
  fait         closed, accomplished
  abandonne    closed, abandoned

Silence rule: nothing here nudges anyone. A step comes back up in
conversation when its subject is discussed, or when the timeline is opened.
Time capsules share the table but stay sealed: no function in this module
reads them.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone

STALE_DAYS = 60
OUTCOMES = {"fait", "abandonne"}


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", t).strip()


def terms(text: str) -> list[str]:
    """Content words of a subject (4 letters or more, accent-free)."""
    return [w for w in _norm(text).split() if len(w) >= 4]


def matches(row, subject_terms: list[str]) -> bool:
    hay = _norm(f"{row.get('content', '')} {row.get('trigger_value', '')}")
    return any(t in hay for t in subject_terms)


def status(row, now: datetime | None = None) -> str:
    if row.get("outcome") in OUTCOMES:
        return row["outcome"]
    now = now or datetime.now(timezone.utc)
    last = row.get("last_mentioned_at") or row.get("created_at")
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if now - last > timedelta(days=STALE_DAYS):
            return "en_suspens"
    return "ouverte"


def due_date(row) -> date | None:
    """Due date of a dated step, otherwise None."""
    if row.get("trigger_kind") != "date":
        return None
    try:
        return date.fromisoformat(str(row["trigger_value"])[:10])
    except ValueError:
        return None


_COLS = """id, content, trigger_kind, trigger_value, created_at, last_mentioned_at,
           resolved_at, outcome, outcome_note, source_event_ids"""


def open_steps(conn, limit: int = 40) -> list:
    return conn.execute(
        f"""SELECT {_COLS} FROM intentions
            WHERE kind = 'etape' AND resolved_at IS NULL
            ORDER BY COALESCE(last_mentioned_at, created_at) DESC LIMIT %s""",
        (limit,),
    ).fetchall()


def steps_for(conn, subject: str, closed_within_days: int = 365) -> list:
    """Steps for a subject: open ones, and ones closed less than a year ago."""
    t = terms(subject)
    if not t:
        return []
    rows = conn.execute(
        f"""SELECT {_COLS} FROM intentions
            WHERE kind = 'etape'
              AND (resolved_at IS NULL OR resolved_at > now() - make_interval(days => %s))
            ORDER BY created_at""",
        (closed_within_days,),
    ).fetchall()
    return [r for r in rows if matches(r, t)]


def add_step(conn, content: str, subject: str = "", due: str | None = None,
             source_event_ids: list[int] | None = None,
             mentioned_at: datetime | None = None) -> int | None:
    """Create a step, unless an open step already says the same thing — in
    that case it is merely marked as mentioned again."""
    content = (content or "").strip()
    if not content:
        return None
    key = _norm(content)
    for r in open_steps(conn, limit=200):
        other = _norm(r["content"])
        if key == other or (len(key) > 12 and (key in other or other in key)):
            touch(conn, [r["id"]], mentioned_at)
            return None
    due_ok = None
    if due:
        try:
            due_ok = date.fromisoformat(str(due)[:10]).isoformat()
        except ValueError:
            due_ok = None
    when = mentioned_at or datetime.now(timezone.utc)
    row = conn.execute(
        """INSERT INTO intentions (content, trigger_kind, trigger_value, kind,
                                   source_event_ids, last_mentioned_at, created_at)
           VALUES (%s, %s, %s, 'etape', %s, %s, %s) RETURNING id""",
        (content, "date" if due_ok else "topic", due_ok or (subject or "").strip(),
         source_event_ids or [], when, when),
    ).fetchone()
    return row["id"]


def touch(conn, ids: list[int], when: datetime | None = None) -> None:
    """A step mentioned again leaves 'en_suspens'."""
    if ids:
        conn.execute(
            """UPDATE intentions SET last_mentioned_at = GREATEST(
                   COALESCE(last_mentioned_at, created_at), %s)
               WHERE id = ANY(%s) AND kind = 'etape'""",
            (when or datetime.now(timezone.utc), ids),
        )


def close(conn, intention_id: int, outcome: str, note: str = "",
          when: datetime | None = None) -> bool:
    """Close a step: done or abandoned. Never a capsule."""
    if outcome not in OUTCOMES:
        return False
    row = conn.execute(
        """UPDATE intentions SET resolved_at = %s, outcome = %s, outcome_note = %s
           WHERE id = %s AND kind = 'etape' AND resolved_at IS NULL RETURNING id""",
        (when or datetime.now(timezone.utc), outcome, (note or "").strip() or None,
         intention_id),
    ).fetchone()
    return row is not None
