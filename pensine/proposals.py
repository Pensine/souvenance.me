"""Mémoire proposée : l'assistant repère, l'utilisateur tranche.

Le serveur ne voit pas la conversation. Il ne peut donc pas *vérifier* qu'un
consentement a été donné — aucune API ne le peut. Ce qu'il peut faire, et qui
est fait ici :

    séparer  une proposition n'est pas un événement. Elle vit dans sa propre
             table et n'entre dans le substrat append-only qu'après un second
             appel, distinct.

    dater    proposition et décision sont horodatées. Une confirmation trop
             rapide pour qu'une réponse humaine ait eu lieu est refusée — un
             modèle qui propose et confirme d'un seul souffle est arrêté.

    tracer   l'événement produit porte `origin='proposed'`. La question « qu'a
             retenu le système de lui-même ? » reste une requête SQL, pour
             toujours.

Le reste — annoncer avant de proposer, ne jamais confirmer sans un oui — tient
à la discipline du modèle. On ne peut pas l'imposer depuis le serveur ; on peut
le rendre visible, et c'est ce que fait `review`.
"""

from datetime import datetime, timezone

from . import db

# Délai minimal entre proposer et confirmer. Ce n'est pas une sécurité — un
# modèle déterminé le contourne en attendant. C'est un garde-fou contre le zèle :
# personne ne lit une proposition et ne répond en deux secondes, donc une
# confirmation aussi rapide n'a pas pu être consentie.
MIN_SECONDS_BEFORE_CONFIRM = 4

KINDS = {"fact", "inference"}


class NotConsented(Exception):
    """Confirmation refusée : rien ne prouve qu'on a laissé le temps de répondre."""


def propose(conn, content: str, kind: str, rationale: str = "") -> dict:
    """Enregistre ce que l'assistant a compris. N'écrit AUCUN événement."""
    if kind not in KINDS:
        kind = "inference"   # dans le doute, la catégorie la plus prudente
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
    """L'utilisateur a dit oui : la proposition devient un événement.

    Lève NotConsented si la proposition vient d'être créée — le temps qu'il
    faut pour lire et répondre ne s'est pas écoulé.
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
        raise KeyError(f"proposition {proposal_id} introuvable")
    if row["status"] != "pending":
        return {"already": row["status"]}
    if row["age_s"] < MIN_SECONDS_BEFORE_CONFIRM:
        db.audit(conn, "mcp", "memory_confirm_too_fast",
                 {"proposal_id": proposal_id, "age_s": float(row["age_s"])})
        raise NotConsented(
            "Proposition confirmée trop vite pour qu'une réponse ait pu être "
            "donnée. Présente-la à la personne, attends sa réponse, puis "
            "confirme."
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
    """Refus. Conservé : ce qu'on ne veut pas voir mémorisé en dit long."""
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
    """Ce qui attend une décision."""
    return conn.execute(
        "SELECT id, content, kind, rationale, proposed_at FROM memory_proposals "
        "WHERE status='pending' ORDER BY proposed_at LIMIT %s",
        (limit,),
    ).fetchall()


def review(conn, days: int = 30) -> dict:
    """Ce que le système a retenu de lui-même, et ce qu'on lui a refusé.

    C'est la question que Dash et al. ont dû poser de l'extérieur, sur des
    inconnus, faute de pouvoir l'adresser au système lui-même. Ici, elle est
    une requête.
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
