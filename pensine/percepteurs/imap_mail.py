"""Percepteur mails personnels — IMAP (phase 2, désactivé par défaut).

S'active uniquement si PENSINE_IMAP_HOST est configuré. Sous règle des tiers :
on capture l'enveloppe (qui, quoi, quand) et un extrait court ; la consolidation
synthétise, elle n'archive jamais les conversations des autres verbatim.
Sécurité (§5 couche 5) : ce percepteur LIT — le contenu externe non fiable
n'obtient jamais d'accès en écriture à la mémoire ; il ne produit que des
events candidats, filtrés par le gouverneur.
"""

import email
import email.header
import imaplib
from datetime import datetime, timedelta, timezone

from .. import config

SNIPPET_CHARS = 1500


def enabled() -> bool:
    return bool(config.IMAP_HOST and config.IMAP_USER and config.IMAP_PASSWORD)


def pull() -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%d-%b-%Y")
    events = []
    with imaplib.IMAP4_SSL(config.IMAP_HOST) as imap:
        imap.login(config.IMAP_USER, config.IMAP_PASSWORD)
        imap.select(config.IMAP_FOLDER, readonly=True)
        _, data = imap.search(None, f'(SINCE "{since}")')
        for num in data[0].split():
            _, msg_data = imap.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            when = email.utils.parsedate_to_datetime(msg["Date"]) if msg["Date"] else None
            events.append({
                "source": "mail",
                "kind": "message",
                "occurred_at": when or datetime.now(timezone.utc),
                "payload": {
                    "from": _decode(msg.get("From", "")),
                    "to": _decode(msg.get("To", "")),
                    "subject": _decode(msg.get("Subject", "")),
                    "snippet": _body_snippet(msg),
                },
            })
    return events


def _decode(value: str) -> str:
    parts = email.header.decode_header(value)
    return "".join(p.decode(enc or "utf-8", errors="replace") if isinstance(p, bytes)
                   else p for p, enc in parts)


def _body_snippet(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8",
                                      errors="replace")[:SNIPPET_CHARS]
        return ""
    payload = msg.get_payload(decode=True) or b""
    return payload.decode(msg.get_content_charset() or "utf-8",
                          errors="replace")[:SNIPPET_CHARS]
