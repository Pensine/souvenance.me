"""Identity claims: an alias is believed only on a quoted proof, and can be withdrawn."""

import json
import os
from datetime import datetime, timezone

import pytest

from pensine import identity

WHEN = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)
SRC = ("Lunch with my sister Priya near the station. Kofi from the lab joined later. "
       "Priya, ma sœur, was in a good mood.")


# --- admission, in code ------------------------------------------------------

def test_alias_et_nom_cote_a_cote_admis():
    assert identity.admit("my sister", "Priya", "my sister Priya", SRC) == (True, "excerpt")
    assert identity.admit("ma soeur", "Priya", "Priya, ma sœur", SRC) == (True, "excerpt")
    # the given name is enough for a full canonical name
    assert identity.admit("my sister", "Priya Raman", "Lunch with my sister Priya", SRC)[0]


def test_extrait_absent_du_depot_refuse():
    assert identity.admit("my sister", "Priya", "my sister Priya Raman", SRC) == \
        (False, "excerpt_not_found")
    assert identity.admit("my sister", "Priya", "my sister Priya", "") == \
        (False, "excerpt_not_found")


def test_extrait_qui_ne_nomme_pas_les_deux_refuse():
    assert identity.admit("my colleague", "Kofi", "Kofi from the lab joined later", SRC) == \
        (False, "alias_not_in_excerpt")
    assert identity.admit("my sister", "Kofi", "Lunch with my sister Priya", SRC) == \
        (False, "name_not_in_excerpt")


def test_coocurrence_lointaine_refusee():
    """Both words in the excerpt is not enough: "my sister" and "Kofi" five words
    apart are two people, not one designation."""
    ok, why = identity.admit("my sister", "Kofi",
                             "my sister Priya near the station. Kofi", SRC)
    assert not ok and why == "not_adjacent"


# Every form below appears in SRC2; each pair is (alias, name, excerpt).
SRC2 = ("Long call with Priya, my sister, this evening. My sister, Priya, called back. "
        "Lunch with Priya (my sister) at noon. Priya is my sister, after all. "
        "Picked up my colleague from the book group Kofi from the station. "
        "My sister named Priya the cat. Told Oskar that my sister works at Marrowgate Press. "
        "Lunch with my sister and Priya. Priya, my sister and Kofi left early. "
        "My sister's friend Priya waved. Oskar met my sister. Later Priya came.")


@pytest.mark.parametrize("alias, name, excerpt", [
    ("my sister", "Priya", "Long call with Priya, my sister, this evening"),   # X, my sister
    ("my sister", "Priya", "My sister, Priya, called back"),                   # my sister, X
    ("my sister", "Priya Raman", "Lunch with Priya (my sister) at noon"),      # X (my sister)
    ("my sister", "Priya", "Priya is my sister, after all"),                   # copula
    ("my colleague from the book group", "Kofi",
     "Picked up my colleague from the book group Kofi from the station"),     # my sister X
])
def test_identity_forms_in_one_clause_are_admitted(alias, name, excerpt):
    assert identity.admit(alias, name, excerpt, SRC2) == (True, "excerpt")


@pytest.mark.parametrize("alias, name, excerpt, why", [
    # two names in one sentence, no identity link between them
    ("my sister", "Oskar", "Told Oskar that my sister works at Marrowgate Press", "not_linked"),
    ("my sister", "Priya", "Lunch with my sister and Priya", "not_linked"),     # two people
    ("my sister", "Priya", "Priya, my sister and Kofi left early", "not_linked"),  # a list
    ("my sister", "Oskar", "Oskar met my sister", "not_linked"),
    ("my sister", "Priya", "My sister's friend Priya waved", "alias_not_in_excerpt"),
    ("my sister", "Priya", "My sister named Priya the cat", "not_linked"),     # a verb
    ("my sister", "Priya", "Oskar met my sister. Later Priya came", "not_adjacent"),
])
def test_names_sharing_a_sentence_are_not_an_identity(alias, name, excerpt, why):
    assert identity.admit(alias, name, excerpt, SRC2) == (False, why)


def test_clause_tokens_keep_the_structure():
    assert identity._clause_tokens("Priya, ma sœur (enfin!) — Kofi") == \
        ["priya", ",", "ma", "soeur", "(", "enfin", "!", ")", "—", "kofi"]


def test_metadonnees_lient_l_expediteur():
    """A mail whose sender is Priya, signed "Pri": the metadata is one side."""
    src = "See you Sunday! Pri"
    assert identity.admit("Pri", "Priya Raman", "See you Sunday! Pri", src,
                          metadata=["Priya Raman"]) == (True, "metadata")
    assert identity.admit("Pri", "Priya Raman", "See you Sunday! Pri", src,
                          metadata=["Ada Moreau"]) == (False, "name_not_in_excerpt")


def test_alias_identique_au_nom_inutile():
    assert identity.admit("Priya", "Priya", "my sister Priya", SRC) == (False, "same_as_name")


def test_noms_de_metadonnees():
    assert identity.metadata_names({"sender": "Priya", "author": {"name": "Ada"}, "x": "y"}) \
        == ["Priya", "Ada"]
    assert identity.metadata_names(json.dumps({"from": "Kofi"})) == ["Kofi"]
    assert identity.metadata_names("not json") == []


# --- on a real database ------------------------------------------------------

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


def _deposit(conn, text, **meta):
    from pensine import db
    return db.append_event(conn, source="pensieve", kind="deposit", occurred_at=WHEN,
                           payload={"text": text, **meta})


@needs_db
def test_revendication_admise_puis_resolution(conn):
    from pensine import graph
    eid = _deposit(conn, "Dinner with my sister TestPriya, she starts at Birchwood Labs.")
    priya = graph.upsert_entity(conn, "TestPriya", "person")
    out = identity.propose(conn, entity_id=priya, alias="my sister", alias_kind="role",
                           role_of_owner="sister", excerpt="my sister TestPriya",
                           source_event_id=eid, confidence=0.9)
    assert out["status"] == "active" and out["admission"] == "excerpt"
    # case, accents, punctuation do not matter
    assert identity.resolve(conn, "My Sister", "person") == (priya, out["id"])
    assert graph.upsert_entity(conn, "my sister", "person") == priya
    assert identity.resolve(conn, "testpriya", "person") == (priya, None)
    # a name differing only by accents is the same entity
    zoe = graph.upsert_entity(conn, "TestZoé", "person")
    assert graph.upsert_entity(conn, "testzoe", "person") == zoe
    # the same claim twice is one row
    again = identity.propose(conn, entity_id=priya, alias="My sister",
                             excerpt="my sister TestPriya", source_event_id=eid)
    assert again["id"] == out["id"]


@needs_db
def test_revendication_non_prouvee_reste_en_attente(conn):
    from pensine import graph
    eid = _deposit(conn, "My sister called. TestPriya sent photos later that week.")
    priya = graph.upsert_entity(conn, "TestPriya", "person")
    out = identity.propose(conn, entity_id=priya, alias="my sister",
                           excerpt="My sister called", source_event_id=eid)
    assert out["status"] == "pending" and out["admission"] == "name_not_in_excerpt"
    assert identity.resolve(conn, "my sister", "person") is None   # not applied
    assert graph.upsert_entity(conn, "my sister", "person") != priya
    assert [c["status"] for c in identity.claims(conn, priya)] == ["pending"]


@needs_db
def test_alias_ambigu_ne_resout_rien(conn):
    from pensine import graph
    eid = _deposit(conn, "my colleague TestKofi and my colleague TestAda came by.")
    kofi = graph.upsert_entity(conn, "TestKofi", "person")
    ada = graph.upsert_entity(conn, "TestAda", "person")
    for who, name in ((kofi, "TestKofi"), (ada, "TestAda")):
        assert identity.propose(conn, entity_id=who, alias="my colleague",
                                excerpt=f"my colleague {name}",
                                source_event_id=eid)["status"] == "active"
    assert identity.resolve(conn, "my colleague", "person") is None
    assert identity.resolve_alias(conn, "my colleague") == sorted([kofi, ada])


@needs_db
def test_ingest_fusionne_puis_retrait_scinde(conn):
    """The night's claim lands "my sister" on Priya; retracting it splits the
    next mentions off and reports the edge it carried, which stays as it was."""
    from pensine import graph
    text = "Dinner with my sister TestPriya. My sister just started at TestBirchwood."
    eid = _deposit(conn, text)
    events = [{"id": eid, "payload": {"text": text}}]
    out = graph.ingest(
        conn, [{"name": "TestPriya", "kind": "person"}],
        [{"subject": "my sister", "predicate": "works at", "object": "TestBirchwood",
          "object_kind": "organization"}],
        [eid], events=events,
        aliases=[{"name": "TestPriya", "alias": "my sister", "role_of_owner": "sister",
                  "excerpt": "my sister TestPriya", "confidence": 0.9}])
    assert out["aliases_admitted"] == 1 and out["relations_added"] == 1
    priya = out["entity_ids"]["testpriya"]
    assert out["entity_ids"]["my sister"] == priya
    hist = graph.entity_history(conn, "my sister")
    assert [(h["subject"], h["object"]) for h in hist] == [("TestPriya", "TestBirchwood")]
    (claim,) = [c for c in identity.claims(conn, priya) if c["status"] == "active"]
    assert hist[0]["via_alias_ids"] == [claim["id"]]
    assert claim["alias_kind"] == "role" and claim["excerpt"] == "my sister TestPriya"

    with pytest.raises(ValueError):
        identity.retract(conn, claim["id"], "")              # a reason is required
    ret = identity.retract(conn, claim["id"], "two different people")
    assert [(r["subject"], r["predicate"], r["object"]) for r in ret["relations"]] == \
        [("TestPriya", "works at", "TestBirchwood")]
    # history is not rewritten: the edge is still on Priya
    assert conn.execute("SELECT count(*) AS n FROM relations WHERE subject_id = %s",
                        (priya,)).fetchone()["n"] == 1
    # later mentions split off
    assert identity.resolve(conn, "my sister", "person") is None
    assert graph.upsert_entity(conn, "my sister", "person") != priya
    with pytest.raises(ValueError):
        identity.retract(conn, claim["id"], "again")         # terminal


@needs_db
def test_une_revendication_ne_se_reecrit_pas(conn):
    import psycopg
    from pensine import graph
    eid = _deposit(conn, "Coffee with my brother TestOdin.")
    odin = graph.upsert_entity(conn, "TestOdin", "person")
    cid = identity.propose(conn, entity_id=odin, alias="my brother",
                           excerpt="my brother TestOdin", source_event_id=eid)["id"]
    with pytest.raises(psycopg.errors.RaiseException):
        with conn.transaction():
            conn.execute("UPDATE entity_aliases SET excerpt = 'x' WHERE id = %s", (cid,))
    identity.retract(conn, cid, "wrong")
    with pytest.raises(psycopg.errors.RaiseException):
        with conn.transaction():
            conn.execute("UPDATE entity_aliases SET status = 'active' WHERE id = %s", (cid,))


@needs_db
def test_oubli_emporte_la_revendication(conn, monkeypatch):
    """Shredding the deposit that proves a claim deletes the claim (its excerpt
    quotes the deposit), drops the pointer from edges other deposits made
    through it, and the alias no longer resolves."""
    from pensine import graph, shred
    monkeypatch.setattr("pensine.config.SHRED_ENABLED", True)
    proof = _deposit(conn, "Walk with my sister TestPriya by the river.")
    later = _deposit(conn, "My sister moved to TestHarbourtown.")
    priya = graph.upsert_entity(conn, "TestPriya", "person")
    cid = identity.propose(conn, entity_id=priya, alias="my sister",
                           excerpt="my sister TestPriya", source_event_id=proof)["id"]
    out = graph.ingest(conn, [], [{"subject": "my sister", "predicate": "lives in",
                                   "object": "TestHarbourtown"}], [later])
    assert out["entity_ids"]["my sister"] == priya
    counts = shred.forget(conn, event_id=proof, commit=False)
    assert counts["alias"] == 1
    assert conn.execute("SELECT count(*) AS n FROM entity_aliases WHERE id = %s",
                        (cid,)).fetchone()["n"] == 0
    edge = conn.execute("SELECT via_alias_ids FROM relations WHERE subject_id = %s",
                        (priya,)).fetchone()
    assert edge["via_alias_ids"] == []          # the fact from `later` stays
    assert identity.resolve(conn, "my sister", "person") is None
    assert "TestPriya" not in json.dumps(conn.execute(
        "SELECT detail FROM audit_log WHERE actor = 'shred' ORDER BY id DESC LIMIT 1"
    ).fetchone()["detail"])


@needs_db
def test_memory_subject_resolved_through_the_claim_and_reported(conn, monkeypatch):
    """Consolidation names the subject as written ("my sister"); the code lands
    it on Priya through the admitted claim, keeps the claim used, and a
    retraction reports the memory without moving it."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))
    import nightly
    from pensine import graph
    monkeypatch.setattr(nightly.embeddings, "embed", lambda *a, **k: None)
    monkeypatch.setattr("pensine.config.OWNER_NAME", "TestMaya Collins")
    text = "Dinner with my sister TestPriya. My sister works at TestMarrowgate Press."
    eid = _deposit(conn, text)
    g = graph.ingest(conn, [], [], [eid], events=[{"id": eid, "payload": {"text": text}}],
                     aliases=[{"name": "TestPriya", "alias": "my sister",
                               "role_of_owner": "sister", "excerpt": "my sister TestPriya"}])
    assert g["aliases_admitted"] == 1
    written = nightly.write_memories(conn, [
        {"type": "semantic", "content": "My sister works at TestMarrowgate Press.",
         "source_event_ids": [eid], "subject": "my sister"},
        {"type": "semantic", "content": "Dinner tonight.", "source_event_ids": [eid],
         "subject": "I"}])
    rows = {r["id"]: r for r in conn.execute(
        "SELECT m.id, m.subject_alias_id, e.name FROM memories m "
        "JOIN entities e ON e.id = m.subject_entity_id WHERE m.id = ANY(%s)",
        ([w["id"] for w in written],)).fetchall()}
    sister, me = (rows[w["id"]] for w in written)
    assert sister["name"] == "TestPriya" and sister["subject_alias_id"]
    assert me["name"] == "TestMaya Collins" and me["subject_alias_id"] is None
    ret = identity.retract(conn, sister["subject_alias_id"], "not the same person")
    assert [m["id"] for m in ret["memories"]] == [written[0]["id"]]
    still = conn.execute("SELECT subject_entity_id FROM memories WHERE id = %s",
                         (written[0]["id"],)).fetchone()
    assert still["subject_entity_id"] is not None          # reported, not rewritten


@needs_db
def test_ambiguous_subject_resolves_to_nobody(conn):
    from pensine import graph
    eid = _deposit(conn, "my colleague TestKofi and my colleague TestAda came by.")
    for name in ("TestKofi", "TestAda"):
        identity.propose(conn, entity_id=graph.upsert_entity(conn, name, "person"),
                         alias="my colleague", excerpt=f"my colleague {name}",
                         source_event_id=eid)
    assert graph.resolve_subject(conn, "my colleague") is None
    assert graph.resolve_subject(conn, "TestKofi")[0] == graph.upsert_entity(
        conn, "TestKofi", "person")


@needs_db
def test_forgetting_the_proof_keeps_the_subject_drops_the_pointer(conn, monkeypatch):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))
    import nightly
    from pensine import graph, shred
    monkeypatch.setattr("pensine.config.SHRED_ENABLED", True)
    monkeypatch.setattr(nightly.embeddings, "embed", lambda *a, **k: None)
    proof = _deposit(conn, "Walk with my sister TestPriya by the river.")
    later = _deposit(conn, "My sister moved to TestHarbourtown.")
    priya = graph.upsert_entity(conn, "TestPriya", "person")
    cid = identity.propose(conn, entity_id=priya, alias="my sister",
                           excerpt="my sister TestPriya", source_event_id=proof)["id"]
    (w,) = nightly.write_memories(conn, [{"type": "semantic", "source_event_ids": [later],
                                          "content": "My sister moved to TestHarbourtown.",
                                          "subject": "my sister"}])
    assert conn.execute("SELECT subject_alias_id FROM memories WHERE id = %s",
                        (w["id"],)).fetchone()["subject_alias_id"] == cid
    shred.forget(conn, event_id=proof, commit=False)
    row = conn.execute("SELECT subject_entity_id, subject_alias_id FROM memories "
                       "WHERE id = %s", (w["id"],)).fetchone()
    assert row == {"subject_entity_id": priya, "subject_alias_id": None}


def test_the_owner_s_possessive_is_the_owner_s_voice():
    assert identity.owner_voice("Which choir did Ivo's brother join?", "Ivo Okafor") == \
        "Which choir did my brother join?"
    assert identity.owner_voice("Where does Ivo’s aunt live?", "Ivo") == "Where does my aunt live?"
    assert identity.owner_voice("Where does Ivor's aunt live?", "Ivo") == "Where does Ivor's aunt live?"
    assert identity.owner_voice("Where does Dina's aunt live?", "") == "Where does Dina's aunt live?"


@needs_db
def test_a_question_by_role_finds_the_proven_name(conn):
    """Measured on dev2 (Sonnet 5.5): "Which choir did Ivo's brother join?"
    went unanswered while "my brother Dev" was proven: the memories say Dev."""
    from pensine import graph
    eid = _deposit(conn, "Dinner with my stepbrother TestDev tonight.")
    dev = graph.upsert_entity(conn, "TestDev", "person")
    identity.propose(conn, entity_id=dev, alias="my stepbrother", excerpt="my stepbrother TestDev",
                     source_event_id=eid)
    assert identity.proven_in(conn, "Which choir did TestIvo's stepbrother join?", "TestIvo") == [
        {"alias": "my stepbrother", "name": "TestDev", "entity_id": dev, "by": "alias"}]
    assert identity.proven_in(conn, "Which choir did TestIvo's cousin join?", "TestIvo") == []


# --- measured on dev3 (Sonnet 5.5, dd6b970): qualified roles ----------------

@needs_db
def test_a_qualified_role_is_not_the_bare_one(conn):
    """"my sister = Vera" proven; the model writes "my sister" for a fact
    about "my sister from the summer course": it must not land on Vera."""
    from pensine import graph
    eid = _deposit(conn, "Met my sister TestVera at the library.")
    vera = graph.upsert_entity(conn, "TestVera", "person")
    identity.propose(conn, entity_id=vera, alias="my sister", excerpt="my sister TestVera",
                     source_event_id=eid)
    content = "TestAnton's sister from the summer course works at Thistledown."
    assert identity.designation(conn, "my sister", content, "TestAnton") is None
    assert identity.designation(conn, "my sister", "My sister works at Nova.", "TestAnton") == \
        "my sister"
    # once "my sister from the summer course" is proven, it is that person
    eid2 = _deposit(conn, "Long call with TestMaya, my sister from the summer course.")
    maya = graph.upsert_entity(conn, "TestMaya", "person")
    identity.propose(conn, entity_id=maya, alias="my sister from the summer course",
                     excerpt="TestMaya, my sister from the summer course", source_event_id=eid2)
    assert identity.designation(conn, "my sister", content, "TestAnton") == \
        "my sister from the summer course"
    assert identity.designation(conn, "ma sœur", "Ma sœur d'Annecy vit à Lyon.", "") is None


@needs_db
def test_a_question_by_name_finds_the_proven_role(conn):
    """"Which company does Gideon work for?" while the memory says only
    "my sister from the old flat works at …"."""
    from pensine import graph
    eid = _deposit(conn, "Long call with TestGideon, my sister from the old flat.")
    gid = graph.upsert_entity(conn, "TestGideon", "person")
    identity.propose(conn, entity_id=gid, alias="my sister from the old flat",
                     excerpt="TestGideon, my sister from the old flat", source_event_id=eid)
    eid2 = _deposit(conn, "Met my sister TestVera at the library.")
    vera = graph.upsert_entity(conn, "TestVera", "person")
    identity.propose(conn, entity_id=vera, alias="my sister", excerpt="my sister TestVera",
                     source_event_id=eid2)
    assert identity.proven_in(conn, "Which company does TestGideon work for now?", "TestAnton") == [
        {"alias": "my sister from the old flat", "name": "TestGideon", "entity_id": gid,
         "by": "name"}]
    # the longer alias the question writes hides the bare one inside it
    got = identity.proven_in(conn, "Which choir did TestAnton's sister from the old flat join?",
                             "TestAnton")
    assert [g["entity_id"] for g in got] == [gid] and got[0]["by"] == "alias"
    assert identity.named_entities(conn, "Where does TestGideon live?", "TestAnton") == {gid}


@needs_db
def test_the_graph_brings_back_what_a_named_person_is_known_for(conn):
    from pensine import db, graph
    gid = graph.upsert_entity(conn, "TestGreta", "person")
    row = conn.execute("INSERT INTO memories (type, content, source_event_ids, subject_entity_id, confidence, importance, valid_from) "
                       "VALUES ('semantic', 'TestGreta joined the Beacon Hill Choir.', '{}', %s, 0.5, 0.5, now()) "
                       "RETURNING id", (gid,)).fetchone()
    assert [r["id"] for r in db.subject_memories(conn, gid, None)] == [row["id"]]


@needs_db
def test_a_person_named_without_any_proven_alias_is_recalled(conn, monkeypatch):
    """Measured on the sealed seed 6: a name with no alias crashed the fusion."""
    from pensine import graph, mcp_server
    monkeypatch.setattr(mcp_server.embeddings, "embed", lambda *a, **k: None)
    graph.upsert_entity(conn, "TestOrla", "person")
    conn.commit()
    assert isinstance(mcp_server.recall("Where does TestOrla live?"), str)
