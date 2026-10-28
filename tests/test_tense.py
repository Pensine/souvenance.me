"""Anchoring in reality: past, present, future, computed in code."""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from pensine import temporal

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def d(days: int) -> datetime:
    return NOW + timedelta(days=days)


# --- orientation of the question -----------------------------------------------

@pytest.mark.parametrize("q, expected", [
    ("quoi de neuf ce mois-ci ?", "recent"),
    ("où j'en suis sur Atelier Nova", "recent"),
    ("what's new lately", "recent"),
    ("qu'est-ce que je pensais en juin du projet ?", "past"),
    ("il y a 3 mois, j'en étais où ?", "past"),
    ("avant ma décision récente", "past"),  # the past wins
    ("quelles courses sont prévues ?", "future"),
    ("ma prochaine échéance", "future"),
    ("est-ce qu'il y a des tensions avec Thibault ?", None),  # "il y a" (there is) != past
    ("Pensine architecture mémoire", None),
])
def test_orientation(q, expected):
    assert temporal.intent(q) == expected


# --- tense and distance of a memory -------------------------------------------

def test_temps_d_une_memoire():
    assert temporal.tense(d(-100), None, None, NOW) == "present"
    assert temporal.tense(d(-100), d(-5), None, NOW) == "past"      # closed
    assert temporal.tense(d(-100), None, 42, NOW) == "past"         # replaced
    assert temporal.tense(d(30), None, None, NOW) == "future"       # upcoming
    assert temporal.tense(d(-100), d(10), None, NOW) == "present"   # closed later


def test_distance_vecue():
    assert temporal.distance(d(-10), None, NOW) == "proche"
    assert temporal.distance(d(-200), None, NOW) == "lointain"
    assert temporal.distance(d(-900), None, NOW) == "ancien"
    assert temporal.distance(d(-10), d(-1), NOW) == "lointain"  # archived: set aside


# --- ranking ------------------------------------------------------------------

def _row(i, dist, frm, to=None, sup=None, arch=None):
    return {"id": i, "distance": dist, "valid_from": frm, "valid_to": to,
            "superseded_by": sup, "archived_at": arch}


def test_le_present_passe_devant_le_passe_sauf_si_on_regarde_en_arriere():
    old = _row(1, 0.20, d(-150), to=d(-30), sup=2)   # old version, very close
    new = _row(2, 0.25, d(-30))                       # up-to-date version, slightly less close
    assert [r["id"] for r in temporal.rank([old, new], None, now=NOW)] == [2, 1]
    assert [r["id"] for r in temporal.rank([old, new], "past", now=NOW)] == [1, 2]


def test_recemment_fait_remonter_le_frais():
    vieux = _row(1, 0.20, d(-300))
    frais = _row(2, 0.28, d(-3))
    assert temporal.rank([vieux, frais], None, now=NOW)[0]["id"] == 1
    assert temporal.rank([vieux, frais], "recent", now=NOW)[0]["id"] == 2


def test_l_avenir_remonte_quand_on_le_demande():
    present = _row(1, 0.20, d(-10))
    projet = _row(2, 0.26, d(40))
    assert temporal.rank([present, projet], "future", now=NOW)[0]["id"] == 2


def test_archivee_recule():
    vivante = _row(1, 0.25, d(-10))
    archivee = _row(2, 0.20, d(-10), arch=d(-1))
    assert temporal.rank([vivante, archivee], None, now=NOW)[0]["id"] == 1


# --- presentation in recall --------------------------------------------------------

def test_situer_une_memoire_revolue():
    from pensine.mcp_server import _situate
    r = {"valid_from": d(-150), "valid_to": d(-30), "superseded_by": 7,
         "revision_note": "le projet a été abandonné", "archived_at": None}
    out = _situate(r, {7: "Nouvelle version"})
    assert out["temps"] == "past" and out["encore_vrai"] is False
    assert out["revolu"]["raison"] == "le projet a été abandonné"
    assert out["revolu"]["remplacee_par"] == {"id": 7, "content": "Nouvelle version"}
    assert out["revolu"]["depuis"]


# --- consolidation: only replace what was shown ------------------------------------

def _nightly():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))
    import nightly
    return nightly


class _Conn:
    def __init__(self):
        self.next_id = 100

    def execute(self, sql, params=None):
        conn = self

        class _R:
            def fetchone(self_inner):
                conn.next_id += 1
                return {"id": conn.next_id}
        return _R()


def test_remplacement_limite_aux_connaissances_montrees(monkeypatch):
    nightly = _nightly()
    closed = []
    monkeypatch.setattr(nightly.embeddings, "embed", lambda *a, **k: None)
    monkeypatch.setattr(nightly.db, "close_memory",
                        lambda conn, mid, **k: closed.append((mid, k["successor_id"], k["reason"])))
    items = [{"type": "semantic", "content": "X est arrêté", "confidence": 0.9,
              "importance": 0.7, "valid_from": "2026-10-01T00:00:00+00:00",
              "remplace": ["12", 99, "pas-un-id"], "raison": "abandonné en octobre"}]
    written = nightly.write_memories(_Conn(), items, allowed={12, 13})
    assert written[0]["replaced"] == [12]           # 99 was not shown
    assert closed == [(12, 101, "abandonné en octobre")]


def test_revolues_sans_successeur(monkeypatch):
    nightly = _nightly()
    closed = []
    monkeypatch.setattr(nightly.db, "close_memory",
                        lambda conn, mid, **k: closed.append((mid, k["reason"])))
    n = nightly.close_ended(None, [{"memory_id": 13, "raison": "terminé"},
                                   {"memory_id": 500, "raison": "hors champ"}], {12, 13})
    assert n == 1 and closed == [(13, "terminé")]


# --- integration: revise then archive on a real database -----------------------------

@pytest.mark.skipif(not os.environ.get("PENSINE_TEST_DB"),
                    reason="PENSINE_TEST_DB not set (integration test)")
def test_reviser_puis_archiver(monkeypatch):
    monkeypatch.setattr("pensine.config.DATABASE_URL", os.environ["PENSINE_TEST_DB"])
    monkeypatch.setattr("pensine.embeddings.embed", lambda *a, **k: None)
    from pensine import db
    from pensine.mcp_server import archive_memory, revise_memory

    with db.connection() as conn:
        mid = conn.execute(
            """INSERT INTO memories (type, content, confidence, importance, valid_from)
               VALUES ('semantic', 'TestRevision : le projet X est en cours', 0.9, 0.5,
                       '2026-06-01') RETURNING id""").fetchone()["id"]
        conn.commit()

    msg = revise_memory(mid, "le projet X a été abandonné",
                        "TestRevision : le projet X est abandonné", "2026-09-15")
    assert "closed" in msg and "Replaced by" in msg
    assert "already replaced" in revise_memory(mid, "encore")
    with db.connection() as conn:
        old = db.get_memory(conn, mid)
        assert old["superseded_by"] and old["valid_to"].date().isoformat() == "2026-09-15"
        new_id = old["superseded_by"]
    assert "archived" in archive_memory(new_id, "plus d'actualité")
    with db.connection() as conn:
        assert db.get_memory(conn, new_id)["archived_at"] is not None
        live = db.search_memories(conn, "TestRevision", None, mark=False)
        assert all(r["id"] not in (mid, new_id) for r in live)
        past = db.search_memories(conn, "TestRevision", None, mark=False,
                                  include_past=True, include_archived=True)
        assert {mid, new_id} <= {r["id"] for r in past}
