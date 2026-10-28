"""MCP landmark tool: validation in code (unit) + insertion (integration)."""

import os

import pytest

from pensine.mcp_server import LANDMARK_KINDS, _validate_landmark


def test_validation_ok():
    assert _validate_landmark("UTMB 2027", "2027-08-27", "race") == ""


def test_date_invalide():
    assert "Invalid date" in _validate_landmark("X", "4 juillet 2026", "race")


def test_kind_invalide():
    msg = _validate_landmark("X", "2026-07-04", "course")
    assert "Invalid kind" in msg
    for kind in LANDMARK_KINDS:
        assert kind in msg  # the message lists the expected kinds


def test_nom_manquant():
    assert "name missing" in _validate_landmark("  ", "2026-07-04", "race")


@pytest.mark.skipif(
    not os.environ.get("PENSINE_TEST_DB"),
    reason="PENSINE_TEST_DB not set (integration test)",
)
def test_insertion_et_doublon(monkeypatch):
    monkeypatch.setattr("pensine.config.DATABASE_URL",
                        os.environ["PENSINE_TEST_DB"])
    from pensine.mcp_server import landmark

    first = landmark("TestJalon pytest", "2030-01-15", "life_event")
    assert "set on 2030-01-15" in first
    again = landmark("TestJalon pytest", "2030-01-15", "life_event")
    assert "duplicate ignored" in again

    # cleanup (the landmarks table is not append-only: it is a reference table)
    from pensine import db
    with db.connection() as conn:
        conn.execute("DELETE FROM landmarks WHERE name = 'TestJalon pytest'")
        conn.execute("DELETE FROM audit_log WHERE action = 'landmark' "
                     "AND detail->>'name' = 'TestJalon pytest'")
        conn.commit()
