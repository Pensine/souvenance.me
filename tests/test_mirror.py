"""The mirror shows what is new, not just what weighs the most."""

import json
from contextlib import contextmanager
from datetime import datetime, timezone


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Answers according to the query: trajectory, entities, reflections, recent."""

    def __init__(self, recent):
        self.recent = recent

    def execute(self, sql, params=None):
        if "date_trunc('quarter'" in sql:
            return _Rows([{"periode": "2026 T3", "type": "semantic", "n": 2,
                           "saillant": ["ancienne mais importante"]}])
        if "ORDER BY valid_from DESC, id DESC" in sql:
            return _Rows(self.recent)
        return _Rows([])

    def commit(self):
        pass


def test_dernieres_memoires_datees_et_dans_l_ordre(monkeypatch):
    from pensine import db, mcp_server, temporal

    recent = [
        {"id": 51, "type": "semantic", "content": "fraîche et modeste",
         "valid_from": datetime(2026, 8, 24, tzinfo=timezone.utc),
         "source_event_ids": [22]},
        {"id": 44, "type": "reflection", "content": "plus ancienne",
         "valid_from": datetime(2026, 8, 13, tzinfo=timezone.utc),
         "source_event_ids": None},
    ]

    @contextmanager
    def _conn():
        yield _FakeConn(recent)

    monkeypatch.setattr(db, "connection", _conn)
    monkeypatch.setattr(db, "audit", lambda *a, **k: None)
    monkeypatch.setattr(temporal, "frame", lambda *a, **k: {})
    monkeypatch.setattr(mcp_server, "get_persona", lambda *a, **k: "")

    out = json.loads(mcp_server.mirror("quoi de neuf ?"))
    dernieres = out["dernieres_memoires"]
    assert [m["id"] for m in dernieres] == [51, 44]
    assert dernieres[0]["date"] == "2026-08-24"
    assert dernieres[0]["evenements"] == [22]
    assert dernieres[1]["evenements"] == []  # NULL in the database -> empty list
    assert dernieres[0]["quand"]  # human-readable duration computed in code
