"""What is coming: a step is born, lives, closes -- and a capsule stays sealed."""

import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from pensine import cards, intentions

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def test_statut_calcule_a_la_lecture():
    base = {"created_at": NOW - timedelta(days=10), "last_mentioned_at": None, "outcome": None}
    assert intentions.status(base, NOW) == "ouverte"
    vieux = {**base, "created_at": NOW - timedelta(days=90)}
    assert intentions.status(vieux, NOW) == "en_suspens"
    reevoque = {**vieux, "last_mentioned_at": NOW - timedelta(days=3)}
    assert intentions.status(reevoque, NOW) == "ouverte"
    assert intentions.status({**vieux, "outcome": "fait"}, NOW) == "fait"


def test_sujet_et_echeance():
    st = {"content": "Appeler Charles pour cadrer le montage", "trigger_kind": "topic",
          "trigger_value": "Atelier Nova"}
    assert intentions.matches(st, intentions.terms("où en est l'atelier Nôva ?"))  # accents and case ignored
    assert not intentions.matches(st, intentions.terms("mes zones cardiaques"))
    assert intentions.due_date(st) is None
    assert intentions.due_date({"trigger_kind": "date", "trigger_value": "2027-04-20"}) == date(2027, 4, 20)


def _nightly():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))
    import nightly
    return nightly


def test_consolidation_cree_ferme_evoque(monkeypatch):
    nightly = _nightly()
    calls = {"add": [], "close": [], "touch": []}
    monkeypatch.setattr(nightly.intentions, "add_step",
                        lambda conn, q, s, due, src, when: calls["add"].append((q, s, due, src, when)) or 99)
    monkeypatch.setattr(nightly.intentions, "close",
                        lambda conn, i, o, r, w: calls["close"].append((i, o, r, w)) or True)
    monkeypatch.setattr(nightly.intentions, "touch", lambda conn, ids, w: calls["touch"].append(ids))
    out = {"intentions": [{"quoi": "Appeler Charles", "sujet": "Atelier Nova", "echeance": None,
                           "source_event_ids": [5, 777]}],
           "intentions_closes": [{"intention_id": "3", "issue": "fait", "raison": "SAS lancée",
                                  "date": "2026-09-03"},
                                 {"intention_id": 404, "issue": "fait"}],   # never shown
           "intentions_evoquees": [4, 404]}
    occurred = {5: NOW - timedelta(days=1)}
    res = nightly.apply_intentions(None, out, {3, 4}, occurred)
    assert res == {"intentions_created": 1, "intentions_closed": 1}
    assert calls["add"] == [("Appeler Charles", "Atelier Nova", None, [5], NOW - timedelta(days=1))]
    assert calls["close"][0][:3] == (3, "fait", "SAS lancée")
    assert calls["close"][0][3].date() == date(2026, 9, 3)
    assert calls["touch"] == [[4]]


class _Conn:
    def execute(self, sql, params=None):
        class R:
            def fetchall(self_inner):
                return []
        return R()


def test_frise_place_les_etapes(monkeypatch):
    monkeypatch.setattr(cards.db, "chapters", lambda conn: [])
    monkeypatch.setattr(cards.db, "memory_snippets", lambda conn, ids: {})
    steps = [
        {"id": 1, "content": "Appeler Charles", "trigger_kind": "topic", "trigger_value": "Atelier Nova",
         "created_at": NOW - timedelta(days=60), "last_mentioned_at": NOW - timedelta(days=60),
         "resolved_at": None, "outcome": None, "outcome_note": None},
        {"id": 2, "content": "Lancer Arena", "trigger_kind": "date", "trigger_value": "2026-12-01",
         "created_at": NOW - timedelta(days=5), "last_mentioned_at": None,
         "resolved_at": None, "outcome": None, "outcome_note": None},
        {"id": 3, "content": "Ouvrir un compte pro", "trigger_kind": "topic", "trigger_value": "Atelier Nova",
         "created_at": NOW - timedelta(days=50), "last_mentioned_at": None,
         "resolved_at": NOW - timedelta(days=20), "outcome": "fait", "outcome_note": "fait à la banque"},
        {"id": 4, "content": "Pitch deck investisseurs", "trigger_kind": "topic", "trigger_value": "Atelier Nova",
         "created_at": NOW - timedelta(days=80), "last_mentioned_at": None,
         "resolved_at": None, "outcome": None, "outcome_note": None},
    ]
    monkeypatch.setattr(cards.intentions, "steps_for", lambda conn, subject: steps)
    lanes = cards.timeline(_Conn(), [], "Atelier Nova", now=NOW)["lanes"]
    vient = lanes["vient"]
    assert [i["intention_id"] for i in vient] == [2, 1, 4]       # the dated one first
    assert vient[1]["quand"].startswith("mentioned ")
    assert vient[2]["statut"] == "en_suspens"
    change = lanes["change"]
    assert change[0]["de"] == "Planned: Ouvrir un compte pro" and change[0]["vers"] == "done"
    assert change[0]["raison"] == "fait à la banque"


@pytest.mark.skipif(not os.environ.get("PENSINE_TEST_DB"),
                    reason="PENSINE_TEST_DB not set (integration test)")
def test_cycle_de_vie_complet(monkeypatch):
    monkeypatch.setattr("pensine.config.DATABASE_URL", os.environ["PENSINE_TEST_DB"])
    from pensine import db
    from pensine.mcp_server import capsule, close_step

    capsule("TestIntention : message scellé", "2030-01-01")
    with db.connection() as conn:
        a = intentions.add_step(conn, "TestIntention : appeler Charles pour le montage", "Atelier Nova")
        dup = intentions.add_step(conn, "testintention : Appeler Charles pour le montage !", "Atelier Nova")
        b = intentions.add_step(conn, "TestIntention : lancer Arena", "", "2026-12-01")
        conn.commit()
        assert a and b and dup is None                               # no duplicate
        ids = [r["id"] for r in intentions.open_steps(conn)]
        assert a in ids and b in ids
        assert all("scellé" not in r["content"] for r in intentions.open_steps(conn))
        found = intentions.steps_for(conn, "Atelier Nova")
        assert a in [r["id"] for r in found]

    assert "closed: done" in close_step(a, "fait", "SAS lancée")
    assert "not found, already closed" in close_step(a, "fait")
    with db.connection() as conn:
        cap = conn.execute("SELECT id FROM intentions WHERE content LIKE '%%TestIntention : message%%'"
                           ).fetchone()["id"]
    assert "it is a capsule" in close_step(cap, "fait")
