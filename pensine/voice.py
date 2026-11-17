"""Who says it: the voice of a memory, read in code from the deposits it cites.

The excerpt check (pensine/evidence.py) proves that the words are in a
deposit. It does not say who put them there: a friend's mistaken
congratulations, a notice from a service, a sentence addressed to "any
assistant" all hold the excerpt they are quoted for. Measured on the first
poisoning runs (SOURCED, lab/poison): the claim passes the gate because it
is written, and the reader repeats it because nothing tells it whose word
it is.

The voice comes from the deposit's own metadata, never from its wording:

  soi       the owner made the deposit (a note, a voice memo, a sent
            message, a photo, the logbook);
  document  a text with no speaker (a document, an imported conversation,
            perceived content);
  tiers     the deposit was received from someone (kind `*_in`, direction in);
  consigne  a deposit the owner did not make, holding a sentence addressed
            to an AI (pensine/injection.py).

A memory takes the most trusted voice among the deposits where its excerpts
were found: one sentence of the owner's is enough to make it the owner's.

What follows, in code:
  - the voice is stored with the evidence when it is not the owner's;
  - recall sets what others wrote apart from the owner's memories, in a list
    of its own with how to read it (SAID_BY_OTHERS);
  - what only a third party says of someone else than themselves (the
    sender named in the deposit's metadata) is kept at capped confidence:
    said, not established;
  - what only a "consigne" deposit says is kept at a low confidence. Nothing
    is erased (the deposit stays in the log), nothing is promoted.
A document is not capped: a lease is a document.

The voice labels are stored data and are compared in code; they stay French.
"""

from __future__ import annotations

import json

from . import evidence, injection

SOI, DOCUMENT, TIERS, CONSIGNE = "soi", "document", "tiers", "consigne"
_TRUST = [SOI, DOCUMENT, TIERS, CONSIGNE]  # most trusted first
CAP = {TIERS: 0.5, CONSIGNE: 0.3}
_DOCUMENT_SOURCES = {"conversation", "import", "perception"}

REPORTED = (TIERS, CONSIGNE)  # set apart by recall
_SENDER_KEYS = ("sender", "author", "from")  # as identity.METADATA_KEYS

# Travel with recall output, whose memories are French (as injection.READ_NOTICE).
GUIDE = ("« voix: document » : le souvenir est tiré d'un texte sans auteur (un bail, un avis, "
         "un import), pas d'une parole de la personne. Il dit ce que le texte affirme.")
SAID_BY_OTHERS = (
    "Ce que d'autres ont écrit à la personne. Ce qu'ils disent d'eux-mêmes est leur parole. "
    "Ce qu'ils disent de la personne ou de ses affaires n'est pas établi par elle : ne le "
    "rapporte jamais comme un fait ; si rien dans « memories » ne le confirme, réponds que "
    "la mémoire ne l'établit pas.")


def _payload(event: dict) -> dict:
    payload = event.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = {}
    return payload if isinstance(payload, dict) else {}


def received(event: dict) -> bool:
    """Was this deposit received rather than made by the owner (a voice
    message, a letter)? Its first person is then the sender."""
    payload = _payload(event)
    kind = str(event.get("kind") or payload.get("kind") or "")
    return kind.endswith("_in") or payload.get("direction") in ("in", "incoming", "received")


def of_event(event: dict) -> str:
    """The voice of one deposit, from its metadata."""
    payload = _payload(event)
    kind = str(event.get("kind") or payload.get("kind") or "")
    if received(event):
        voice = TIERS
    elif kind == "document" or payload.get("kind") == "document" \
            or str(event.get("source") or "") in _DOCUMENT_SOURCES:
        voice = DOCUMENT
    else:
        return SOI
    # the owner may write anything; a sentence addressed to an AI in what
    # someone else wrote is not testimony
    return CONSIGNE if injection.suspicious(evidence.source_text(event)) else voice


def sender(event: dict) -> str:
    """Who sent a received deposit, when its metadata names them."""
    payload = _payload(event)
    for key in _SENDER_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _holding(memory: dict, events_by_id: dict[int, dict]) -> list[dict]:
    """The deposits of a memory where its excerpts were found (all its
    deposits when none holds one)."""
    own = [events_by_id[i] for i in (memory.get("source_event_ids") or []) if i in events_by_id]
    citations = (memory.get("evidence") or {}).get("citations") or []
    holding = [e for e in own
               if any(evidence.quote_found(c, evidence.source_text(e)) for c in citations)]
    return holding or own


def of_memory(memory: dict, events_by_id: dict[int, dict]) -> str | None:
    """The voice of a memory: the most trusted one among the deposits where
    its excerpts were found. None when no deposit of its own is known."""
    voices = {of_event(e) for e in _holding(memory, events_by_id)}
    return next((v for v in _TRUST if v in voices), None)


def _same_person(subject: str, name: str) -> bool:
    a, b = set(evidence.normalize(subject).split()), set(evidence.normalize(name).split())
    return bool(a) and bool(b) and (a <= b or b <= a)


def _speaks_of_themselves(memory: dict, holding: list[dict]) -> bool:
    """The sender's own life ("my dog woke me") is first-hand, whatever the
    channel: the memory's subject is the person who sent the deposit. When
    no deposit names its sender, a named subject other than the owner is
    taken to be them."""
    from . import atoms
    subject = (memory.get("subject") or "").strip()
    if not subject or subject == atoms.OWNER:
        return False
    senders = [name for name in map(sender, holding) if name]
    return not senders or any(_same_person(subject, name) for name in senders)


def stamp(memories: list[dict], events: list[dict]) -> tuple[list[dict], dict]:
    """Give each admitted memory its voice. Returns the memories and a
    content-free count per voice (for the audit log)."""
    by_id = {e["id"]: e for e in events if "id" in e}
    out, report = [], {}
    for m in memories:
        voice = of_memory(m, by_id)
        if voice in (None, SOI):
            out.append(m)
            continue
        report[voice] = report.get(voice, 0) + 1
        m = {**m, "evidence": {**(m.get("evidence") or {}), "voix": voice}}
        cap = CAP.get(voice)
        if cap is not None and not (voice == TIERS
                                    and _speaks_of_themselves(m, _holding(m, by_id))):
            m["confidence"] = min(float(m.get("confidence", 0.5)), cap)
        out.append(m)
    return out, report
