"""The night proposes who is who; the code decides (no model, no database)."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))

import nightly  # noqa: E402

from pensine import config  # noqa: E402

TEXT = "Dinner with my sister Priya tonight. My sister works at Marrowgate Press."
ANSWER = {
    "memories": [{"type": "semantic", "content": "My sister works at Marrowgate Press.",
                  "source_event_ids": [1], "preuve": ["My sister works at Marrowgate Press"],
                  "subject": "my sister"}],
    "aliases": [{"name": "Priya", "alias": "my sister", "role_of_owner": "sister",
                 "excerpt": "my sister Priya", "source_event_id": 1, "confidence": 0.9}],
    "entities": [], "relations": []}


def test_aliases_and_subjects_survive_validation():
    night, problem = nightly.validate_night({**ANSWER, "aliases": {"name": "Priya",
                                                                   "alias": "my sister"}})
    assert problem is None
    assert night["aliases"] == [{"name": "Priya", "alias": "my sister"}]  # one object mended
    assert night["memories"][0]["subject"] == "my sister"
    night, _ = nightly.validate_night({"aliases": ["junk", {"name": "A", "alias": "B"}]})
    assert night["aliases"] == [{"name": "A", "alias": "B"}]


def test_subject_field_is_repaired_not_fatal():
    night, problem = nightly.validate_night({"memories": [
        {"type": "semantic", "content": "a", "subject": "  Priya "},
        {"type": "semantic", "content": "b", "sujet": "ma sœur"},
        {"type": "semantic", "content": "c", "subject": 12},
        {"type": "semantic", "content": "d", "subject": "x" * 200}]})
    assert problem is None
    assert [m.get("subject") for m in night["memories"]] == ["Priya", "ma sœur", None, None]


def test_owner_words_name_the_owner(monkeypatch):
    seen = []
    monkeypatch.setattr(config, "OWNER_NAME", "Maya Collins")
    monkeypatch.setattr(nightly.graph, "resolve_subject",
                        lambda conn, m: seen.append(m) or (7, None))
    cache = {}
    assert nightly.memory_subject(None, "I", cache) == (7, None)
    assert nightly.memory_subject(None, "me", cache) == (7, None)   # cached: same person
    assert nightly.memory_subject(None, "my sister", cache) == (7, None)
    assert nightly.memory_subject(None, None, cache) is None
    assert seen == ["Maya Collins", "my sister"]


def test_claims_are_ingested_before_memories_are_written(monkeypatch):
    """Tonight's "my sister" must already land on Priya: the claims go to
    graph.ingest (with the batch's deposits, to check excerpts) before
    write_memories resolves the subjects."""
    order = []
    monkeypatch.setattr(nightly.llm, "complete", lambda prompt, **k: json.dumps(ANSWER))
    monkeypatch.setattr(nightly, "_knowledge", lambda *a, **k: [])
    monkeypatch.setattr(nightly, "link_episodes", lambda conn, w: 0)
    monkeypatch.setattr(nightly.intentions, "open_steps", lambda *a, **k: [])
    monkeypatch.setattr(nightly.relations, "ingest", lambda *a, **k: 0)
    monkeypatch.setattr(nightly.db, "audit", lambda *a, **k: None)
    monkeypatch.setattr(nightly.db, "mark_examined", lambda *a, **k: None)
    monkeypatch.setattr(nightly.integrity, "record_candidates", lambda *a, **k: None)
    monkeypatch.setattr(config, "VERIFY", "code")

    def ingest(conn, entities, relations, ids, aliases=None, events=None):
        order.append(("ingest", [a["alias"] for a in aliases], [e["id"] for e in events]))
        return {"aliases_admitted": 1}

    def write(conn, items, allowed, places, **kw):
        order.append(("write", [m["subject"] for m in items]))
        return []
    monkeypatch.setattr(nightly.graph, "ingest", ingest)
    monkeypatch.setattr(nightly, "write_memories", write)

    class Gov:
        def constitution_text(self):
            return ""
    event = {"id": 1, "source": "test", "kind": "note", "payload": {"text": TEXT},
             "occurred_at": datetime(2025, 2, 15, 9, tzinfo=timezone.utc)}
    r = nightly.consolidate(None, Gov(), [event])
    assert order == [("ingest", ["my sister"], [1]), ("write", ["my sister"])]
    assert r["aliases_admitted"] == 1


def test_prompt_asks_for_subjects_and_claims():
    for words in ("`subject`", "`aliases`", "`excerpt`", "même proposition"):
        assert words in nightly.PROMPT
