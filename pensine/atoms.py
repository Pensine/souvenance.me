"""One fact per memory, its subject read by a model, its proof checked in code.

Measured on SOURCED (third Qwen 3.5 4B run, 37f508d): 37 % of the memories
that state a gold fact named the wrong person, and nearly all of them named
the owner. Two causes, neither of them the model's alone:

  - a memory glued two facts of one deposit ("Watered the plants on the
    balcony. My aunt lives in Valencia now.") under one `subject` field, so
    one of the two was bound to be wrong;
  - the model wrote the owner as the subject by default, even for a fact it
    reported about someone else ("Ran into Dina, who works at Mistral
    Joinery." → subject: the owner).

So before the evidence cascade, each candidate is split into its sentences
when they are about different people, and each part gets the subject its
SENTENCE gives. The sentence is read by a model (pensine/readers.py, GLiNER2),
not by grammar rules: hand-written rules here went from 37 % to 3 % errors on
the dev phrasing they were written on, and stayed at 26 % on the sealed set.

What the reader does not say stays the model's word, except the owner: the
model's default is precisely the measured error, so a sentence the code
cannot attribute keeps no subject rather than the owner. A memory without a
subject is honest; one on the wrong person is an attribution error
(graph.resolve_subject).

A part is never split from the excerpt that proves it: each part keeps the
citations that overlap its sentence (or the sentence itself, when it is
written word for word in the deposit), and goes through the cascade on its
own.

Also here, `interpretive`: a memory that narrates the record instead of the
life ("The subject reports a change…", "Uncertainty regarding the identity of
'Silas' versus the previously mentioned 'uncle'") states nothing a deposit
says. Its excerpts exist, so the excerpt tier let it through; it is rejected
in the cascade (pensine/evidence.py). A doubt about who is who has its own
channel, `identity_hypotheses`, checked in code.

Without the reader (no `gliner2`, PENSINE_READER=none), every sentence is
unread: the model's word is kept, never its owner default.
"""

from __future__ import annotations

import re

from . import evidence, readers

OWNER = "I"  # what consolidation.nightly.memory_subject maps to the owner

_PRONOUNS = {"he", "she", "they", "il", "elle", "ils", "elles"}
_POSSESSIVE = r"(?:my|our|mon|ma|mes|notre|nos)"


def sentences(text: str) -> list[str]:
    """The sentences of a memory, end punctuation kept."""
    parts = re.split(r"(?<=[.!?;])\s+(?=[\"'«(]?[A-ZÀ-Ý])", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _tokens(sentence: str) -> list[str]:
    return evidence.normalize(sentence).replace("'", "' ").split()


def subject_of(sentence: str, names: set[str] | frozenset = frozenset()) -> str | None:
    """Whom ONE sentence states its fact about, READ by a model
    (pensine/readers.py): a mention as written ("Dina", "my aunt"), OWNER, a
    pronoun opening the sentence (resolved later, within its deposit), or
    None when the reading does not say. `names` is kept for callers."""
    s = sentence.strip()
    if not s:
        return None
    first = evidence.normalize(s).split()[0] if evidence.normalize(s) else ""
    if first in _PRONOUNS:
        return first  # continues the previous sentence
    who = readers.subject(s)
    if who in (None, OWNER):
        return who
    who = re.sub(r"\s+", " ", who).strip(" ,")
    if re.match(rf"{_POSSESSIVE}\s", who, re.IGNORECASE):
        return who[0].lower() + who[1:]  # a role, as the model writes it: "my sister"
    return who


def _key(subject: str | None) -> str | None:
    return evidence.normalize(subject) if subject else None


def _overlap(a: str, b: str) -> float:
    wa, wb = set(evidence.normalize(a).split()), set(evidence.normalize(b).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def _citations(memory: dict) -> list[str]:
    raw = memory.get("preuve") or []
    return [raw] if isinstance(raw, str) else [c for c in raw if isinstance(c, str)]


def atomize(memory: dict, sources: list[str] | None = None,
            names: set[str] | frozenset = frozenset(), owner: str = "",
            incoming: bool = False) -> list[dict]:
    """One candidate memory → one memory per fact, each with the subject its
    sentence gives. `sources`: the texts of the memory's deposits (to cite a
    sentence written word for word). Sentences about the same person stay
    together; a sentence that opens on a pronoun continues the previous one.
    `incoming`: every deposit of the memory was received (a voice message, a
    letter): its "I" is the sender, never the owner."""
    content = (memory.get("content") or "").strip()
    parts: list[list] = []  # [text, subject]
    for s in sentences(content):
        who = subject_of(s, names)
        if parts and (who in _PRONOUNS or who is None):
            parts[-1][0] += " " + s
            continue
        if parts and _key(who) == _key(parts[-1][1]):
            parts[-1][0] += " " + s
            continue
        parts.append([s, who])
    if len(parts) <= 1:
        who = parts[0][1] if parts else None
        return [_with_subject(memory, who, owner, incoming)]
    text = "\n".join(sources or [])
    cites = _citations(memory)
    out = []
    for i, (s, who) in enumerate(parts):
        mine = [c for c in cites if _overlap(c, s) >= 0.5]
        if not mine and text and evidence.quote_found(s, text):
            mine = [s]
        part = {k: v for k, v in memory.items() if k not in ("event_key", "remplace", "raison")}
        part.update(content=s, preuve=mine or cites)
        if memory.get("event_bounds"):
            part["event_bounds"] = [b for b in memory["event_bounds"]
                                    if _overlap(str(b.get("excerpt") or ""), s) >= 0.5]
            if not part["event_bounds"]:
                part.pop("event_bounds")
        out.append(_with_subject(part, who, owner, incoming))
    # what the memory replaced goes with the part about someone other than
    # the diary voice when there is one such part, otherwise with the last
    if memory.get("remplace"):
        others = [p for p in out if p.get("subject") not in (None, OWNER)]
        target = others[0] if len(others) == 1 else out[-1]
        target["remplace"] = memory["remplace"]
        if memory.get("raison"):
            target["raison"] = memory["raison"]
    return out


def _with_subject(memory: dict, who: str | None, owner: str = "",
                  incoming: bool = False) -> dict:
    m = dict(memory)
    held = re.match(r"^(\S+)'s (.+)$", who or "")
    if held and _is_owner(held[1], owner):
        who = f"my {held[2]}"  # the owner's aunt, as the model writes a role
    if incoming and who is not None and _is_owner(who, owner):
        who = None  # someone else's "I": the code does not know who sent it
    if who is not None and _is_owner(who, owner):
        m["subject"] = OWNER
    elif who is not None:
        m["subject"] = who  # a pronoun is resolved within its deposit, or to nobody
    elif _is_owner(m.get("subject") or "", owner):
        # the code cannot read it: the model's word, never its owner default
        m.pop("subject", None)
    return m


def _is_owner(mention: str, owner: str) -> bool:
    k = evidence.normalize(mention)
    if not k:
        return False
    if k in OWNER_WORDS:
        return True
    o = evidence.normalize(owner)
    return bool(o) and (k == o or k == o.split()[0])


# How a memory may name its owner (as consolidation.nightly.OWNER_WORDS).
OWNER_WORDS = {"i", "me", "myself", "je", "moi", "owner", "user", "the owner", "the user"}


# ------------------------------------------------------------ interpretation

_META = re.compile(
    r"\bthe (?:subject|user|owner|narrator|author|speaker|writer)\b"
    r"|\b(?:previous|new|latest|earlier|this|that|the) (?:entry|entries|note|record|log)\b"
    r"|\bpreviously (?:mentioned|stated|noted|reported)\b"
    r"|\bsupersed\w* (?:the |a )?(?:previous|earlier|prior)\b"
    r"|\breplacing (?:the|a) (?:previous|earlier)\b"
    r"|\buncertainty (?:regarding|about|over|as to)\b|\bit is (?:unclear|not clear)\b"
    r"|\bl'utilisateur\b|\bl'auteur\b|\ble narrateur\b"
    r"|\ble sujet (?:rapporte|indique|mentionne|dit|signale|evoque)\b"
    r"|\bprecedemment (?:mentionne|cite|evoque|indique)\w*\b"
    r"|\b(?:l'entree|la note|le message) (?:precedente?|anterieure?)\b"
    r"|\bincertitude (?:sur|quant|concernant|au sujet)\b|\bil n'est pas clair\b")


def interpretive(content: str) -> bool:
    """Does the memory narrate the record (the entries, "the subject", a
    doubt about the notes) instead of stating what a deposit says?"""
    return bool(_META.search(evidence.normalize(content or "")))
