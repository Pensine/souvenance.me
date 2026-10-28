"""A night the model answers badly must not block the nights after it.

Measured on the SOURCED sample (2026-10-28, Qwen 3.5 4B local): 6 of 14
nights failed on invalid JSON, the backlog grew from 6 to 18 deposits, and
facts deposited on the failed nights never reached memory. These tests pin
the remedy: tolerant reading, a stricter re-ask, splitting, and deposits
left pending (never lost) when a single one still fails.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))

import nightly  # noqa: E402

from pensine import config, language, llm  # noqa: E402

NIGHT = {"memories": [{"type": "semantic", "content": "Kofi lives in Ghent.",
                       "preuve": ["I live in Ghent"]}], "entities": [], "relations": []}


# -- parse_json -------------------------------------------------------------------

def test_clean_json_is_clean():
    assert llm.parse_json(json.dumps(NIGHT)) == (NIGHT, "clean")


def test_fenced_json_with_prose_around_is_repaired():
    raw = "Here is the result:\n```json\n" + json.dumps(NIGHT) + "\n```\nHope it helps!"
    assert llm.parse_json(raw) == (NIGHT, "repaired")


def test_trailing_text_after_the_object_is_ignored():
    raw = json.dumps(NIGHT) + "\n\nNote: I skipped the noise. {not json}"
    assert llm.parse_json(raw)[0] == NIGHT


def test_trailing_commas_are_dropped():
    raw = '{"memories": [{"type": "semantic", "content": "a, b",},], "entities": [],}'
    value, how = llm.parse_json(raw)
    assert how == "repaired"
    assert value == {"memories": [{"type": "semantic", "content": "a, b"}], "entities": []}


def test_truncated_array_keeps_the_complete_elements():
    whole = json.dumps({"memories": [{"content": "one"}, {"content": "two"},
                                     {"content": "three, cut"}]})
    raw = whole[:whole.index("three") + 3]  # stops inside the third memory
    value, how = llm.parse_json(raw)
    assert how == "truncated"
    assert value == {"memories": [{"content": "one"}, {"content": "two"}]}


def test_truncation_inside_a_string_with_brackets_is_handled():
    raw = '{"memories": [{"content": "a [b] {c}"}, {"content": "unfinished } ] text'
    value, how = llm.parse_json(raw)
    assert (value, how) == ({"memories": [{"content": "a [b] {c}"}]}, "truncated")


def test_escaped_quotes_do_not_end_a_string():
    raw = '{"memories": [{"content": "she said \\"hi\\""}, {"content": "x'
    assert llm.parse_json(raw)[0] == {"memories": [{"content": 'she said "hi"'}]}


def test_think_block_is_stripped_and_unclosed_one_fails():
    assert llm.parse_json("<think>draft</think>" + json.dumps(NIGHT))[0] == NIGHT
    with pytest.raises(ValueError):
        llm.parse_json("<think>still thinking about the {memories")


def test_nothing_recoverable_raises_value_error():
    for raw in ("", "I could not find any memory.", '{"memories": [', "[[[["):
        with pytest.raises(ValueError):
            llm.parse_json(raw)


def test_extract_json_keeps_its_contract():
    assert llm.extract_json("```json\n[1, 2]\n```") == [1, 2]


# -- validate_night ---------------------------------------------------------------

def test_old_list_format_is_still_accepted():
    night, problem = nightly.validate_night([{"type": "Episodic", "content": "x"}])
    assert problem is None
    assert night["memories"] == [{"type": "episodic", "content": "x"}]
    assert night["entities"] == [] and night["relations"] == []


def test_wrong_shapes_are_problems_not_crashes():
    assert nightly.validate_night("text")[1]
    assert nightly.validate_night({"answer": "nothing"})[1]
    assert nightly.validate_night({"memories": "none"})[1]


def test_harmless_shapes_are_mended():
    night, problem = nightly.validate_night(
        {"memories": [{"type": "semantic", "content": "x"}, "stray", 3],
         "entities": {"name": "Kofi"}, "relations": None})
    assert problem is None
    assert night["memories"] == [{"type": "semantic", "content": "x"}]
    assert night["entities"] == [{"name": "Kofi"}]
    assert night["relations"] == []


def test_bad_field_values_are_neutralized_not_fatal():
    night, problem = nightly.validate_night({"memories": [
        {"type": "semantic", "content": "x", "confidence": "high", "importance": 7,
         "valid_from": "unknown", "valid_to": "2025-02-12T?", "source_event_ids": ["3", "x", 3],
         "remplace": "12"},
        {"type": "semantic", "content": None}],
        "relations": [{"subject": "a", "predicate": "p", "object": "b",
                       "valid_from": "next week"}, "junk"],
        "revolues": [{"memory_id": 1, "valid_to": "2025-02-10"}]})
    assert problem is None
    m, = night["memories"]
    assert (m["confidence"], m["importance"]) == (0.5, 1.0)
    assert m["valid_from"] is None and m["valid_to"] == "2025-02-12"
    assert m["source_event_ids"] == [3] and m["remplace"] == [12]
    assert night["relations"] == [{"subject": "a", "predicate": "p", "object": "b",
                                   "valid_from": None}]
    assert night["revolues"][0]["valid_to"] == "2025-02-10"


# -- ask_night: bounded retry, stricter re-ask --------------------------------------

def _scripted(monkeypatch, answers):
    prompts = []

    def complete(prompt, **kwargs):
        prompts.append((prompt, kwargs))
        return answers[min(len(prompts) - 1, len(answers) - 1)]
    monkeypatch.setattr(nightly.llm, "complete", complete)
    return prompts


def test_a_malformed_answer_is_asked_again_stricter(monkeypatch):
    prompts = _scripted(monkeypatch, ["Sure! {memories: oops", json.dumps(NIGHT)])
    night, stats = nightly.ask_night("PROMPT")
    assert night["memories"] == NIGHT["memories"]
    assert stats["calls"] == 2
    assert prompts[0][0] == "PROMPT"
    assert prompts[1][0].startswith("PROMPT") and "UN SEUL objet JSON" in prompts[1][0]
    assert all(kw.get("json_mode") for _, kw in prompts)


def test_retries_are_bounded(monkeypatch):
    monkeypatch.setattr(config, "CONSOLIDATION_ATTEMPTS", 3)
    prompts = _scripted(monkeypatch, ["no json at all"])
    with pytest.raises(nightly.MalformedOutput):
        nightly.ask_night("PROMPT")
    assert len(prompts) == 3


def test_malformed_output_is_a_value_error():
    """Callers that caught ValueError (the SOURCED adapter) keep working."""
    assert issubclass(nightly.MalformedOutput, ValueError)


def test_truncated_answer_only_accepted_when_it_cannot_be_split(monkeypatch):
    cut = json.dumps({"memories": [{"type": "semantic", "content": "a"},
                                   {"type": "semantic", "content": "b"}]})[:-12]
    _scripted(monkeypatch, [cut])
    with pytest.raises(nightly.MalformedOutput, match="coupée"):
        nightly.ask_night("PROMPT", accept_truncated=False)
    night, stats = nightly.ask_night("PROMPT", accept_truncated=True)
    assert [m["content"] for m in night["memories"]] == ["a"]
    assert stats["truncated"] == 1


def test_a_whole_answer_after_a_truncated_one_wins(monkeypatch):
    cut = json.dumps(NIGHT)[:-15]
    _scripted(monkeypatch, [cut, json.dumps(NIGHT)])
    night, stats = nightly.ask_night("PROMPT", accept_truncated=True)
    assert night["memories"] == NIGHT["memories"] and stats["truncated"] == 0


# -- consolidate: splitting, pending, never blocking ---------------------------------

def _events(n):
    return [{"id": i, "occurred_at": datetime(2025, 2, 11, 8, i, tzinfo=timezone.utc),
             "source": "test", "kind": "note", "payload": {"text": f"deposit {i}"}}
            for i in range(1, n + 1)]


def _batch_stub(monkeypatch, fails):
    seen, audits = [], []

    def batch(conn, governor, events):
        ids = [e["id"] for e in events]
        seen.append(ids)
        if fails(ids):
            raise nightly.MalformedOutput("JSON illisible")
        return {"memories_written": len(ids), "memories_rejected": 0}
    monkeypatch.setattr(nightly, "consolidate_batch", batch)
    monkeypatch.setattr(nightly.db, "audit", lambda conn, actor, action, detail=None:
                        audits.append((action, detail)))
    return seen, audits


def test_an_oversized_night_is_split_until_it_passes(monkeypatch):
    seen, audits = _batch_stub(monkeypatch, fails=lambda ids: len(ids) > 2)
    r = nightly.consolidate(None, None, _events(6))
    assert r["memories_written"] == 6
    assert r["events_pending"] == 0
    assert seen[0] == [1, 2, 3, 4, 5, 6]
    assert sorted(i for ids in seen if len(ids) <= 2 for i in ids) == [1, 2, 3, 4, 5, 6]
    assert not [a for a in audits if a[0] == "batch_failed"]


def test_a_poisoned_deposit_stays_pending_and_does_not_block_the_others(monkeypatch):
    seen, audits = _batch_stub(monkeypatch, fails=lambda ids: 3 in ids)
    r = nightly.consolidate(None, None, _events(5))
    assert r["memories_written"] == 4
    assert r["events_pending"] == 1
    failed = [d for a, d in audits if a == "batch_failed"]
    assert failed and failed[0]["event_ids"] == [3]
    assert "deposit" not in json.dumps(failed)  # the audit never copies content


def test_chronological_order_is_kept(monkeypatch):
    seen, _ = _batch_stub(monkeypatch, fails=lambda ids: len(ids) > 1)
    nightly.consolidate(None, None, _events(4))
    singles = [ids[0] for ids in seen if len(ids) == 1]
    assert singles == [1, 2, 3, 4]


def test_max_events_bounds_each_call(monkeypatch):
    monkeypatch.setattr(config, "CONSOLIDATION_MAX_EVENTS", 2)
    seen, _ = _batch_stub(monkeypatch, fails=lambda ids: False)
    r = nightly.consolidate(None, None, _events(5))
    assert seen == [[1, 2], [3, 4], [5]]
    assert r["batches"] == 3


def test_a_value_the_code_refuses_is_split_like_a_bad_answer(monkeypatch):
    """Measured: a night failed on a ValueError raised after the model had
    answered (a date the code could not read). It must not block the night."""
    def batch(conn, governor, events):
        if any(e["id"] == 2 for e in events):
            raise ValueError("Invalid isoformat string: 'deposit 2 text'")
        return {"memories_written": len(events)}
    audits = []
    monkeypatch.setattr(nightly, "consolidate_batch", batch)
    monkeypatch.setattr(nightly.db, "audit", lambda conn, actor, action, detail=None:
                        audits.append(detail))
    r = nightly.consolidate(None, None, _events(3))
    assert r["memories_written"] == 2 and r["events_pending"] == 1
    assert audits[-1] == {"event_ids": [2], "errors": ["ValueError"]}  # no content


def test_each_batch_runs_in_a_savepoint(monkeypatch):
    class Conn:
        def __init__(self):
            self.log = []

        def transaction(self):
            conn = self

            class T:
                def __enter__(self):
                    conn.log.append("begin")

                def __exit__(self, exc_type, *a):
                    conn.log.append("rollback" if exc_type else "release")
                    return False
            return T()

    def batch(conn, governor, events):
        if len(events) > 1:
            raise nightly.MalformedOutput("x")
        return {"memories_written": 1}
    monkeypatch.setattr(nightly, "consolidate_batch", batch)
    monkeypatch.setattr(nightly.db, "audit", lambda *a, **k: None)
    conn = Conn()
    nightly.consolidate(conn, None, _events(2))
    assert conn.log == ["begin", "rollback", "begin", "release", "begin", "release"]


def test_an_outage_is_still_a_pause_not_a_split(monkeypatch):
    calls = []

    def batch(conn, governor, events):
        calls.append(len(events))
        raise llm.LLMUnavailable("server down")
    monkeypatch.setattr(nightly, "consolidate_batch", batch)
    with pytest.raises(llm.LLMUnavailable):
        nightly.consolidate(None, None, _events(4))
    assert calls == [4]


# -- consolidate_batch end to end (fake model, no database) ---------------------------

def _wire(monkeypatch, answers):
    prompts = _scripted(monkeypatch, answers)
    for name, value in (("write_memories", lambda *a, **k: []),
                        ("_knowledge", lambda *a, **k: []),
                        ("link_episodes", lambda conn, w: 0)):
        monkeypatch.setattr(nightly, name, value)
    monkeypatch.setattr(nightly.intentions, "open_steps", lambda *a, **k: [])
    monkeypatch.setattr(nightly.graph, "ingest", lambda *a, **k: {})
    monkeypatch.setattr(nightly.relations, "ingest", lambda *a, **k: 0)
    monkeypatch.setattr(nightly.db, "audit", lambda *a, **k: None)
    monkeypatch.setattr(nightly.integrity, "record_candidates", lambda *a, **k: None)
    marked = []
    monkeypatch.setattr(nightly.db, "mark_examined",
                        lambda conn, ids, mids: marked.extend(ids))
    monkeypatch.setattr(config, "VERIFY", "code")
    return prompts, marked


class _Gov:
    def constitution_text(self):
        return ""


def _event(i, text):
    return {"id": i, "source": "test", "kind": "note",
            "occurred_at": datetime(2025, 2, 15, 9, tzinfo=timezone.utc),
            "payload": {"text": text}}


EN = "We finally moved into the new flat in Turin today, and I start the new job on Monday."
FR = "On a enfin emménagé dans le nouvel appartement à Chambéry, et je commence lundi."


def test_failed_nights_leave_events_unmarked(monkeypatch):
    prompts, marked = _wire(monkeypatch, ["not json"])
    r = nightly.consolidate(None, _Gov(), [_event(1, EN), _event(2, FR)])
    assert r["events_pending"] == 2
    assert marked == []  # nothing marked: both come back next night


def test_retry_then_success_marks_the_events(monkeypatch):
    prompts, marked = _wire(monkeypatch, ["oops", json.dumps(NIGHT)])
    r = nightly.consolidate(None, _Gov(), [_event(1, EN)])
    assert r["events_pending"] == 0 and r["llm_calls"] == 2
    assert marked == [1]


def test_prompt_names_english_for_english_deposits(monkeypatch):
    prompts, _ = _wire(monkeypatch, [json.dumps(NIGHT)])
    nightly.consolidate(None, _Gov(), [_event(1, EN)])
    p = prompts[0][0]
    assert '"langue": "en"' in p
    assert p.rstrip().endswith("Do not translate.")
    assert "Write every memory" in p and "{{LANGUAGE}}" not in p


def test_prompt_keeps_french_for_french_deposits(monkeypatch):
    prompts, _ = _wire(monkeypatch, [json.dumps(NIGHT)])
    nightly.consolidate(None, _Gov(), [_event(1, FR)])
    p = prompts[0][0]
    assert '"langue": "fr"' in p
    assert "Langue d'écriture : français (fr)" in p and "Ne traduis pas." in p


def test_mixed_night_asks_for_each_deposit_language(monkeypatch):
    prompts, _ = _wire(monkeypatch, [json.dumps(NIGHT)])
    nightly.consolidate(None, _Gov(), [_event(1, EN), _event(2, FR)])
    assert "celle de chaque événement source" in prompts[0][0]


def test_language_can_be_forced(monkeypatch):
    monkeypatch.setattr(config, "MEMORY_LANGUAGE", "fr")
    prompts, _ = _wire(monkeypatch, [json.dumps(NIGHT)])
    nightly.consolidate(None, _Gov(), [_event(1, EN)])
    assert "Langue d'écriture : français (fr)" in prompts[0][0]


# -- language ---------------------------------------------------------------------

@pytest.mark.parametrize("text,code", [
    (EN, "en"), (FR, "fr"),
    ("J'ai signé le bail hier, c'est fait.", "fr"),
    ("Hoy fui al mercado con mi hermana y compramos fruta para la semana.", "es"),
    ("Heute war ich mit meinem Bruder im Park und es war sehr schön.", "de"),
    ("Oggi è una bella giornata e sono molto felice.", "it"),
])
def test_detect(text, code):
    assert language.detect(text) == code


def test_too_short_to_tell_is_none():
    assert language.detect("OK, see you") is None
    assert language.detect("") is None


def test_short_memories_with_min_hits_one():
    assert language.detect("Kofi a déménagé à Turin.", min_hits=1) == "fr"
    assert language.detect("Kofi moved to Turin with his partner.", min_hits=1) == "en"


def test_short_deposit_takes_the_language_of_the_night():
    langs = nightly.event_languages([_event(1, EN), _event(2, "OK!")])
    assert langs == {1: "en", 2: "en"}


def test_language_check_counts_mismatches():
    langs = {1: "en"}
    r = nightly.language_check([
        {"content": "Kofi moved to Turin with his partner.", "source_event_ids": [1]},
        {"content": "Kofi a déménagé à Turin avec sa compagne.", "source_event_ids": [1]},
        {"content": "Turin", "source_event_ids": [1]},  # undecidable: not counted
    ], langs)
    assert r == {"language_checked": 2, "language_mismatched": 1}


def test_short_deposits_are_pooled_to_find_the_language():
    def photo(i, text):  # the SOURCED payload shape: the deposit id once read as French "d"
        return {"id": i, "payload": {"kind": "photo", "text": text, "author": "Kofi Achebe",
                                     "recipient": "", "deposit_id": f"D000{i}"}}
    langs = nightly.event_languages([photo(1, "Photo taken on 2025-02-03 at 16:26."),
                                     photo(2, "Photo taken on 2025-02-03 at 17:11.")])
    assert langs == {1: "en", 2: "en"}


def test_identifiers_are_not_words():
    assert language.detect("D0001 D0002 l2 c3 16h26", min_hits=1) is None
    assert language.detect("J'ai vu qu'il pleuvait, c'est l'hiver.") == "fr"


def test_a_reread_correction_that_translates_is_not_applied():
    from pensine import evidence

    events = [{"id": 1, "payload": {"text": "Got the keys today: the new place is 79 Linden "
                                            "Street, Ghent, and I love it."}}]
    memory = {"type": "semantic", "source_event_ids": [1],
              "content": "Kofi moved to 79 Linden Street in Ghent with his cat Mimi.",
              "preuve": ["the new place is 79 Linden Street, Ghent"]}
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return json.dumps({"verdict": "partielle",
                           "correction": "Kofi a emménagé au 79 Linden Street à Gand."})
    kept, report = evidence.verify([memory], events, ask=ask, extract_json=llm.extract_json)
    assert "Write every memory" in asked[0]  # the language is named in the reread
    assert kept[0]["content"] == memory["content"]  # not translated
    assert kept[0]["evidence"]["statut"] == "partielle"
    assert kept[0]["confidence"] <= 0.5
