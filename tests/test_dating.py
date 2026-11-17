"""Bounded dating: a bound needs a quote, the date is computed, the interval derived."""

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from pensine import dating

A = datetime(2025, 3, 3, 18, tzinfo=timezone.utc)   # "not yet"
B = datetime(2025, 3, 11, 9, tzinfo=timezone.utc)   # "already"
NOT_YET = "Long day. The kayak I ordered has not arrived yet, maybe next week."
ALREADY = "Took the kayak out on the lake, it is already scratched."
DATED = "Got the keys on 12 March 2025, finally. Moved in yesterday."


# --- admission, in code ------------------------------------------------------

def test_relation_bound_takes_the_deposit_date():
    b, why = dating.admit("earliest", "The kayak I ordered has not arrived yet", NOT_YET, A)
    assert why == "deposit_time" and b["earliest"] == date(2025, 3, 3) and b["latest"] is None
    b, why = dating.admit("latest", "it is already scratched", ALREADY, B)
    assert why == "deposit_time" and b["latest"] == date(2025, 3, 11) and b["earliest"] is None


def test_date_expression_is_computed_not_taken_from_the_model():
    b, why = dating.admit("exact", "Got the keys on 12 March 2025", DATED, A)
    assert why == "excerpt_date" and b["earliest"] == b["latest"] == date(2025, 3, 12)
    b, _ = dating.admit("exact", "Moved in yesterday", DATED, A)
    assert b["earliest"] == b["latest"] == date(2025, 3, 2)     # relative to the deposit
    assert dating.date_range("sometime in March 2025", date(2025, 6, 1))[:2] == \
        (date(2025, 3, 1), date(2025, 3, 31))
    assert dating.date_range("depuis mars", date(2025, 6, 1))[:2] == \
        (date(2025, 3, 1), date(2025, 3, 31))
    assert dating.date_range("le 1er avril 2025", date(2025, 6, 1))[:2] == \
        (date(2025, 4, 1), date(2025, 4, 1))
    assert dating.date_range("it may rain", date(2025, 6, 1)) is None


@pytest.mark.parametrize("side, excerpt, src, why", [
    ("earliest", "The canoe has not arrived yet", NOT_YET, "excerpt_not_found"),
    ("exact", "Took the kayak out on the lake", ALREADY, "no_temporal_cue"),
    ("exact", "it is already scratched", ALREADY, "relation_not_exact"),
    ("earliest", "it is already scratched", ALREADY, "side_contradicts_relation"),
    ("latest", "has not arrived yet, maybe next week", NOT_YET, "side_contradicts_relation"),
    ("soon", "it is already scratched", ALREADY, "bad_side"),
])
def test_bounds_without_proof_are_refused(side, excerpt, src, why):
    assert dating.admit(side, excerpt, src, A) == (None, why)


def test_french_relations():
    src = "Le vélo n'est toujours pas arrivé. Elle a déjà repeint la cuisine."
    assert dating.admit("earliest", "Le vélo n'est toujours pas arrivé", src, A)[1] == \
        "deposit_time"
    assert dating.admit("latest", "Elle a déjà repeint la cuisine", src, A)[1] == "deposit_time"


def test_since_a_date_anchors_the_start():
    src = "I have had the piano since 2 March 2025."
    b, why = dating.admit("exact", "I have had the piano since 2 March 2025", src, B)
    assert why == "excerpt_date" and b["earliest"] == b["latest"] == date(2025, 3, 2)


# --- combination, in code ----------------------------------------------------

def _row(mid, lo=None, hi=None, ex="x", src=1):
    return {"memory_id": mid, "earliest": lo, "latest": hi, "excerpt": ex,
            "source_event_id": src, "basis": "deposit_time"}


def test_two_memories_bracket_the_fact():
    iv = dating.interval([_row(1, lo=date(2025, 3, 3), ex="not yet", src=10),
                          _row(2, hi=date(2025, 3, 11), ex="already", src=11)])
    assert iv["earliest"]["date"] == date(2025, 3, 3) and iv["earliest"]["source_event_id"] == 10
    assert iv["latest"]["date"] == date(2025, 3, 11) and iv["latest"]["excerpt"] == "already"
    assert not iv["exact"] and not iv["conflict"]
    assert dating.phrase(iv, "en") == "between 3 March 2025 and 11 March 2025"
    assert dating.phrase(iv) == "entre le 3 mars 2025 et le 11 mars 2025"


def test_the_tightest_bounds_win():
    iv = dating.interval([_row(1, lo=date(2025, 3, 1)), _row(2, lo=date(2025, 3, 5)),
                          _row(3, hi=date(2025, 3, 20)), _row(4, hi=date(2025, 3, 9))])
    assert (iv["earliest"]["memory_id"], iv["latest"]["memory_id"]) == (2, 4)


def test_exact_only_when_the_bounds_meet():
    d = date(2025, 3, 12)
    iv = dating.interval([_row(1, lo=d, hi=d)])
    assert iv["exact"] and dating.phrase(iv, "en") == "on 12 March 2025"
    one = dating.interval([_row(1, lo=date(2025, 3, 3))])
    assert dating.phrase(one, "en").startswith("not before 3 March 2025")
    assert dating.phrase(one).startswith("pas avant le 3 mars 2025")
    assert dating.interval([]) is None and dating.phrase(None) is None


def test_crossing_bounds_are_a_contradiction_not_an_average():
    iv = dating.interval([_row(1, lo=date(2025, 3, 20)), _row(2, hi=date(2025, 3, 9))])
    assert iv["conflict"] and "conflicting" in dating.phrase(iv, "en")
    assert "contradictoires" in dating.phrase(iv)


def test_describe_cites_both_ends():
    iv = dating.interval([_row(1, lo=date(2025, 3, 3), ex="not yet", src=10),
                          _row(2, hi=date(2025, 3, 11), ex="already", src=11)])
    d = dating.describe(iv, "en")
    assert d["au_plus_tot"] == {"date": "2025-03-03", "extrait": "not yet", "depot": 10,
                                "base": "deposit_time"}
    assert d["au_plus_tard"]["depot"] == 11 and not d["contradiction"]


# --- the night asks, the code admits (no database) ---------------------------

def test_night_fields_are_mended():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))
    import nightly
    night, problem = nightly.validate_night({"memories": [
        {"type": "semantic", "content": "a", "event_key": " Kofi has the kayak ",
         "event_bounds": {"side": "earliest", "excerpt": "not yet"}},
        {"type": "semantic", "content": "b", "bornes": ["junk", {"side": "latest"}]},
        {"type": "semantic", "content": "c", "event_key": 3, "event_bounds": "soon"}]})
    assert problem is None
    a, b, c = night["memories"]
    assert a["event_key"] == "Kofi has the kayak" and a["event_bounds"] == [
        {"side": "earliest", "excerpt": "not yet"}]
    assert b["event_bounds"] == [{"side": "latest"}]
    assert "event_key" not in c and "event_bounds" not in c
    for words in ("`event_key`", "`event_bounds`", "`earliest`", "`latest`"):
        assert words in nightly.PROMPT


class _Conn:
    """Records the writes of write_memories; no database."""

    def __init__(self):
        self.sql, self.next_id = [], 100

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))
        conn = self

        class R:
            def fetchone(self_inner):
                conn.next_id += 1
                return {"id": conn.next_id}
        return R()


def test_write_memories_stores_only_admitted_bounds(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))
    import nightly
    monkeypatch.setattr(nightly.embeddings, "embed", lambda *a, **k: None)
    events = {1: {"id": 1, "occurred_at": A, "payload": {"text": NOT_YET}}}
    conn = _Conn()
    (w,) = nightly.write_memories(conn, [{
        "type": "semantic", "content": "The kayak has not arrived yet.",
        "source_event_ids": [1], "event_key": "the kayak arrived",
        "event_bounds": [{"side": "earliest", "excerpt": "has not arrived yet",
                          "source_event_id": 99},                       # wrong id: found
                         {"side": "exact", "excerpt": "has not arrived yet"},   # refused
                         {"side": "latest", "excerpt": "arrived on 5 March"}]}],  # not quoted
        events=events)
    inserts = [p for q, p in conn.sql if q.startswith("INSERT INTO memory_time_bounds")]
    assert len(inserts) == 1
    assert inserts[0][1:3] == (date(2025, 3, 3), None) and inserts[0][4] == 1
    assert w["bounds_admitted"] == 1
    assert w["bounds_refused"] == {"relation_not_exact": 1, "no_source": 1}
    # the code's key ("kayak"), the same whatever the model wrote that night
    assert ("UPDATE memories SET event_key = %s WHERE id = %s",
            ("kayak", w["id"])) in conn.sql


def test_write_memories_reads_bounds_the_model_did_not_propose(monkeypatch):
    """Measured (37f508d): a 4B model proposed no bound in a whole run. The
    code reads them in the memory's own verified excerpts, and both nights
    pool under the same key and subject."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))
    import nightly
    monkeypatch.setattr(nightly.embeddings, "embed", lambda *a, **k: None)
    events = {1: {"id": 1, "occurred_at": A, "payload": {"text": NOT_YET}},
              2: {"id": 2, "occurred_at": B, "payload": {"text": ALREADY}}}
    conn = _Conn()
    w1, w2 = nightly.write_memories(conn, [
        {"type": "episodic", "content": "The kayak has not arrived yet.", "source_event_ids": [1],
         "evidence": {"citations": ["The kayak I ordered has not arrived yet"]}},
        {"type": "episodic", "content": "Took the kayak out on the lake.", "source_event_ids": [2],
         "evidence": {"citations": ["it is already scratched", "Took the kayak out on the lake"]}},
    ], events=events)
    inserts = [p for q, p in conn.sql if q.startswith("INSERT INTO memory_time_bounds")]
    assert [(i[1], i[2]) for i in inserts] == [(date(2025, 3, 3), None), (None, date(2025, 3, 11))]
    assert w1["bounds_admitted"] == w2["bounds_admitted"] == 1
    keys = [p for q, p in conn.sql if q.startswith("UPDATE memories SET event_key")]
    assert keys == [("kayak", w1["id"]), ("kayak", w2["id"])]
    iv = dating.interval([{"earliest": i[1], "latest": i[2]} for i in inserts])
    assert dating.phrase(iv, "en") == "between 3 March 2025 and 11 March 2025"


def test_propose_reads_relations_and_dates_never_a_bare_sentence():
    assert dating.propose(["has not arrived yet"]) == [
        {"side": "earliest", "excerpt": "has not arrived yet"}]
    assert dating.propose(["Le vélo est déjà là."])[0]["side"] == "latest"
    assert dating.propose(["Got the keys on 12 March 2025"])[0]["side"] == "exact"
    assert dating.propose(["Since 3 March I live in Lyon."])[0]["side"] == "exact"
    assert dating.propose(["Watered the plants on the balcony.", "", None]) == []
    assert dating.object_key("The kayak I ordered has not arrived yet") == "kayak"
    assert dating.object_key("L'ordinateur n'est pas encore arrivé.") == "ordinateur"
    assert dating.object_key("Since 3 March I live in Lyon.") is None


# --- on a real database --------------------------------------------------------

needs_db = pytest.mark.skipif(not os.environ.get("PENSINE_TEST_DB"),
                              reason="PENSINE_TEST_DB not set (integration test)")


@pytest.fixture
def conn(monkeypatch, tmp_path):
    monkeypatch.setattr("pensine.config.DATABASE_URL", os.environ["PENSINE_TEST_DB"])
    monkeypatch.setattr("pensine.config.KEYS_DIR", tmp_path / "keys")
    monkeypatch.setattr("pensine.config.MEDIA_ROOT", tmp_path / "media")
    monkeypatch.setattr("pensine.config.SHRED_ENABLED", False)
    monkeypatch.setattr("pensine.config.TIMEZONE", "UTC")
    from pensine import db
    with db.connection() as c:
        yield c
        c.rollback()


def _night(conn, monkeypatch, when, text, memory):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))
    import nightly
    from pensine import db
    monkeypatch.setattr(nightly.embeddings, "embed", lambda *a, **k: None)
    import uuid
    text = f"{text} [{uuid.uuid4().hex[:8]}]"   # the log deduplicates identical deposits
    eid = db.append_event(conn, source="pensieve", kind="deposit", occurred_at=when,
                          payload={"text": text})
    event = {"id": eid, "occurred_at": when, "payload": {"text": text}}
    (w,) = nightly.write_memories(conn, [{**memory, "source_event_ids": [eid]}],
                                  events={eid: event})
    return eid, w["id"]


@needs_db
def test_bracketed_interval_on_a_database_then_shredded(conn, monkeypatch):
    from pensine import shred
    monkeypatch.setattr("pensine.config.SHRED_ENABLED", True)
    e1, m1 = _night(conn, monkeypatch, A, "TestKayak note: " + NOT_YET, {
        "type": "episodic", "content": "The TestKayak has not arrived yet.",
        "subject": "I", "event_key": "TestKayak arrived",
        "event_bounds": [{"side": "earliest", "excerpt": "has not arrived yet"}]})
    e2, m2 = _night(conn, monkeypatch, B, "TestKayak note: " + ALREADY, {
        "type": "semantic", "content": "The TestKayak is here.", "subject": "I",
        "event_key": "testkayak  ARRIVED",
        "event_bounds": [{"side": "latest", "excerpt": "it is already scratched"}]})
    out = dating.for_memories(conn, [m2])
    iv = out[m2]
    assert (iv["earliest"]["date"], iv["latest"]["date"]) == (date(2025, 3, 3), date(2025, 3, 11))
    assert (iv["earliest"]["source_event_id"], iv["latest"]["source_event_id"]) == (e1, e2)
    assert dating.phrase(iv, "en") == "between 3 March 2025 and 11 March 2025"
    # the "not yet" memory superseded by the "already" one still bounds the fact
    conn.execute("UPDATE memories SET superseded_by = %s WHERE id = %s", (m2, m1))
    assert dating.for_memories(conn, [m1])[m1]["earliest"]["date"] == date(2025, 3, 3)
    # forgetting the "not yet" deposit takes its bound (and its quote) with it
    counts = shred.forget(conn, event_id=e1, commit=False)
    assert counts["bornes"] == 1
    left = dating.for_memories(conn, [m2])[m2]
    assert left["earliest"] is None and left["latest"]["date"] == date(2025, 3, 11)
    assert "scratched" not in json.dumps(conn.execute(
        "SELECT detail FROM audit_log WHERE actor = 'shred' ORDER BY id DESC LIMIT 1"
    ).fetchone()["detail"])


@needs_db
def test_recall_states_the_interval_with_both_sources(conn, monkeypatch):
    from pensine import mcp_server
    e1, _ = _night(conn, monkeypatch, A, "TestPiano: the piano has not been delivered yet.", {
        "type": "episodic", "content": "The TestPiano has not been delivered yet.",
        "subject": "I", "event_key": "TestPiano delivered",
        "event_bounds": [{"side": "earliest", "excerpt": "has not been delivered yet"}]})
    e2, _ = _night(conn, monkeypatch, B, "TestPiano: the piano is already in the hall.", {
        "type": "semantic", "content": "The TestPiano was delivered.", "subject": "I",
        "event_key": "TestPiano delivered",
        "event_bounds": [{"side": "latest", "excerpt": "the piano is already in the hall"}]})
    conn.commit()
    try:
        monkeypatch.setattr(mcp_server.embeddings, "embed", lambda *a, **k: None)
        out = json.loads(mcp_server.recall("When was the TestPiano delivered?"))
        timed = [m["date_evenement"] for m in out["memories"] if "date_evenement" in m]
        assert timed and all(t["phrase"] == "between 3 March 2025 and 11 March 2025"
                             for t in timed)
        assert {timed[0]["au_plus_tot"]["depot"], timed[0]["au_plus_tard"]["depot"]} == {e1, e2}
        assert "dates_bornees" in out
    finally:
        conn.execute("DELETE FROM memory_time_bounds WHERE source_event_id = ANY(%s)",
                     ([e1, e2],))
        conn.execute("DELETE FROM memory_links WHERE source_id IN (SELECT id FROM memories "
                     "WHERE source_event_ids && %s::bigint[]) OR target_id IN (SELECT id "
                     "FROM memories WHERE source_event_ids && %s::bigint[])", ([e1, e2],) * 2)
        conn.execute("DELETE FROM memories WHERE source_event_ids && %s::bigint[]", ([e1, e2],))
        conn.commit()


@needs_db
def test_a_later_affirmation_closes_an_earlier_not_yet(conn, monkeypatch):
    """Measured on dev2 (Sonnet 5.5, 253de05): "Jonah is still without the
    rowing machine", then "Jonah's rowing machine has been in use for a
    while" with no "already". The second deposit bounds the fact from above."""
    tag = "Testrower"
    _, m1 = _night(conn, monkeypatch, A, f"{tag} Jonah is still without the {tag.lower()} machine.", {
        "type": "episodic", "content": f"Jonah is still without the {tag.lower()} machine.",
        "subject": "I",
        "evidence": {"citations": [f"Jonah is still without the {tag.lower()} machine"]}})
    e2, m2 = _night(conn, monkeypatch, B, f"{tag} Jonah's {tag.lower()} machine has been in use.", {
        "type": "semantic", "content": f"Jonah's {tag.lower()} machine has been in use.",
        "subject": "I",
        "evidence": {"citations": [f"Jonah's {tag.lower()} machine has been in use"]}})
    iv = dating.for_memories(conn, [m2])[m2]
    assert (iv["earliest"]["date"], iv["latest"]["date"]) == (date(2025, 3, 3), date(2025, 3, 11))
    assert iv["latest"]["source_event_id"] == e2


def test_an_arrival_denied_is_a_not_yet_and_a_possessive_names_the_thing():
    assert dating.relation("The standing desk I ordered? Not delivered.") == "after"
    assert dating.relation("Le colis n'est pas livré.") == "after"
    assert dating.object_key("Jonah's rowing machine has been in use for a while.") == "rowing"
    assert dating.relation("I am not here today.") is None
