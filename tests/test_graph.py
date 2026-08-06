"""Graphe temporel : intégration sur base réelle (skip sans PENSINE_TEST_DB)."""

import os
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("PENSINE_TEST_DB"),
    reason="PENSINE_TEST_DB non défini (test d'intégration)",
)


@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setattr("pensine.config.DATABASE_URL",
                        os.environ["PENSINE_TEST_DB"])
    from pensine import db
    with db.connection() as c:
        yield c
        c.rollback()  # rien ne persiste


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def test_exclusive_ferme_l_ancienne_arete(conn):
    from pensine import graph
    alice = graph.upsert_entity(conn, "TestAlice", "person")
    lyon = graph.upsert_entity(conn, "TestLyon", "place")
    annecy = graph.upsert_entity(conn, "TestAnnecy", "place")

    graph.add_relation(conn, subject_id=alice, predicate="habite à",
                       object_id=lyon, valid_from=_dt(2024, 1, 1), exclusive=True)
    graph.add_relation(conn, subject_id=alice, predicate="habite à",
                       object_id=annecy, valid_from=_dt(2026, 3, 1), exclusive=True)

    rows = conn.execute(
        """SELECT o.name, r.valid_to, r.invalidated_at FROM relations r
           JOIN entities o ON o.id = r.object_id
           WHERE r.subject_id = %s AND r.predicate = 'habite à'
           ORDER BY r.valid_from""", (alice,)).fetchall()
    assert len(rows) == 2
    assert rows[0]["name"] == "TestLyon"
    assert rows[0]["valid_to"] is not None          # fermée, jamais effacée
    assert rows[0]["invalidated_at"] is not None    # temps du système tracé
    assert rows[1]["valid_to"] is None              # la nouvelle est active


def test_dedup_arete_active(conn):
    from pensine import graph
    a = graph.upsert_entity(conn, "TestBob", "person")
    b = graph.upsert_entity(conn, "TestTrail", "project")
    r1 = graph.add_relation(conn, subject_id=a, predicate="travaille sur",
                            object_id=b, valid_from=_dt(2026, 1, 1))
    r2 = graph.add_relation(conn, subject_id=a, predicate="travaille sur",
                            object_id=b, valid_from=_dt(2026, 2, 1))
    assert r1 is not None and r2 is None  # doublon actif non recréé


def test_neighborhood_au_temps_t(conn):
    from pensine import graph
    alice = graph.upsert_entity(conn, "TestCarole", "person")
    lyon = graph.upsert_entity(conn, "TestGrenoble", "place")
    graph.add_relation(conn, subject_id=alice, predicate="habite à",
                       object_id=lyon, valid_from=_dt(2024, 1, 1),
                       valid_to=_dt(2025, 1, 1))
    # aujourd'hui : l'arête est fermée → absente du voisinage courant
    now_edges = graph.neighborhood(conn, "TestCarole")
    assert not any(e["object"] == "TestGrenoble" for e in now_edges)
    # mais au temps T (2024), elle était vraie
    then_edges = graph.neighborhood(conn, "TestCarole", at=_dt(2024, 6, 1))
    assert any(e["object"] == "TestGrenoble" for e in then_edges)


def test_upsert_insensible_a_la_casse(conn):
    from pensine import graph
    id1 = graph.upsert_entity(conn, "TestJeanne", "person")
    id2 = graph.upsert_entity(conn, "testjeanne", "person")
    assert id1 == id2
