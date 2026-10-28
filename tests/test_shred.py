"""Crypto-shredding: forgetting in a log that erases nothing."""

import json
import os
from datetime import datetime, timezone

import pytest

from pensine import shred

WHEN = datetime(2026, 9, 14, 8, tzinfo=timezone.utc)


@pytest.fixture
def keys(tmp_path, monkeypatch):
    monkeypatch.setattr("pensine.config.KEYS_DIR", tmp_path / "keys")
    return tmp_path / "keys"


def test_sceller_ouvrir_detruire(keys):
    scope = shred.deposit_scope()
    env = shred.seal({"transcript": "rendez-vous chez ACME"}, scope)
    blob = json.dumps(env)
    assert "ACME" not in blob and shred.scope_of(blob) == scope
    assert shred.open_payload(blob) == {"transcript": "rendez-vous chez ACME"}
    assert oct((keys / f"{scope}.key").stat().st_mode)[-3:] == "600"
    assert shred.destroy_key(scope) and not (keys / f"{scope}.key").exists()
    assert shred.open_payload(env) is None              # forgotten for everyone
    assert shred.destroy_key(scope) is False            # idempotent
    rows = shred.open_rows([{"id": 1, "payload": env}, {"id": 2, "payload": {"a": 1}}])
    assert rows[0]["forgotten"] and rows[0]["payload"] == {}
    assert rows[1] == {"id": 2, "payload": {"a": 1}}    # not sealed: unchanged


def test_portee_de_sujet_opaque(keys):
    s = shred.subject_scope("  Santé  ")
    assert s == shred.subject_scope("santé") and "sant" not in s
    with pytest.raises(ValueError):
        shred.subject_scope(" ")
    with pytest.raises(ValueError):
        shred.key("../etc")


def test_hash_cle_ne_confirme_rien_apres_oubli(keys):
    scope = shred.deposit_scope()
    h1 = shred.keyed_hash(scope, "s", "k", WHEN, {"t": "x"})
    assert h1 == shred.keyed_hash(scope, "s", "k", WHEN, {"t": "x"})   # dedup within the scope
    from pensine import db
    assert h1 != db.event_hash("s", "k", WHEN, {"t": "x"})
    shred.destroy_key(scope)
    assert shred.keyed_hash(scope, "s", "k", WHEN, {"t": "x"}) != h1   # new key, different hash


def test_altere_refuse(keys):
    scope = shred.deposit_scope()
    env = shred.seal({"t": "x"}, scope)
    env[shred.ENVELOPE]["portee"] = shred.deposit_scope()  # scope swapped
    shred.key(env[shred.ENVELOPE]["portee"], create=True)
    with pytest.raises(Exception):
        shred.open_payload(env)


class _Conn:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        return {"id": 7}


def test_drapeau_eteint_rien_ne_change(keys, monkeypatch):
    from pensine import db
    monkeypatch.setattr("pensine.config.SHRED_ENABLED", False)
    c = _Conn()
    db.append_event(c, source="s", kind="k", occurred_at=WHEN, payload={"t": "x"})
    (sql, params), = c.calls
    assert json.loads(params[3]) == {"t": "x"} and params[5] == db.event_hash("s", "k", WHEN,
                                                                               {"t": "x"})
    assert not keys.exists()


def test_drapeau_allume_scelle(keys, monkeypatch):
    from pensine import db
    monkeypatch.setattr("pensine.config.SHRED_ENABLED", True)
    c = _Conn()
    db.append_event(c, source="s", kind="k", occurred_at=WHEN, payload={"t": "secret"})
    insert = next(p for s, p in c.calls if "INSERT INTO events" in s)
    assert "secret" not in insert[3] and insert[5].startswith("h1:")
    assert any("shred_scopes" in s for s, _ in c.calls)
    assert shred.open_payload(insert[3]) == {"t": "secret"}


# ------------------------------------------------------- integration (real database)

needs_db = pytest.mark.skipif(not os.environ.get("PENSINE_TEST_DB"),
                              reason="PENSINE_TEST_DB not set (integration test)")


@pytest.fixture
def conn(monkeypatch, keys, tmp_path):
    monkeypatch.setattr("pensine.config.DATABASE_URL", os.environ["PENSINE_TEST_DB"])
    monkeypatch.setattr("pensine.config.SHRED_ENABLED", True)
    monkeypatch.setattr("pensine.config.MEDIA_ROOT", tmp_path / "media")
    from pensine import db
    with db.connection() as c:
        yield c
        c.rollback()


def _memory(conn, content, sources):
    return conn.execute(
        "INSERT INTO memories (type, content, confidence, importance, valid_from, "
        "source_event_ids) VALUES ('episodic', %s, .8, .5, now(), %s) RETURNING id",
        (content, sources)).fetchone()["id"]


@needs_db
def test_oubli_de_bout_en_bout(conn, tmp_path):
    from pensine import db, graph
    (tmp_path / "media" / "2026").mkdir(parents=True)
    (tmp_path / "media" / "2026" / "a.m4a").write_bytes(b"voix")
    mid = db.insert_media(conn, captured_at=WHEN, kind="audio", storage_path="2026/a.m4a")
    conn.execute("UPDATE media SET transcript = 'voix secrète' WHERE id = %s", (mid,))
    secret = db.append_event(conn, source="pensieve", kind="deposit", occurred_at=WHEN,
                             payload={"note": "dépôt à oublier"}, media_id=mid)
    other = db.append_event(conn, source="daily_log", kind="daily_log", occurred_at=WHEN,
                            payload={"transcript": "journée ordinaire"})
    solo = _memory(conn, "issu du secret", [secret])
    mixed = _memory(conn, "issu des deux", [secret, other])
    keep = _memory(conn, "issu de l'autre", [other])
    conn.execute("INSERT INTO memory_links (source_id, target_id, kind) VALUES (%s, %s, 'x')",
                 (min(solo, keep), max(solo, keep)))
    a = graph.upsert_entity(conn, "TestOublie", "person")
    b = graph.upsert_entity(conn, "TestLieuOublie", "place")
    graph.add_relation(conn, subject_id=a, predicate="habite", object_id=b,
                       valid_from=WHEN, source_event_ids=[secret])
    db.mark_examined(conn, [secret, other], {solo, mixed, keep})

    assert db.source_events(conn, [secret])[0]["payload"] == {"note": "dépôt à oublier"}
    out = shred.forget(conn, event_id=secret, commit=False)

    assert out["cle_detruite"] and out["memoires"] == 2 and out["a_reconsolider"] == 1
    left = {r["id"] for r in conn.execute("SELECT id FROM memories WHERE id = ANY(%s)",
                                          ([solo, mixed, keep],)).fetchall()}
    assert left == {keep}
    # the event stays (append-only), unreadable
    row = db.source_events(conn, [secret])[0]
    assert row["forgotten"] and row["payload"] == {} and row["transcript"] is None
    assert "oublier" not in json.dumps(conn.execute(
        "SELECT payload FROM events WHERE id = %s", (secret,)).fetchone()["payload"])
    assert not (tmp_path / "media" / "2026" / "a.m4a").exists()
    assert conn.execute("SELECT count(*) AS n FROM entities WHERE name LIKE 'Test%%Oublie'"
                        ).fetchone()["n"] == 0
    # the other deposit goes back into consolidation; the forgotten one never does
    replay = {r["id"] for r in db.unconsolidated_events(conn, limit=10_000)}
    assert other not in replay  # still linked to the "keep" memory
    assert secret not in replay
    audit = conn.execute("SELECT detail FROM audit_log WHERE actor = 'shred' "
                         "ORDER BY id DESC LIMIT 1").fetchone()["detail"]
    assert "oublier" not in json.dumps(audit) and audit["memoires"] == 2


@needs_db
def test_oubli_refuse_un_depot_en_clair(conn, monkeypatch):
    from pensine import db
    monkeypatch.setattr("pensine.config.SHRED_ENABLED", False)
    eid = db.append_event(conn, source="s", kind="k", occurred_at=WHEN,
                          payload={"t": "ancien dépôt en clair"})
    with pytest.raises(shred.ShredError):
        shred.forget(conn, event_id=eid, commit=False)


def test_couches_une_cle_suffit(keys):
    a, b = shred.deposit_scope(), shred.deposit_scope()
    env = shred.seal_layers({"content": "candidate"}, [a, b])
    assert "candidate" not in json.dumps(env)
    assert shred.open_layers(json.dumps(env)) == {"content": "candidate"}
    assert shred.open_layers({"clair": 1}) == {"clair": 1}
    shred.destroy_key(b)                                # one of the two deposits forgotten
    assert shred.open_layers(env) is None


@needs_db
def test_journal_des_candidates_et_frontiere_sur_base(conn, monkeypatch):
    """A real night (dummy model): kept candidates sealed, frontier
    replayed from the database, then forgetting of a deposit that takes them along."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))
    import nightly
    from pensine import db, integrity
    from pensine.governor import Governor
    monkeypatch.setattr("pensine.config.LLM_BACKEND", "fake")
    monkeypatch.setattr("pensine.config.VERIFY", "code")
    monkeypatch.setattr("pensine.config.EMBEDDINGS_ENABLED", False)
    conn.execute("DELETE FROM night_candidates")
    e1 = db.append_event(conn, source="daily_log", kind="daily_log", occurred_at=WHEN,
                         payload={"transcript": "J'ai couru dix kilomètres autour du lac."})
    e2 = db.append_event(conn, source="daily_log", kind="daily_log", occurred_at=WHEN,
                         payload={"transcript": "Devis ACME reçu, réponse avant vendredi."})
    monkeypatch.setenv("PENSINE_FAKE_LLM_RESPONSE", json.dumps({"memories": [
        {"type": "episodic", "content": "Dix kilomètres autour du lac.", "source_event_ids": [e1],
         "preuve": ["couru dix kilomètres autour du lac"]},
        {"type": "episodic", "content": "Devis ACME de 4000 euros.", "source_event_ids": [e2],
         "preuve": ["Devis ACME reçu"]},
        {"type": "reflection", "content": "Il court pour oublier le devis.",
         "source_event_ids": [e1, e2], "preuve": []}]}))
    evs = [e for e in db.unconsolidated_events(conn, limit=10_000) if e["id"] in (e1, e2)]
    nightly.consolidate(conn, Governor(), evs)
    rows = conn.execute("SELECT issue, payload FROM night_candidates ORDER BY id").fetchall()
    assert [r["issue"] for r in rows] == ["ok", "relecture_absente", "aucun_extrait"]
    assert "ACME" not in json.dumps([r["payload"] for r in rows])     # sealed
    nights = integrity.nights_from_db(conn)
    assert len(nights) == 1 and len(nights[0]["candidates"]) == 3
    pts = {p["severite"]: p["gardees"]["k"]
           for p in integrity.frontier(nights)["points"]}
    assert pts == {"desactive": 3, "defaut": 2, "strict": 1}
    out = shred.forget(conn, event_id=e2, commit=False)
    assert out["candidates"] == 2                       # the one from e2 and the mixed one
    assert len(integrity.nights_from_db(conn)[0]["candidates"]) == 1
