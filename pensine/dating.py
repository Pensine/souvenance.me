"""Bounded dating: when did it happen, as far as the deposits can say.

A life-log rarely dates the events it mentions. "The kayak has not arrived
yet" (3 March) and "the kayak is already here" (11 March) do not give the
day it arrived; together they give an interval, and that interval is all
the memory may claim. Writing "it arrived on 7 March" is an invented
precision, as much an invention as a wrong name.

So a memory's event time is stored as BOUNDS (table `memory_time_bounds`,
migration 017), each backed by its own quote:

  - `earliest`: the event did not happen before this date ("not yet" on a
    deposit of 3 March gives earliest = 3 March);
  - `latest`: it had happened by this date ("already", "since", "by then");
  - an exact date is earliest == latest ("I got it on 12 March").

Admission is decided here, in code. A bound is kept only if its excerpt is
found in its deposit (`evidence.quote_found`) and carries either a date
expression or a temporal relation. The DATE is never the model's: it is
computed from the expression ("12 March", "yesterday", "in March 2025") or,
for a bare relation, taken from the deposit's own timestamp, and marked as
such (`basis = 'deposit_time'`). A relation must agree with its side ("not
yet" can only give an earliest bound) and never yields an exact date.

Combination is arithmetic, so it is code too (temporal.py principle): the
memories about one fact (same subject entity, same `event_key`) pool their
bounds; the interval is [the latest earliest, the earliest latest], each end
keeping the quote that set it. Superseded memories still count: "not yet"
stays true evidence about the past after "already" replaces it. Bounds that
cross (earliest after latest) are a contradiction, reported as such, never
averaged.

Like temporal.py, what this module returns to the reader is French by
default, English when asked; the cue lists parse both.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from . import evidence

SIDES = ("earliest", "latest", "exact")
BASES = ("excerpt_date", "deposit_time")

# Temporal relations between the event and the moment of the deposit, on
# accent-free lowercase text (temporal._norm). AFTER: the event had not
# happened yet when the deposit was made; BEFORE: it already had.
_AFTER = re.compile(
    r"\b(?:not|never|no|n't|hasn't|haven't|hadn't|isn't|aren't|wasn't|doesn't|don't|didn't)"
    r"\b(?:[\w' ]{0,40}?)\byet\b|\byet to\b|\bstill (?:no|not|waiting|hasn't|haven't|"
    r"doesn't|don't|without)\b|\bpas encore\b|\btoujours pas\b|\bpas toujours\b|"
    r"\ben attente\b|\bnot \w+ \w+ yet\b"
    # an arrival denied at the deposit: "Not delivered.", "hasn't arrived"
    r"|\b(?:not|n't|never|pas)\s+(?:\w+\s+)?(?:delivered|arrived|shipped|received|"
    r"livre|livree|arrive|arrivee|recu|recue)\b")
_BEFORE = re.compile(r"\b(?:already|by then|by now|deja|since|depuis|ever since|"
                     r"for (?:a|two|three|several|some) (?:days|weeks|months) now)\b")
# "since" / "depuis" in front of a date anchor the start: the date decides
_SINCE = re.compile(r"\b(?:since|depuis)\b")

_MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12, "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}
_MON = "|".join(sorted(_MONTHS, key=len, reverse=True))
_FR_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
              "septembre", "octobre", "novembre", "décembre"]
_EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
              "September", "October", "November", "December"]
_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "un": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "sept": 7}


def _norm(text: str) -> str:
    from .temporal import _norm as tnorm
    return re.sub(r"\s+", " ", tnorm(text)).strip()


def _day(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _month_range(y: int, m: int) -> tuple[date, date]:
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return date(y, m, 1), nxt - timedelta(days=1)


def date_range(excerpt: str, at: date) -> tuple[date, date, str] | None:
    """The period a date expression in the excerpt designates, computed from
    the deposit's own date `at`: (first day, last day, the expression).
    A day gives first == last; a month, its whole span. None without one."""
    t = _norm(excerpt)
    m = re.search(r"\b((?:19|20)\d\d)-(\d\d)-(\d\d)\b", t)
    if m and (d := _day(int(m[1]), int(m[2]), int(m[3]))):
        return d, d, m[0]
    m = (re.search(rf"\b(\d{{1,2}})(?:er|st|nd|rd|th)? ({_MON})(?:,? ((?:19|20)\d\d))?\b", t)
         or None)
    if m:
        d = _day(int(m[3]) if m[3] else at.year, _MONTHS[m[2]], int(m[1]))
        if d:
            return d, d, m[0]
    m = re.search(rf"\b({_MON}) (\d{{1,2}})(?:st|nd|rd|th)?(?:,? ((?:19|20)\d\d))?\b", t)
    if m and not (m[1] == "may" and not m[3]):
        d = _day(int(m[3]) if m[3] else at.year, _MONTHS[m[1]], int(m[2]))
        if d:
            return d, d, m[0]
    if re.search(r"\b(?:the day before yesterday|avant-hier|avant hier)\b", t):
        d = at - timedelta(days=2)
        return d, d, "avant-hier"
    if re.search(r"\b(?:yesterday|hier)\b", t):
        d = at - timedelta(days=1)
        return d, d, "hier"
    if re.search(r"\b(?:today|this morning|this afternoon|this evening|tonight|"
                 r"aujourd'hui|ce matin|cet apres-midi|ce soir)\b", t):
        return at, at, "aujourd'hui"
    m = (re.search(r"\b(\d+|\w+) days? ago\b", t)
         or re.search(r"\bil y a (\d+|\w+) jours?\b", t))
    if m:
        n = int(m[1]) if m[1].isdigit() else _NUMBERS.get(m[1])
        if n:
            d = at - timedelta(days=n)
            return d, d, m[0]
    m = re.search(rf"\b({_MON}),? ((?:19|20)\d\d)\b", t) or \
        re.search(rf"\b(?:in|en|during|pendant|since|depuis|de|d') ?({_MON})\b", t)
    if m and not (m[1] == "may" and m.lastindex == 1 and not re.search(r"\b(?:in|since) may\b", t)):
        mo = _MONTHS[m[1]]
        if m.lastindex == 2:
            y = int(m[2])
        else:  # the most recent such month, at the time of the deposit
            y = at.year if mo <= at.month else at.year - 1
        lo, hi = _month_range(y, mo)
        return lo, hi, m[0]
    return None


def relation(excerpt: str) -> str | None:
    """'after' (the event had not happened yet at the deposit: "not yet"),
    'before' (it already had: "already", "since", "by then"), or None."""
    t = _norm(excerpt)
    if _AFTER.search(t):
        return "after"
    if _BEFORE.search(t):
        return "before"
    return None


def admit(side: str, excerpt: str, source: str, deposit_at) -> tuple[dict | None, str]:
    """Is this bound proven by its excerpt? Returns (bound, reason).

    bound: {earliest, latest, basis, cue}; reason 'excerpt_date' or
    'deposit_time' when admitted, otherwise why not: 'bad_side',
    'excerpt_not_found', 'no_temporal_cue', 'relation_not_exact',
    'side_contradicts_relation', 'no_deposit_time'."""
    if side not in SIDES:
        return None, "bad_side"
    excerpt = (excerpt or "").strip()
    if not evidence.quote_found(excerpt, source):
        return None, "excerpt_not_found"
    at = _local_date(deposit_at)
    if at is None:
        return None, "no_deposit_time"
    rng = date_range(excerpt, at)
    rel = relation(excerpt)
    if rng and rel == "before" and _SINCE.search(_norm(excerpt)) \
            and not re.search(r"\b(?:already|deja|by then|by now)\b", _norm(excerpt)):
        rel = None  # "since 3 March": the date anchors the start, no relation left
    want = {"after": "earliest", "before": "latest"}.get(rel)
    if rel and side == "exact":
        return None, "relation_not_exact"
    if rel and side != want:
        return None, "side_contradicts_relation"
    if rng:
        lo, hi, cue = rng
        earliest = lo if side in ("earliest", "exact") else None
        latest = hi if side in ("latest", "exact") else None
        return {"earliest": earliest, "latest": latest, "basis": "excerpt_date",
                "cue": cue}, "excerpt_date"
    if not rel:
        return None, "no_temporal_cue"
    cue = (_AFTER if rel == "after" else _BEFORE).search(_norm(excerpt))[0]
    return {"earliest": at if rel == "after" else None,
            "latest": at if rel == "before" else None,
            "basis": "deposit_time", "cue": cue}, "deposit_time"


def _local_date(when) -> date | None:
    if isinstance(when, datetime):
        return evidence._local(when).date()
    if isinstance(when, date):
        return when
    try:
        return evidence._local(datetime.fromisoformat(str(when).replace("Z", "+00:00"))).date()
    except (TypeError, ValueError):
        return None


def event_key(text: str | None) -> str | None:
    """The comparison key of a fact ("Kofi a le kayak" = "kofi a le kayak")."""
    from .identity import norm
    k = norm(text or "")
    return k[:200] or None


def propose(citations: list[str]) -> list[dict]:
    """The bounds the code reads in a memory's own excerpts, when the model
    proposed none: "not yet" → earliest, "already" / "since" → latest, a
    date said → exact. Measured: a 4B model proposed no bound in a whole
    run (37f508d), while the excerpts said "not yet" and "already". These
    are only proposals; `store` admits each one as it admits the model's."""
    out = []
    for c in citations or []:
        if not isinstance(c, str) or not c.strip():
            continue
        t = _norm(c)
        rel = relation(c)
        has_date = date_range(c, date(2000, 1, 1)) is not None
        if rel and has_date and _SINCE.search(t) \
                and not re.search(r"\b(?:already|deja|by then|by now)\b", t):
            rel = None  # "since 3 March": the date anchors the start
        side = {"after": "earliest", "before": "latest"}.get(rel) or ("exact" if has_date else None)
        if side:
            out.append({"side": side, "excerpt": c.strip()})
    return out


def affirm(conn, memory_id: int, subject_id: int | None, key: str | None,
           citations: list[str], sources: list[int], events: dict[int, dict]) -> dict:
    """The other end of a "not yet": a later memory that states the thing as
    had ("Jonah's rowing machine has been in use for a while"), on the same
    subject and the same thing as a stored earliest bound, without the word
    "already". Its deposit is a latest bound: by then, it had happened. The
    proof is its excerpt, found in its deposit, carrying the thing and no
    "not yet"; the bound is never wider than that deposit's day."""
    if not (conn and subject_id and key and events):
        return {"admitted": 0, "refused": {}}
    open_ = _guarded(conn, """
        SELECT 1 FROM memory_time_bounds b JOIN memories m ON m.id = b.memory_id
        WHERE m.subject_entity_id = %s AND m.event_key = %s AND m.id <> %s
          AND b.earliest IS NOT NULL LIMIT 1""", (subject_id, key, memory_id))
    if not open_:
        return {"admitted": 0, "refused": {}}
    for c in citations or []:
        if not isinstance(c, str) or relation(c) or object_key(c) != key:
            continue
        for sid in sources:
            ev = events.get(sid)
            if ev is None or not evidence.quote_found(c, evidence.source_text(ev)):
                continue
            at = _local_date(ev.get("occurred_at"))
            if at is None:
                continue
            conn.execute(
                """INSERT INTO memory_time_bounds (memory_id, earliest, latest, excerpt,
                       source_event_id, basis, cue)
                   VALUES (%s, NULL, %s, %s, %s, 'deposit_time', 'affirmed after not yet')""",
                (memory_id, at, c.strip()[:evidence.MAX_CITATION], sid))
            return {"admitted": 1, "refused": {}}
    return {"admitted": 0, "refused": {"not_affirmed": 1}}


# A thing a fact is about, after "the" / "le": the head noun of what was
# got, sent, delivered ("the kayak I ordered" → kayak).
_THING = re.compile(r"(?:\b(?:the|le|la|les|mon|ma|mes|my|son|sa|ses|his|her|their|our"
                    r"|[a-z]+'s)\s+|\bl')"
                    r"((?:new|old|little|big|nouveau|nouvelle|petit|petite|grand|grande)\s+)?"
                    r"([a-z][a-z'-]{2,})")
_NOT_THINGS = {"day", "week", "month", "year", "morning", "evening", "night", "time", "way",
               "jour", "semaine", "mois", "annee", "matin", "soir", "nuit", "fois", "moment"}


def object_key(text: str | None) -> str | None:
    """A code event key: the thing the fact is about, so that "the kayak has
    not arrived yet" and "already got the kayak" pool their bounds without
    the model having to repeat the same `event_key` on two different nights.
    Pooling also requires the same subject (for_memories)."""
    for m in _THING.finditer(_norm(text or "")):
        if m[2] not in _NOT_THINGS:
            return m[2]
    return None


# ------------------------------------------------------------ combination

def interval(rows: list[dict]) -> dict | None:
    """Combine the bounds of the memories about one fact. Each row:
    {earliest, latest, excerpt, source_event_id, memory_id, basis}.
    Returns {earliest, latest, exact, conflict} where each end is the row
    that set it (or None), or None without any bound."""
    lows = [r for r in rows if r.get("earliest") is not None]
    highs = [r for r in rows if r.get("latest") is not None]
    if not lows and not highs:
        return None
    # the tightest: the latest "not before", the earliest "not after";
    # ties go to the first written (stable)
    lo = max(lows, key=lambda r: r["earliest"]) if lows else None
    hi = min(highs, key=lambda r: r["latest"]) if highs else None
    lo_d = lo["earliest"] if lo else None
    hi_d = hi["latest"] if hi else None
    conflict = bool(lo and hi and lo_d > hi_d)
    return {"earliest": _end(lo, "earliest"), "latest": _end(hi, "latest"),
            "exact": bool(lo and hi and lo_d == hi_d), "conflict": conflict}


def _end(row: dict | None, side: str) -> dict | None:
    if row is None:
        return None
    return {"date": row[side], "excerpt": row.get("excerpt"),
            "source_event_id": row.get("source_event_id"),
            "memory_id": row.get("memory_id"), "basis": row.get("basis")}


def human_date(d: date, lang: str = "fr") -> str:
    if lang == "en":
        return f"{d.day} {_EN_MONTHS[d.month - 1]} {d.year}"
    return f"{'1er' if d.day == 1 else d.day} {_FR_MONTHS[d.month - 1]} {d.year}"


def phrase(iv: dict | None, lang: str = "fr") -> str | None:
    """How to say it: never a single date unless both bounds meet.
    French by default (temporal.py convention), English with lang='en'."""
    if not iv:
        return None
    lo = iv["earliest"]["date"] if iv.get("earliest") else None
    hi = iv["latest"]["date"] if iv.get("latest") else None
    en = lang == "en"
    if iv.get("conflict"):
        return (f"conflicting evidence: not before {human_date(lo, 'en')}, yet already by "
                f"{human_date(hi, 'en')}" if en else
                f"indices contradictoires : pas avant le {human_date(lo)}, mais déjà le "
                f"{human_date(hi)}")
    if lo and hi and lo == hi:
        return f"on {human_date(lo, 'en')}" if en else f"le {human_date(lo)}"
    if lo and hi:
        return (f"between {human_date(lo, 'en')} and {human_date(hi, 'en')}" if en else
                f"entre le {human_date(lo)} et le {human_date(hi)}")
    if lo:
        return (f"not before {human_date(lo, 'en')} (no later bound known)" if en else
                f"pas avant le {human_date(lo)} (aucune borne ultérieure connue)")
    return (f"by {human_date(hi, 'en')} at the latest (no earlier bound known)" if en else
            f"au plus tard le {human_date(hi)} (aucune borne antérieure connue)")


GUIDE = (
    "Une date d'événement bornée (`date_evenement`) est calculée en code à "
    "partir d'extraits cités : ne donne jamais une date unique quand seul un "
    "intervalle est connu. Dis « entre A et B » et cite les deux sources ; "
    "« pas avant A » ou « au plus tard B » quand une seule borne existe.")


# ------------------------------------------------------------ storage

def store(conn, memory_id: int, bounds: list[dict], sources: list[int],
          events: dict[int, dict]) -> dict:
    """Admit and write a memory's proposed bounds. Each proposal:
    {side, excerpt, source_event_id?}. The source must be one of the memory's
    deposits (`sources`, looked up in `events`); a missing or wrong id is
    replaced by the deposit whose text holds the excerpt. Returns counts and
    the reasons for refusals (codes only: the audit never copies content)."""
    admitted, refused = 0, {}
    candidates = {i: events[i] for i in sources if i in events}
    for b in bounds or []:
        if not isinstance(b, dict):
            continue
        excerpt = b.get("excerpt") or b.get("extrait") or ""
        if isinstance(excerpt, list):
            excerpt = next((x for x in excerpt if isinstance(x, str)), "")
        excerpt = str(excerpt).strip()[:evidence.MAX_CITATION]
        try:
            sid = int(b.get("source_event_id"))
        except (TypeError, ValueError):
            sid = None
        if sid not in candidates:
            sid = next((i for i, e in candidates.items()
                        if evidence.quote_found(excerpt, evidence.source_text(e))), None)
        ev = candidates.get(sid)
        if ev is None:
            refused["no_source"] = refused.get("no_source", 0) + 1
            continue
        side = str(b.get("side") or "").strip().lower()
        bound, why = admit(side, excerpt, evidence.source_text(ev), ev.get("occurred_at"))
        if bound is None:
            refused[why] = refused.get(why, 0) + 1
            continue
        conn.execute(
            """INSERT INTO memory_time_bounds (memory_id, earliest, latest, excerpt,
                   source_event_id, basis, cue)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (memory_id, bound["earliest"], bound["latest"], excerpt, sid, bound["basis"],
             bound["cue"]))
        admitted += 1
    return {"admitted": admitted, "refused": refused}


def _guarded(conn, sql: str, params):
    import psycopg
    try:
        with conn.transaction():
            return conn.execute(sql, params).fetchall()
    except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn):
        return None


def for_memories(conn, memory_ids: list[int]) -> dict[int, dict]:
    """The event interval of each memory's fact, pooled over every memory
    that shares its subject and event key: {memory_id: interval}. Empty on a
    database without migration 017."""
    if not memory_ids:
        return {}
    keys = _guarded(conn, """SELECT id, subject_entity_id, event_key FROM memories
                             WHERE id = ANY(%s) AND event_key IS NOT NULL""",
                    (sorted(set(memory_ids)),)) or []
    if not keys:
        return {}
    rows = _guarded(conn, """
        SELECT b.memory_id, b.earliest, b.latest, b.excerpt, b.source_event_id, b.basis,
               m.subject_entity_id, m.event_key
        FROM memory_time_bounds b JOIN memories m ON m.id = b.memory_id
        WHERE m.event_key = ANY(%s) ORDER BY b.id""",
                    (sorted({k["event_key"] for k in keys}),)) or []
    pooled: dict[tuple, list[dict]] = {}
    for r in rows:
        pooled.setdefault((r["subject_entity_id"], r["event_key"]), []).append(dict(r))
    out = {}
    for k in keys:
        iv = interval(pooled.get((k["subject_entity_id"], k["event_key"]), []))
        if iv:
            out[k["id"]] = iv
    return out


def describe(iv: dict, lang: str = "fr") -> dict:
    """The reader's view of an interval: the phrase and each end's quote."""
    def end(e):
        return None if not e else {"date": e["date"].isoformat(), "extrait": e["excerpt"],
                                   "depot": e["source_event_id"],
                                   "base": e["basis"]}
    return {"phrase": phrase(iv, lang), "au_plus_tot": end(iv.get("earliest")),
            "au_plus_tard": end(iv.get("latest")), "contradiction": iv.get("conflict", False)}
