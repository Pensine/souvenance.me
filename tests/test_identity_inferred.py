"""Inferred identity claims: coverage from converging evidence, kept apart from proof."""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pensine import identity

WHEN = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)


# --- in code, no database ----------------------------------------------------

def test_generic_values_support_nothing():
    assert identity.generic("from home") and identity.generic("the office")
    assert identity.generic("a") and not identity.generic("Saltire Glassworks")
    assert not identity.generic("Porto")


def test_together_tells_two_people_from_one():
    a, n = ["my", "aunt"], [["ines"]]
    assert identity.together("Lunch with my aunt and Ines today.", a, n) == "together"
    assert identity.together("Lunch with my aunt Ines today.", a, n) == "linked"
    assert identity.together("Lunch with my aunt today.", a, n) is None


@pytest.mark.parametrize("text, pronoun, expected", [
    ("Saw Ines at the market. She looked tired.", "she", "Ines Varga"),
    ("Saw Ines and Kofi at the market. She looked tired.", "she", None),   # two candidates
    ("She looked tired. Saw Ines later.", "she", None),                   # nobody before it
    ("Saw Ines at the market.", "she", None),                             # no pronoun here
    ("J'ai croisé Ines au marché. Elle avait l'air fatiguée.", "elle", "Ines Varga"),
    ("Saw Ines at the market. She looked tired.", "Priya", None),         # not a pronoun
])
def test_pronouns_resolve_within_one_deposit_only(text, pronoun, expected):
    assert identity.pronoun_referent(pronoun, text, ["Ines Varga", "Kofi Mensah"]) == expected


# --- on a real database --------------------------------------------------------

needs_db = pytest.mark.skipif(not os.environ.get("PENSINE_TEST_DB"),
                              reason="PENSINE_TEST_DB not set (integration test)")


@pytest.fixture
def conn(monkeypatch, tmp_path):
    monkeypatch.setattr("pensine.config.DATABASE_URL", os.environ["PENSINE_TEST_DB"])
    monkeypatch.setattr("pensine.config.KEYS_DIR", tmp_path / "keys")
    monkeypatch.setattr("pensine.config.MEDIA_ROOT", tmp_path / "media")
    monkeypatch.setattr("pensine.config.SHRED_ENABLED", False)
    from pensine import db
    with db.connection() as c:
        yield c
        c.rollback()


@pytest.fixture
def names():
    """Fresh names per test: the log deduplicates, and earlier runs stay in it."""
    tag = uuid.uuid4().hex[:6]
    return {"name": f"Inesx{tag}", "city": f"Porvik{tag}", "emp": f"Saltire{tag} Glassworks"}


def _dep(conn, text, days=0):
    from pensine import db
    return db.append_event(conn, source="pensieve", kind="deposit",
                           occurred_at=WHEN + timedelta(days=days), payload={"text": text})


def _converging(conn, n, alias="my aunt", extra_alias_city=None):
    """Four deposits: the alias and the name each tied to the city and the
    employer, never written together."""
    a1 = _dep(conn, f"Long day. {alias.capitalize()} lives in {extra_alias_city or n['city']} now.")
    a2 = _dep(conn, f"{alias.capitalize()} works at {n['emp']}.", 1)
    n1 = _dep(conn, f"{n['name']} lives in {n['city']}, near the harbour.", 2)
    n2 = _dep(conn, f"Ran into {n['name']}, who works at {n['emp']}.", 3)
    sup = [{"attribute": n["city"], "alias_excerpt": f"lives in {n['city']} now",
            "alias_event_id": a1, "name_excerpt": f"{n['name']} lives in {n['city']}",
            "name_event_id": n1},
           {"attribute": n["emp"], "alias_excerpt": f"{alias} works at {n['emp']}",
            "alias_event_id": a2, "name_excerpt": f"{n['name']}, who works at {n['emp']}",
            "name_event_id": n2}]
    sup[0]["alias_excerpt"] = f"{alias} lives in {n['city']} now"
    return sup, (a1, a2, n1, n2)


@needs_db
def test_converging_supports_make_a_hedged_hypothesis_never_used(conn, names):
    from pensine import graph
    sup, deps = _converging(conn, names)
    ent = graph.upsert_entity(conn, names["name"], "person")
    out = identity.infer(conn, entity_id=ent, alias="my aunt", supports=sup,
                         role_of_owner="aunt")
    assert out["status"] == "active" and out["tier"] == "inferred"
    assert out["admission"] == "converging:2" and out["confidence"] == 0.6
    assert [s["attribute"] for s in out["supports"]] == [names["city"], names["emp"]]
    # not used: "my aunt" still lands on nobody / a separate entity
    assert identity.resolve(conn, "my aunt", "person") is None or \
        identity.resolve(conn, "my aunt", "person")[0] != ent
    assert graph.resolve_subject(conn, "my aunt")[0] != ent
    (h,) = [x for x in identity.hypotheses_for(conn, "Where does my aunt work?", "en")
            if x["id"] == out["id"]]
    assert h["phrase"].startswith(f"“my aunt” is probably the same person as {names['name']}")
    assert "Inferred, not proven" in h["phrase"] and names["emp"] in h["phrase"]
    fr = identity.hypotheses_for(conn, f"Où travaille {names['name']} ?")
    assert any("probablement la même personne" in x["phrase"] for x in fr)


@needs_db
def test_one_attribute_or_a_generic_one_is_not_enough(conn, names):
    from pensine import graph
    sup, _ = _converging(conn, names)
    ent = graph.upsert_entity(conn, names["name"], "person")
    one = identity.infer(conn, entity_id=ent, alias="my aunt", supports=sup[:1])
    assert one["status"] == "pending" and one["admission"] == "insufficient_supports"
    h1 = _dep(conn, "My uncle works from home most days.")
    h2 = _dep(conn, f"{names['name']} works from home most days.", 1)
    generic = {"attribute": "from home", "alias_excerpt": "My uncle works from home",
               "alias_event_id": h1, "name_excerpt": f"{names['name']} works from home",
               "name_event_id": h2}
    two = identity.infer(conn, entity_id=ent, alias="my uncle",
                         supports=[{**sup[0], "alias_excerpt": sup[0]["alias_excerpt"]},
                                   generic])
    assert two["status"] == "pending" and two["refused"].get("generic_attribute") == 1
    # a made-up excerpt or the same value twice adds nothing
    fake = {**sup[1], "name_excerpt": f"{names['name']} runs {names['emp']}"}
    three = identity.infer(conn, entity_id=ent, alias="my godfather",
                           supports=[sup[0], sup[0], fake])
    assert three["status"] == "pending"


@needs_db
def test_together_in_one_deposit_refutes(conn, names):
    from pensine import graph
    sup, _ = _converging(conn, names, alias="my flatmate")
    _dep(conn, f"Lunch with my flatmate and {names['name']} today.", 4)
    ent = graph.upsert_entity(conn, names["name"], "person")
    out = identity.infer(conn, entity_id=ent, alias="my flatmate", supports=sup)
    assert out["status"] == "refuted"
    reason = conn.execute("SELECT retract_reason FROM entity_aliases WHERE id = %s",
                          (out["id"],)).fetchone()["retract_reason"]
    assert reason.startswith("present together in deposit")


@needs_db
def test_two_places_at_the_same_time_refutes(conn, names):
    from pensine import graph
    sup, (a1, _, n1, _) = _converging(conn, names, extra_alias_city="Lyonne")
    ent = graph.upsert_entity(conn, names["name"], "person")
    against = [{"alias_value": "Lyonne", "name_value": names["city"],
                "alias_excerpt": "My aunt lives in Lyonne now", "alias_event_id": a1,
                "name_excerpt": f"{names['name']} lives in {names['city']}",
                "name_event_id": n1}]
    out = identity.infer(conn, entity_id=ent, alias="my aunt", supports=sup[1:],
                         against=against)
    assert out["status"] == "refuted"


@needs_db
def test_a_later_identity_form_promotes_and_a_co_mention_refutes(conn, names):
    from pensine import graph
    sup, _ = _converging(conn, names)
    ent = graph.upsert_entity(conn, names["name"], "person")
    h = identity.infer(conn, entity_id=ent, alias="my aunt", supports=sup)
    text = f"Dinner with my aunt {names['name']} tonight."
    eid = _dep(conn, text, 5)
    out = identity.check_deposits(conn, [{"id": eid, "payload": {"text": text}}])
    assert out["hypotheses_promoted"] == 1
    row = conn.execute("SELECT status, promoted_to FROM entity_aliases WHERE id = %s",
                       (h["id"],)).fetchone()
    assert row["status"] == "promoted" and row["promoted_to"]
    assert identity.resolve(conn, "my aunt", "person") == (ent, row["promoted_to"])
    # another hypothesis, refuted by a later co-mention
    other = {**names, "name": names["name"] + "c"}
    sup2, _ = _converging(conn, other, alias="my cousin")
    ent2 = graph.upsert_entity(conn, other["name"], "person")
    h2 = identity.infer(conn, entity_id=ent2, alias="my cousin", supports=sup2)
    assert h2["status"] == "active"
    text = f"Lunch with my cousin and {other['name']} today."
    eid = _dep(conn, text, 6)
    assert identity.check_deposits(conn, [{"id": eid, "payload": {"text": text}}]) == \
        {"hypotheses_promoted": 0, "hypotheses_refuted": 1}
    assert conn.execute("SELECT status FROM entity_aliases WHERE id = %s",
                        (h2["id"],)).fetchone()["status"] == "refuted"


@needs_db
def test_owner_confirmation_promotes_and_refusal_refutes(conn, names, monkeypatch):
    from pensine import graph, proposals
    monkeypatch.setattr(proposals, "MIN_SECONDS_BEFORE_CONFIRM", -1)
    sup, _ = _converging(conn, names)
    ent = graph.upsert_entity(conn, names["name"], "person")
    h = identity.infer(conn, entity_id=ent, alias="my aunt", supports=sup)
    pid = conn.execute("SELECT proposal_id FROM entity_aliases WHERE id = %s",
                       (h["id"],)).fetchone()["proposal_id"]
    assert pid
    out = proposals.confirm(conn, pid)
    assert out["identity_claim"]
    assert identity.resolve(conn, "my aunt", "person") == (ent, out["identity_claim"])
    sup2, _ = _converging(conn, {**names, "name": names["name"] + "b"}, alias="my uncle")
    ent2 = graph.upsert_entity(conn, names["name"] + "b", "person")
    h2 = identity.infer(conn, entity_id=ent2, alias="my uncle", supports=sup2)
    pid2 = conn.execute("SELECT proposal_id FROM entity_aliases WHERE id = %s",
                        (h2["id"],)).fetchone()["proposal_id"]
    proposals.decline(conn, pid2, "no")
    assert conn.execute("SELECT status FROM entity_aliases WHERE id = %s",
                        (h2["id"],)).fetchone()["status"] == "refuted"


@needs_db
def test_forgetting_a_support_takes_the_hypothesis(conn, names, monkeypatch):
    from pensine import db, graph, shred
    monkeypatch.setattr("pensine.config.SHRED_ENABLED", True)
    sup, (a1, *_) = _converging(conn, names)
    ent = graph.upsert_entity(conn, names["name"], "person")
    h = identity.infer(conn, entity_id=ent, alias="my aunt", supports=sup)
    pid = conn.execute("SELECT proposal_id FROM entity_aliases WHERE id = %s",
                       (h["id"],)).fetchone()["proposal_id"]
    counts = shred.forget(conn, event_id=a1, commit=False)
    assert counts["alias"] >= 1
    assert not conn.execute("SELECT 1 FROM entity_aliases WHERE id = %s", (h["id"],)).fetchone()
    assert not conn.execute("SELECT 1 FROM memory_proposals WHERE id = %s", (pid,)).fetchone()
    _ = db


@needs_db
def test_pronoun_subject_resolves_within_its_deposit(conn, names, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))
    import nightly
    from pensine import graph
    monkeypatch.setattr(nightly.embeddings, "embed", lambda *a, **k: None)
    ent = graph.upsert_entity(conn, names["name"], "person")
    text = f"Saw {names['name']} at the market. She got the job at {names['emp']}."
    eid = _dep(conn, text)
    other = _dep(conn, f"She got the job at {names['emp']}.", 1)
    w = nightly.write_memories(conn, [
        {"type": "semantic", "content": "She got the job.", "subject": "she",
         "source_event_ids": [eid]},
        {"type": "semantic", "content": "She got the job.", "subject": "she",
         "source_event_ids": [other]}],
        events={eid: {"id": eid, "payload": {"text": text}},
                other: {"id": other, "payload": {"text": f"She got the job at {names['emp']}."}}})
    subj = {r["id"]: r["subject_entity_id"] for r in conn.execute(
        "SELECT id, subject_entity_id FROM memories WHERE id = ANY(%s)",
        ([x["id"] for x in w],)).fetchall()}
    assert subj[w[0]["id"]] == ent and subj[w[1]["id"]] is None
    _ = json
