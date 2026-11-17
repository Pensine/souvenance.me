"""Identity claims: who is "my sister", and who says so.

A life-log names the same person in several ways: "Priya", "my sister",
"Priya, ma sœur", the sender field of a forwarded mail. Merging those mentions
into one entity is a decision, and a wrong one is costly: a fact about the
sister becomes a fact about a colleague, or about the owner. Memory graphs
usually take it silently (an LLM answers "duplicate of #12") and keep neither
the reason nor a way back.

Here each alias is a CLAIM (table `entity_aliases`, migration 015):

  - it carries the excerpt of the deposit that proves it, a confidence and
    its source deposit;
  - it is ADMITTED only if, in code, the excerpt is found in that deposit
    (`evidence.quote_found`) and names both the alias and the canonical name
    in one clause, joined by an identity form: "my sister Priya",
    "Priya, ma sœur", "my sister, Priya", "Priya (my sister)",
    "Priya is my sister" (`_FORMS`). Two names merely sharing a sentence
    ("Told Oskar that my sister works at ...", "my sister and Priya") are
    refused. Or the deposit metadata ties them (sender / author / forwarder).
    Otherwise it stays `pending`: kept, inspectable, never used;
  - only active claims take part in resolution (`resolve`);
  - retracting one closes it and reports the edges that were attached
    through it. Nothing is rewritten: the past attachment stays visible as
    what it was, a belief that has since been withdrawn.

The check is structural, not semantic: it proves that a real deposit writes
the two phrases as one designation, not that the writer was right (an
apposition can be a list read wrong: "Priya, my sister, Kofi"): hence the
stored confidence, and retraction.
"""

from __future__ import annotations

import json
import re

from . import evidence

STATUSES = ("pending", "active", "retracted", "refuted", "promoted")
TIERS = ("proven", "inferred")
ALIAS_KINDS = ("name", "role")

# How an excerpt may tie an alias to a name: the two phrases sit in ONE
# clause and are joined by an identity form, never merely side by side in a
# sentence. Each form is (what lies between the two phrases, which order,
# what must close it). Order "an" = alias then name, "na" = name then alias.
#   "my sister Priya"            nothing between, alias first
#   "Priya, my sister" / "my sister, Priya"     a comma, not a list ("and")
#   "Priya (my sister)" / "my sister (Priya)"   a parenthesis
#   "Priya - my sister"          a dash
#   "Priya is my sister" / "Priya, who is my sister" / "my sister is Priya"
# "named" and "called" are left out on purpose: "my sister named Priya the
# cat", "my sister called Priya" are verbs as often as designations.
# "Told Oskar that my sister works at ..." names both in one sentence with
# no such form: refused. So is "my sister and Priya" (two people).
_FORMS = (
    ((), "an", None),
    ((",",), "an", None), ((",",), "na", None),
    (("(",), "an", ")"), (("(",), "na", ")"),
    (("—",), "an", None), (("—",), "na", None),
    (("is",), "na", None), (("is",), "an", None),
    (("who", "is"), "na", None), ((",", "who", "is"), "na", None),
    (("est",), "na", None), (("est",), "an", None),
    (("qui", "est"), "na", None), ((",", "qui", "est"), "na", None),
)
# After a comma form, these words make the comma a list ("Priya, my sister
# and Kofi"): no apposition then.
_LIST_WORDS = {"and", "or", "et", "ou", "&"}
_SENTENCE_END = {".", "!", "?", ";", "\n"}
_TOKEN = re.compile(r"[^\W_][\w'’-]*|\n|[,;:.!?()\[\]—–]|(?<!\w)-(?!\w)")

# Excerpts longer than this cannot ground an identity claim: the longer the
# span, the likelier two names co-occur by chance.
MAX_EXCERPT = 200

# Deposit metadata that names a person by construction.
METADATA_KEYS = ("sender", "author", "from", "forwarded_by", "forwarder")


# ------------------------------------------------------------ admission

def norm(text: str) -> str:
    """evidence.normalize, plus the ligatures NFKD keeps ("sœur" = "soeur")."""
    return evidence.normalize(text).replace("œ", "oe").replace("æ", "ae")


def _tokens(text: str) -> list[str]:
    return norm(text).split()


def _clause_tokens(text: str) -> list[str]:
    """Words (normalized like `norm`) and the punctuation that structures a
    clause (commas, brackets, dashes, sentence ends), in order."""
    out: list[str] = []
    for m in _TOKEN.finditer((text or "").replace("’", "'")):
        t = m.group(0)
        if t[0].isalnum() or t[0] == "_":
            out += norm(t).split()
        elif t in "–-":
            out.append("—")
        else:
            out.append({"[": "(", "]": ")"}.get(t, t))
    return out


def _starts(phrase: list[str], words: list[str]) -> list[int]:
    n = len(phrase)
    return [i for i in range(len(words) - n + 1) if words[i:i + n] == phrase] if n else []


def _linked(alias: list[str], name: list[str], toks: list[str]) -> str | None:
    """How alias and name relate in the excerpt: 'linked' when an identity
    form joins them in one clause, 'same_sentence' when they only share a
    sentence, 'apart' when they never do, None when one is missing."""
    best = None
    for i in _starts(alias, toks):
        for j in _starts(name, toks):
            if i < j:
                first, second, order = (i, len(alias)), (j, len(name)), "an"
            else:
                first, second, order = (j, len(name)), (i, len(alias)), "na"
            end = first[0] + first[1]
            if end > second[0]:
                continue  # overlapping phrases
            between = tuple(toks[end:second[0]])
            k = second[0] + second[1]
            after = toks[k] if k < len(toks) else None
            for gap, o, close in _FORMS:
                if gap != between or o != order:
                    continue
                if close is not None and after != close:
                    continue
                if "," in gap and after in _LIST_WORDS:
                    continue
                return "linked"
            if not any(t in _SENTENCE_END for t in between):
                best = "same_sentence"
            elif best is None:
                best = "apart"
    return best


def _name_forms(canonical: str) -> list[list[str]]:
    """The full canonical name, and its given name alone ("Priya" for
    "Priya Raman"): a deposit rarely writes a relative's surname."""
    full = _tokens(canonical)
    forms = [full] if full else []
    if len(full) > 1 and len(full[0]) >= 3:
        forms.append(full[:1])
    return forms


def metadata_names(payload) -> list[str]:
    """Person names the deposit metadata carries (sender, author…)."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return []
    if not isinstance(payload, dict):
        return []
    out = []
    for k in METADATA_KEYS:
        v = payload.get(k)
        if isinstance(v, dict):
            v = v.get("name")
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    return out


def admit(alias: str, canonical: str, excerpt: str, source: str,
          metadata: list[str] | None = None) -> tuple[bool, str]:
    """Is this alias claim proven by its excerpt? Returns (admitted, reason).

    reason: 'excerpt' or 'metadata' when admitted; otherwise why not
    ('excerpt_not_found', 'excerpt_too_long', 'alias_not_in_excerpt',
    'name_not_in_excerpt', 'not_linked' (same sentence, no identity form),
    'not_adjacent' (never in the same sentence), 'same_as_name')."""
    a, names = _tokens(alias), _name_forms(canonical)
    if not a or not names:
        return False, "empty"
    if a in names:
        return False, "same_as_name"
    excerpt = (excerpt or "").strip()
    if len(excerpt) > MAX_EXCERPT:
        return False, "excerpt_too_long"
    if not evidence.quote_found(excerpt, source):
        return False, "excerpt_not_found"
    words = _tokens(excerpt)
    has_alias = bool(_starts(a, words))
    has_name = any(_starts(n, words) for n in names)
    if has_alias and has_name:
        toks = _clause_tokens(excerpt)
        how = {_linked(a, n, toks) for n in names}
        if "linked" in how:
            return True, "excerpt"
        reason = "not_linked" if "same_sentence" in how else "not_adjacent"
    else:
        reason = "alias_not_in_excerpt" if not has_alias else "name_not_in_excerpt"
    # metadata tie: the deposit's sender/author IS one side, the excerpt
    # names the other ("— Pri" in a mail whose sender is Priya Raman)
    for m in metadata or []:
        mt = _tokens(m)
        if has_alias and mt in names:
            return True, "metadata"
        if has_name and mt == a:
            return True, "metadata"
    return False, reason


# ------------------------------------------------------------ storage

def _event(conn, event_id: int | None) -> dict | None:
    if event_id is None:
        return None
    from . import db
    rows = db.source_events(conn, [event_id])
    if not rows or rows[0].get("forgotten"):
        return None
    r = rows[0]
    return {**r, "media_transcript": r.get("transcript"),
            "media_description": r.get("description")}


def propose(conn, *, entity_id: int, alias: str, excerpt: str,
            source_event_id: int | None, confidence: float = 0.5,
            alias_kind: str = "name", role_of_owner: str | None = None,
            event: dict | None = None) -> dict:
    """Record an alias claim; admitted ('active') or not ('pending').

    `event` (id, payload, media_transcript…) spares a read when the caller
    already holds the deposit. Returns {id, status, admission, shadows}:
    `shadows` lists entities already named like the alias. They are NOT
    merged: their edges stay where they are, and the caller decides."""
    if alias_kind not in ALIAS_KINDS:
        raise ValueError(f"unknown alias kind: {alias_kind}")
    alias = (alias or "").strip()
    norm_ = norm(alias)
    if not norm_:
        raise ValueError("empty alias")
    confidence = float(confidence)
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be in [0, 1]")
    ent = conn.execute("SELECT id, name, kind FROM entities WHERE id = %s",
                       (entity_id,)).fetchone()
    if not ent:
        raise ValueError(f"unknown entity: {entity_id}")
    same = conn.execute(
        """SELECT id, status, admission FROM entity_aliases
           WHERE entity_id = %s AND alias_norm = %s AND status = 'active' AND tier = 'proven'
           LIMIT 1""", (entity_id, norm_)).fetchone()
    if same:  # already believed, on a proof of its own: no second row
        return {"id": same["id"], "status": "active", "admission": same["admission"],
                "shadows": []}
    if event is None or (source_event_id is not None and event.get("id") != source_event_id):
        event = _event(conn, source_event_id)
    source = evidence.source_text(event) if event else ""
    admitted, reason = admit(alias, ent["name"], excerpt, source,
                             metadata_names(event.get("payload")) if event else [])
    row = conn.execute(
        """INSERT INTO entity_aliases (entity_id, alias, alias_norm, alias_kind,
               role_of_owner, excerpt, source_event_id, confidence, status, admission)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (entity_id, alias, norm_, alias_kind, (role_of_owner or "").strip() or None,
         (excerpt or "").strip()[:evidence.MAX_CITATION], source_event_id, confidence,
         "active" if admitted else "pending", reason)).fetchone()
    shadows = []
    if admitted:
        promote(conn, entity_id, norm_, row["id"])
        shadows = [r["id"] for r in conn.execute(
            "SELECT id FROM entities WHERE lower(name) = lower(%s) AND kind = %s AND id != %s",
            (alias, ent["kind"], entity_id)).fetchall()]
    return {"id": row["id"], "status": "active" if admitted else "pending",
            "admission": reason, "shadows": shadows}


# ------------------------------------------------------------ resolution

def _guarded(conn, sql: str, params) -> list[dict] | None:
    """Run a lookup that needs a migration; None if the table or function is
    missing (an older database resolves by exact name, as before)."""
    import psycopg
    if not hasattr(conn, "transaction"):  # no database (test doubles): nothing to read
        return None
    try:
        with conn.transaction():
            return conn.execute(sql, params).fetchall()
    except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedFunction,
            psycopg.errors.UndefinedColumn):
        return None


def resolve(conn, mention: str, kind: str | None = None) -> tuple[int, int | None] | None:
    """The entity a mention designates: (entity_id, alias_id) or None.

    In order: an active alias claim (alias_id set), the exact name (case-
    insensitive), the name compared accent- and punctuation-insensitively.
    An alias claimed for two different entities ("my colleague" for Kofi and
    for Ada) resolves to neither: it is ambiguous, and guessing would be an
    attribution error."""
    key = norm(mention or "")
    if not key:
        return None
    rows = _guarded(conn, """
        SELECT a.id AS alias_id, a.entity_id FROM entity_aliases a
        JOIN entities e ON e.id = a.entity_id
        WHERE a.alias_norm = %s AND a.status = 'active' AND a.tier = 'proven'
          AND (%s::text IS NULL OR e.kind = %s)
        ORDER BY a.id""", (key, kind, kind)) or []
    entities = {r["entity_id"] for r in rows}
    if len(entities) == 1:
        return rows[0]["entity_id"], rows[0]["alias_id"]
    if entities:
        return None  # ambiguous claim: no guess
    exact = conn.execute(
        "SELECT id FROM entities WHERE lower(name) = lower(%s) "
        "AND (%s::text IS NULL OR kind = %s) ORDER BY id LIMIT 1",
        (mention.strip(), kind, kind)).fetchone()
    if exact:
        return exact["id"], None
    loose = _guarded(conn, r"""
        SELECT id FROM entities
        WHERE btrim(regexp_replace(regexp_replace(lower(pensine_unaccent(name)),
                    '[^[:alnum:]_'' ]+', ' ', 'g'), '\s+', ' ', 'g')) = %s
          AND (%s::text IS NULL OR kind = %s)
        ORDER BY id LIMIT 2""", (evidence.normalize(mention), kind, kind)) or []
    # two entities that differ only by an accent: do not pick one
    return (loose[0]["id"], None) if len(loose) == 1 else None


def resolve_alias(conn, mention: str, kind: str | None = None) -> list[int]:
    """The entities an active claim gives to this mention (for inspection)."""
    rows = _guarded(conn, """
        SELECT DISTINCT a.entity_id FROM entity_aliases a JOIN entities e ON e.id = a.entity_id
        WHERE a.alias_norm = %s AND a.status = 'active' AND a.tier = 'proven'
          AND (%s::text IS NULL OR e.kind = %s) ORDER BY a.entity_id""",
        (norm(mention or ""), kind, kind)) or []
    return [r["entity_id"] for r in rows]


# ------------------------------------------------------------ retraction

def retract(conn, alias_id: int, reason: str) -> dict:
    """Withdraw a claim. Later mentions of the alias no longer reach the
    entity (they split off again). Returns the claim, and the edges and
    memories that were attached through it: they are reported, never rewritten — deciding what
    they now mean is a new decision, with its own trace."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("a retraction needs a reason")
    row = conn.execute(
        """UPDATE entity_aliases SET status = 'retracted', retracted_at = now(),
                  retract_reason = %s
           WHERE id = %s AND status != 'retracted'
           RETURNING id, entity_id, alias, status, retracted_at""",
        (reason, alias_id)).fetchone()
    if not row:
        raise ValueError(f"claim {alias_id} unknown or already retracted")
    edges = conn.execute(
        """SELECT r.id, s.name AS subject, r.predicate, o.name AS object,
                  r.valid_from, r.valid_to, r.source_event_ids
           FROM relations r
           JOIN entities s ON s.id = r.subject_id
           JOIN entities o ON o.id = r.object_id
           WHERE %s = ANY(r.via_alias_ids) ORDER BY r.id""", (alias_id,)).fetchall()
    # memories whose subject was resolved through the claim (migration 016):
    # reported the same way, never moved
    mems = _guarded(conn, """SELECT id, content, subject_entity_id FROM memories
                              WHERE subject_alias_id = %s ORDER BY id""", (alias_id,)) or []
    return {**dict(row), "relations": [dict(e) for e in edges],
            "memories": [dict(m) for m in mems]}


def claims(conn, entity_id: int) -> list[dict]:
    """Every claim about an entity, pending and retracted included, oldest
    first: what was believed about who this is, and on what proof."""
    return [dict(r) for r in conn.execute(
        """SELECT id, alias, alias_kind, role_of_owner, excerpt, source_event_id,
                  confidence, status, admission, created_at, retracted_at, retract_reason
           FROM entity_aliases WHERE entity_id = %s ORDER BY created_at, id""",
        (entity_id,)).fetchall()]


# ------------------------------------------------------------ inferred tier
#
# Coverage without giving up evidence (migration 018). Many identities are
# never written as one designation: "my aunt lives in Porto" one day, "Ines
# lives in Porto" another, "my aunt works at Saltire Glassworks", "Ines works
# at Saltire Glassworks". The night may PROPOSE that "my aunt" is Ines; the
# code builds the claim only from converging supports it can check:
#
#   - each support is one attribute value written next to the alias in one
#     deposit and next to the name in ANOTHER, both excerpts found in their
#     deposit (`evidence.quote_found`) and both containing the value;
#   - a generic value ("from home", "the office") supports nothing;
#   - at least MIN_SUPPORTS independent supports (distinct values, distinct
#     pairs of deposits); the confidence grows with their number and stays
#     below a proven claim's;
#   - the two found together in one deposit without an identity form ("lunch
#     with my aunt and Ines"), or verified evidence of two different places
#     at the same time, refutes the hypothesis, with the reason.
#
# An inferred claim never resolves a mention (resolution reads proven claims
# only): recall shows it with a hedge, nothing is attached through it. It is
# promoted when a later deposit writes the identity form, or when the owner
# confirms it through the proposal path (pensine/proposals.py).

MIN_SUPPORTS = 2
GENERIC_VALUES = {"home", "from home", "at home", "the office", "an office", "work", "the city",
                  "town", "the city centre", "the centre", "the gym", "a cafe", "the cafe",
                  "nearby", "the area", "london", "paris", "a bank", "a school", "a shop",
                  "la maison", "a la maison", "le bureau", "la ville", "le centre"}
PRONOUNS = {"he", "she", "they", "him", "her", "them", "il", "elle", "lui", "ils", "elles"}
_SAME_TIME_DAYS = 30


def _name_in(names: list[list[str]], toks: list[str]) -> bool:
    return any(_starts(n, toks) for n in names)


def generic(value: str) -> bool:
    v = norm(value)
    words = [w for w in v.split() if w not in {"the", "a", "an", "le", "la", "les", "un", "une"}]
    return v in GENERIC_VALUES or not words or len(v) < 3


def _support(s: dict, alias: list[str], names: list[list[str]], fetch) -> tuple[dict | None, str]:
    """Check one support: (verified support, '') or (None, why)."""
    value = str(s.get("attribute") or s.get("value") or "").strip()
    if not value or generic(value):
        return None, "generic_attribute"
    vt = _tokens(value)
    try:
        ea, en = int(s.get("alias_event_id")), int(s.get("name_event_id"))
    except (TypeError, ValueError):
        return None, "no_source"
    if ea == en:
        return None, "same_deposit"
    a_ev, n_ev = fetch(ea), fetch(en)
    if not a_ev or not n_ev:
        return None, "no_source"
    xa, xn = str(s.get("alias_excerpt") or "").strip(), str(s.get("name_excerpt") or "").strip()
    if not (evidence.quote_found(xa, evidence.source_text(a_ev))
            and evidence.quote_found(xn, evidence.source_text(n_ev))):
        return None, "excerpt_not_found"
    ta, tn = _tokens(xa), _tokens(xn)
    if not _starts(alias, ta) or not _name_in(names, tn):
        return None, "side_not_named"
    if not (_starts(vt, ta) and _starts(vt, tn)):
        return None, "value_not_in_both"
    return {"attribute": value, "alias_excerpt": xa[:evidence.MAX_CITATION],
            "alias_event_id": ea, "name_excerpt": xn[:evidence.MAX_CITATION],
            "name_event_id": en}, ""


def _against(s: dict, alias, names, fetch) -> dict | None:
    """Verified evidence of two different places at the same time."""
    va, vn = (str(s.get(k) or "").strip() for k in ("alias_value", "name_value"))
    if not va or not vn or norm(va) == norm(vn):
        return None
    try:
        ea, en = int(s.get("alias_event_id")), int(s.get("name_event_id"))
    except (TypeError, ValueError):
        return None
    a_ev, n_ev = fetch(ea), fetch(en)
    if not a_ev or not n_ev:
        return None
    xa, xn = str(s.get("alias_excerpt") or ""), str(s.get("name_excerpt") or "")
    if not (evidence.quote_found(xa, evidence.source_text(a_ev))
            and evidence.quote_found(xn, evidence.source_text(n_ev))):
        return None
    ta, tn = _tokens(xa), _tokens(xn)
    if not (_starts(alias, ta) and _starts(_tokens(va), ta)
            and _name_in(names, tn) and _starts(_tokens(vn), tn)):
        return None
    try:
        gap = abs((a_ev["occurred_at"] - n_ev["occurred_at"]).days)
    except (KeyError, TypeError):
        return None
    if gap > _SAME_TIME_DAYS:
        return None
    return {"alias_value": va, "name_value": vn, "alias_event_id": ea, "name_event_id": en}


def together(text: str, alias: list[str], names: list[list[str]]) -> str | None:
    """'linked' if the text writes alias and name as one designation,
    'together' if it names both otherwise (two people), None if not both."""
    toks = _clause_tokens(text)
    words = [t for t in toks if t[0].isalnum() or t[0] == "_"]
    if not _starts(alias, words) or not _name_in(names, words):
        return None
    return "linked" if any(_linked(alias, n, toks) == "linked" for n in names) else "together"


def _copresence(conn, alias: list[str], names: list[list[str]]) -> int | None:
    """A deposit that names both without an identity form (searched by the
    name; sealed deposits are not searchable and are not seen here)."""
    probe = " ".join(names[-1])
    rows = conn.execute(
        """SELECT e.id, e.occurred_at, e.payload, m.transcript AS media_transcript,
                  m.description AS media_description
           FROM events e LEFT JOIN media m ON m.id = e.media_id
           WHERE pensine_unaccent(lower(e.payload::text || ' ' || coalesce(m.transcript, '')))
                 LIKE '%%' || %s || '%%' ORDER BY e.id LIMIT 500""", (probe,)).fetchall()
    for r in rows:
        if together(evidence.source_text(dict(r)), alias, names) == "together":
            return r["id"]
    return None


def infer(conn, *, entity_id: int, alias: str, supports: list[dict],
          against: list[dict] | None = None, alias_kind: str = "role",
          role_of_owner: str | None = None) -> dict:
    """Record an identity HYPOTHESIS (tier 'inferred'), checked in code.
    Returns {id, status, admission, confidence, supports}: 'active' with
    enough independent supports, 'refuted' on contradicting evidence (kept,
    with the reason), 'pending' otherwise. An active one also opens a
    proposal the owner can confirm (proposals.confirm promotes it)."""
    if alias_kind not in ALIAS_KINDS:
        alias_kind = "role"
    a = _tokens(alias)
    ent = conn.execute("SELECT id, name FROM entities WHERE id = %s", (entity_id,)).fetchone()
    if not a or not ent:
        raise ValueError("unknown entity or empty alias")
    names = _name_forms(ent["name"])
    key = norm(alias)
    open_ = conn.execute(
        """SELECT id, status, tier, admission, confidence FROM entity_aliases
           WHERE entity_id = %s AND alias_norm = %s AND status = 'active'
           ORDER BY tier = 'proven' DESC LIMIT 1""", (entity_id, key)).fetchone()
    if open_:
        return {"id": open_["id"], "status": "active", "tier": open_["tier"],
                "admission": open_["admission"], "confidence": open_["confidence"],
                "supports": []}
    cache: dict = {}

    def fetch(i):
        if i not in cache:
            cache[i] = _event(conn, i)
        return cache[i]
    kept, used_values, used_pairs, why = [], set(), set(), {}
    for s in supports or []:
        ok, reason = _support(s, a, names, fetch) if isinstance(s, dict) else (None, "bad")
        if not ok:
            why[reason] = why.get(reason, 0) + 1
            continue
        v, pair = norm(ok["attribute"]), (ok["alias_event_id"], ok["name_event_id"])
        if v in used_values or pair in used_pairs:
            why["not_independent"] = why.get("not_independent", 0) + 1
            continue
        used_values.add(v)
        used_pairs.add(pair)
        kept.append(ok)
    refuted = None
    for s in against or []:
        c = _against(s, a, names, fetch) if isinstance(s, dict) else None
        if c:
            refuted = (f"different places at the same time: {c['alias_value']} "
                       f"(deposit {c['alias_event_id']}) vs {c['name_value']} "
                       f"(deposit {c['name_event_id']})")
            break
    if not refuted and len(kept) >= MIN_SUPPORTS:
        seen = _copresence(conn, a, names)
        if seen:
            refuted = f"present together in deposit {seen}"
    k = len(kept)
    confidence = round(min(0.75, 0.4 + 0.1 * k), 2) if k else 0.0
    status = "refuted" if refuted else "active" if k >= MIN_SUPPORTS else "pending"
    admission = (f"converging:{k}" if status == "active" else "refuted" if refuted
                 else "insufficient_supports")
    proposal_id = None
    if status == "active":
        from . import proposals
        values = ", ".join(f"“{x['attribute']}”" for x in kept)
        proposal_id = proposals.propose(
            conn, f"Is “{alias}” the same person as {ent['name']}? Probably: both are "
                  f"tied to {values}, in different deposits.", "inference",
            "identity hypothesis built in code from quoted supports; confirming it "
            "makes it a proven claim")["id"]
    row = conn.execute(
        """INSERT INTO entity_aliases (entity_id, alias, alias_norm, alias_kind,
               role_of_owner, excerpt, source_event_id, confidence, status, admission,
               tier, supports, proposal_id, retracted_at, retract_reason)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'inferred', %s, %s, %s, %s)
           RETURNING id""",
        (entity_id, alias.strip(), key, alias_kind, (role_of_owner or "").strip() or None,
         kept[0]["alias_excerpt"] if kept else "",
         max(x["alias_event_id"] for x in kept) if kept else None, confidence, status,
         admission, json.dumps(kept, ensure_ascii=False), proposal_id,
         _now() if refuted else None, refuted)).fetchone()
    return {"id": row["id"], "status": status, "tier": "inferred", "admission": admission,
            "confidence": confidence, "supports": kept, "refused": why}


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def promote(conn, entity_id: int, alias_norm: str, proven_id: int) -> list[int]:
    """Close the open inferred claims a proven one now confirms."""
    rows = _guarded(conn, """
        UPDATE entity_aliases SET status = 'promoted', promoted_to = %s,
               retracted_at = now(), retract_reason = 'promoted to a proven claim'
        WHERE entity_id = %s AND alias_norm = %s AND tier = 'inferred'
          AND status IN ('active', 'pending') RETURNING id""",
                    (proven_id, entity_id, alias_norm)) or []
    return [r["id"] for r in rows]


def refute(conn, claim_id: int, reason: str) -> bool:
    row = conn.execute(
        """UPDATE entity_aliases SET status = 'refuted', retracted_at = now(),
                  retract_reason = %s
           WHERE id = %s AND tier = 'inferred' AND status IN ('active', 'pending')
           RETURNING id""", (reason, claim_id)).fetchone()
    return bool(row)


def check_deposits(conn, events: list[dict]) -> dict:
    """Tonight's deposits against the open hypotheses: an identity form
    promotes (through a proven claim of its own), a co-mention without one
    refutes. Returns counts."""
    rows = _guarded(conn, """SELECT a.id, a.entity_id, a.alias, a.alias_kind, a.role_of_owner,
                                    e.name FROM entity_aliases a
                             JOIN entities e ON e.id = a.entity_id
                             WHERE a.tier = 'inferred' AND a.status = 'active'""", ()) or []
    out = {"hypotheses_promoted": 0, "hypotheses_refuted": 0}
    for h in rows:
        a, names = _tokens(h["alias"]), _name_forms(h["name"])
        for ev in events:
            text = evidence.source_text(ev)
            how = together(text, a, names)
            if how == "together":
                refute(conn, h["id"], f"present together in deposit {ev['id']}")
                out["hypotheses_refuted"] += 1
                break
            if how == "linked":
                sentence = next((x for x in re.split(r"(?<=[.!?;])\s+|\n", text)
                                 if together(x, a, names) == "linked"), "")
                r = propose(conn, entity_id=h["entity_id"], alias=h["alias"],
                            excerpt=sentence[:MAX_EXCERPT], source_event_id=ev["id"],
                            confidence=0.9, alias_kind=h["alias_kind"],
                            role_of_owner=h["role_of_owner"], event=ev)
                out["hypotheses_promoted"] += r["status"] == "active"
                break
    return out


def on_confirmed(conn, proposal_id: int, event_id: int) -> int | None:
    """The owner confirmed an identity proposal: a proven claim whose proof
    is the confirmation event, and the hypothesis is promoted."""
    h = _guarded(conn, """SELECT id, entity_id, alias, alias_norm, alias_kind, role_of_owner
                          FROM entity_aliases WHERE proposal_id = %s AND tier = 'inferred'
                            AND status = 'active'""", (proposal_id,))
    if not h:
        return None
    h = h[0]
    row = conn.execute(
        """INSERT INTO entity_aliases (entity_id, alias, alias_norm, alias_kind, role_of_owner,
               excerpt, source_event_id, confidence, status, admission, tier)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 0.95, 'active', 'owner_confirmed', 'proven')
           RETURNING id""",
        (h["entity_id"], h["alias"], h["alias_norm"], h["alias_kind"], h["role_of_owner"],
         "confirmed by the owner", event_id)).fetchone()
    promote(conn, h["entity_id"], h["alias_norm"], row["id"])
    return row["id"]


def on_declined(conn, proposal_id: int) -> None:
    for h in _guarded(conn, "SELECT id FROM entity_aliases WHERE proposal_id = %s "
                            "AND tier = 'inferred'", (proposal_id,)) or []:
        refute(conn, h["id"], "declined by the owner")


def ingest_hypotheses(conn, hyps: list[dict]) -> dict:
    """The night's identity hypotheses ({name, alias, supports, against?,
    role_of_owner?}): each checked by `infer`."""
    from . import graph
    out = {"hypotheses_active": 0, "hypotheses_pending": 0, "hypotheses_refuted": 0}
    for h in hyps or []:
        name, alias = (str(h.get("name") or "").strip(), str(h.get("alias") or "").strip())
        if not name or not alias or not isinstance(h.get("supports"), list):
            continue
        r = infer(conn, entity_id=graph.upsert_entity(conn, name, h.get("kind") or "person"),
                  alias=alias, supports=h["supports"],
                  against=h.get("against") if isinstance(h.get("against"), list) else [],
                  alias_kind="role" if h.get("role_of_owner") else "name",
                  role_of_owner=h.get("role_of_owner"))
        if r.get("tier") == "inferred" and f"hypotheses_{r['status']}" in out:
            out[f"hypotheses_{r['status']}"] += 1
    return out


def owner_voice(query: str, owner: str = "") -> str:
    """The question in the owner's voice: "Ivo's brother" asked about the
    owner Ivo is "my brother", the way the deposits and the claims say it."""
    first = (owner or "").split()[0] if (owner or "").strip() else ""
    if not first or not first[:1].isalpha():
        return query
    return re.sub(rf"\b{re.escape(first)}['’]s\b", "my", query, flags=re.IGNORECASE)


def _proven(conn) -> list[dict]:
    return _guarded(conn, """SELECT a.alias, a.entity_id, e.name
                             FROM entity_aliases a JOIN entities e ON e.id = a.entity_id
                             WHERE a.tier = 'proven' AND a.status = 'active'
                             ORDER BY a.id""", ()) or []


def _covered(start: int, n: int, spans: list[tuple[int, int]]) -> bool:
    """Is the phrase at [start, start+n) inside a longer phrase found there?"""
    return any(s <= start and start + n <= s + m and m > n for s, m in spans)


# What opens a role's qualifier: "my sister FROM the old flat", "ma sœur DU
# club". A qualified role is another designation than the bare one.
_QUALIFIER = {"from", "of", "at", "in", "du", "de", "des"}


def designation(conn, mention: str, text: str, owner: str = "") -> str | None:
    """The designation a memory writes, read against the proven claims.

    A model often shortens a role ("my sister" for "my sister from the old
    flat"); resolving the short form through a proven "my sister = Vera"
    would hand the fact to the wrong sister. So, where `text` writes the
    mention: the longest proven alias written there wins; a mention written
    there only with a qualifier no proven alias covers designates no one we
    know (None). Otherwise the mention as given."""
    m, toks = _tokens(mention), _tokens(owner_voice(text or "", owner))
    at = _starts(m, toks) if m else []
    if not at:
        return mention
    longer = [r for r in _proven(conn)
              if len(_tokens(r["alias"])) > len(m) and _tokens(r["alias"])[:len(m)] == m]
    for r in sorted(longer, key=lambda r: -len(_tokens(r["alias"]))):
        if set(_starts(_tokens(r["alias"]), toks)) & set(at):
            return r["alias"]
    def qualified(i: int) -> bool:
        k = i + len(m)
        return k < len(toks) and (toks[k] in _QUALIFIER or toks[k].startswith("d'"))
    if all(qualified(i) for i in at):
        return None
    return mention


def proven_in(conn, query: str, owner: str = "") -> list[dict]:
    """The proven identity claims the question names: by alias ("my brother"
    → Dev) or by name ("Dev" → my brother: the memories may say only "my
    brother"). [{alias, name, entity_id, by}], by = 'alias' or 'name'. An
    alias inside a longer one the question writes ("my sister" in "my sister
    from the old flat") is not that one. Only the proven tier: an inferred
    claim is shown hedged and used for nothing (hypotheses_for)."""
    q = _tokens(owner_voice(query, owner))
    rows = _proven(conn)
    by_alias: dict[str, set[int]] = {}
    for r in rows:
        by_alias.setdefault(norm(r["alias"]), set()).add(r["entity_id"])
    spans = [(i, len(_tokens(r["alias"]))) for r in rows for i in _starts(_tokens(r["alias"]), q)]
    out, seen = [], set()
    for r in rows:
        if len(by_alias[norm(r["alias"])]) > 1:
            continue  # ambiguous claim: no bridge
        a = _tokens(r["alias"])
        hits = [i for i in _starts(a, q) if not _covered(i, len(a), spans)]
        by = "alias" if hits else ("name" if _name_in(_name_forms(r["name"]), q) else None)
        if by and (r["alias"], r["entity_id"]) not in seen:
            seen.add((r["alias"], r["entity_id"]))
            out.append({"alias": r["alias"], "name": r["name"], "entity_id": r["entity_id"],
                        "by": by})
    return out


def named_entities(conn, query: str, owner: str = "") -> set[int]:
    """The people the question names by name ("Which company does Dev work
    for?"), the owner aside. For RECALL only: a given name two entities share
    ("Vera", "Vera Novak") brings back both, and the reader sees each memory
    with its own words; nothing is attached through this."""
    q = _tokens(query)
    rows = _guarded(conn, "SELECT id, name FROM entities WHERE kind = 'person'", ()) or []
    own = _tokens(owner)
    hits: dict[str, set[int]] = {}
    for r in rows:
        forms = _name_forms(r["name"])
        if not forms or forms[0] == own or (own and forms[-1] == own[:1]):
            continue
        for f in forms:
            if _starts(f, q):
                hits.setdefault(" ".join(f), set()).add(r["id"])
    return {i for ids in hits.values() for i in ids}


def hypotheses_for(conn, query: str, lang: str = "fr") -> list[dict]:
    """Open hypotheses about who is named in the question, worded with their
    hedge. Never used to answer as if proven."""
    q = _tokens(query)
    rows = _guarded(conn, """SELECT a.id, a.alias, a.confidence, a.supports, e.name
                             FROM entity_aliases a JOIN entities e ON e.id = a.entity_id
                             WHERE a.tier = 'inferred' AND a.status = 'active'
                             ORDER BY a.id""", ()) or []
    out = []
    for r in rows:
        a, names = _tokens(r["alias"]), _name_forms(r["name"])
        if not (_starts(a, q) or _name_in(names, q)):
            continue
        sup = r["supports"] if isinstance(r["supports"], list) else json.loads(r["supports"])
        if lang == "en":
            because = "; ".join(f"both are tied to “{s['attribute']}” (deposits "
                                f"{s['alias_event_id']} and {s['name_event_id']})" for s in sup)
            text = (f"“{r['alias']}” is probably the same person as {r['name']}, because "
                    f"{because}. Inferred, not proven: no fact is attached through it.")
        else:
            because = " ; ".join(f"tous deux liés à « {s['attribute']} » (dépôts "
                                 f"{s['alias_event_id']} et {s['name_event_id']})" for s in sup)
            text = (f"« {r['alias']} » est probablement la même personne que {r['name']}, "
                    f"parce que {because}. Hypothèse, non prouvée : aucun fait n'est "
                    f"attaché par elle.")
        out.append({"id": r["id"], "phrase": text, "confiance": r["confidence"],
                    "appuis": sup})
    return out


def pronoun_referent(pronoun: str, text: str, names: list[str]) -> str | None:
    """Within ONE deposit only: the person a pronoun designates, when exactly
    one known person is named before its first occurrence; otherwise None.
    Never across deposits."""
    p = norm(pronoun)
    if p not in PRONOUNS:
        return None
    toks = [t for t in _clause_tokens(text) if t[0].isalnum() or t[0] == "_"]
    if p not in toks:
        return None
    before = toks[:toks.index(p)]
    found = {n for n in names if any(_starts(f, before) for f in _name_forms(n))}
    return found.pop() if len(found) == 1 else None
