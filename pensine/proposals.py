"""Proposed memory: the assistant spots, the user decides.

The server does not see the conversation. It therefore cannot *verify* that
consent was given — no API can. What it can do, and what is done here:

    separate  a proposal is not an event. It lives in its own table and only
              enters the append-only substrate after a second, distinct call.

    timestamp proposal and decision are timestamped. A confirmation too fast
              for a human answer to have occurred is refused — a model that
              proposes and confirms in one breath is stopped.

    trace     the resulting event carries `origin='proposed'`. The question
              "what did the system retain on its own?" remains a SQL query,
              forever.

The rest — announcing before proposing, never confirming without a yes —
depends on the model's discipline. It cannot be enforced from the server; it
can be made visible, and that is what `review` does.
"""

from datetime import datetime, timezone

from . import db

# Minimum delay between proposing and confirming. This is not a security
# measure — a determined model gets around it by waiting. It is a guardrail
# against zeal: nobody reads a proposal and answers within two seconds, so a
# confirmation that fast cannot have been consented to.
MIN_SECONDS_BEFORE_CONFIRM = 4

KINDS = {"fact", "inference"}


class NotConsented(Exception):
    """Confirmation refused: nothing proves that time was left to answer."""


def propose(conn, content: str, kind: str, rationale: str = "") -> dict:
    """Record what the assistant understood. Writes NO event."""
    if kind not in KINDS:
        kind = "inference"   # when in doubt, the most cautious category
    row = conn.execute(
        """
        INSERT INTO memory_proposals (content, kind, rationale)
        VALUES (%s, %s, %s)
        RETURNING id, proposed_at
        """,
        (content.strip(), kind, rationale.strip() or None),
    ).fetchone()
    db.audit(conn, "mcp", "memory_proposed",
             {"proposal_id": row["id"], "kind": kind})
    return {"id": row["id"], "proposed_at": row["proposed_at"]}


def confirm(conn, proposal_id: int) -> dict:
    """The user said yes: the proposal becomes an event.

    Raises NotConsented if the proposal has just been created — the time it
    takes to read and answer has not elapsed.
    """
    row = conn.execute(
        """
        SELECT id, content, kind, rationale, status,
               EXTRACT(EPOCH FROM (now() - proposed_at)) AS age_s
        FROM memory_proposals WHERE id = %s
        """,
        (proposal_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"proposal {proposal_id} not found")
    if row["status"] != "pending":
        return {"already": row["status"]}
    if row["age_s"] < MIN_SECONDS_BEFORE_CONFIRM:
        db.audit(conn, "mcp", "memory_confirm_too_fast",
                 {"proposal_id": proposal_id, "age_s": float(row["age_s"])})
        raise NotConsented(
            "Proposal confirmed too fast for an answer to have been given. "
            "Present it to the person, wait for their answer, then confirm."
        )

    event_id = db.append_event(
        conn,
        source="conversation",
        kind="proposed_memory",
        occurred_at=datetime.now(timezone.utc),
        payload={"note": row["content"], "kind": row["kind"],
                 "rationale": row["rationale"], "proposal_id": row["id"]},
        origin="proposed",
    )
    conn.execute(
        "UPDATE memory_proposals SET status='confirmed', decided_at=now(), "
        "event_id=%s WHERE id=%s",
        (event_id, proposal_id),
    )
    db.audit(conn, "mcp", "memory_confirmed",
             {"proposal_id": proposal_id, "event_id": event_id})
    return {"event_id": event_id}


def decline(conn, proposal_id: int, reason: str = "") -> dict:
    """Refusal. Kept: what one does not want remembered says a lot."""
    updated = conn.execute(
        "UPDATE memory_proposals SET status='declined', decided_at=now(), "
        "decline_reason=%s WHERE id=%s AND status='pending' RETURNING id",
        (reason.strip() or None, proposal_id),
    ).fetchone()
    if updated is None:
        return {"already": "decided"}
    db.audit(conn, "mcp", "memory_declined", {"proposal_id": proposal_id})
    return {"declined": proposal_id}


def pending(conn, limit: int = 20):
    """What is awaiting a decision."""
    return conn.execute(
        "SELECT id, content, kind, rationale, proposed_at FROM memory_proposals "
        "WHERE status='pending' ORDER BY proposed_at LIMIT %s",
        (limit,),
    ).fetchall()


def review(conn, days: int = 30) -> dict:
    """What the system retained on its own, and what it was refused.

    This is the question Dash et al. had to ask from the outside, about
    strangers, for lack of being able to put it to the system itself. Here, it
    is a query.
    """
    counts = conn.execute(
        f"""
        SELECT status, kind, count(*) AS n
        FROM memory_proposals
        WHERE proposed_at > now() - INTERVAL '{int(days)} days'
        GROUP BY status, kind
        """
    ).fetchall()
    origins = conn.execute(
        f"""
        SELECT origin, count(*) AS n FROM events
        WHERE ingested_at > now() - INTERVAL '{int(days)} days'
        GROUP BY origin
        """
    ).fetchall()
    total = sum(o["n"] for o in origins) or 1
    proposed = sum(o["n"] for o in origins if o["origin"] == "proposed")
    return {
        "fenetre_jours": days,
        "propositions": [dict(c) for c in counts],
        "events_par_origine": {o["origin"]: o["n"] for o in origins},
        "part_proposee": round(proposed / total, 3),
    }
