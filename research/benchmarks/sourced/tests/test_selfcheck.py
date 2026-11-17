"""Judge validation without an annotator: the mutation control builds what
it says it builds, and a judge that reads nothing fails it."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourced.adapters.controls import OracleSystem  # noqa: E402
from sourced.deposits import build_deposits, deposit_dicts  # noqa: E402
from sourced.judge import LexicalJudge, normalize  # noqa: E402
from sourced.runner import load, run  # noqa: E402
from sourced.selfcheck import mutation_control, reader_name, reread  # noqa: E402
from sourced.tasks import derive_questions, question_dicts  # noqa: E402
from sourced.world import generate_world  # noqa: E402


@pytest.fixture(scope="module")
def life(tmp_path_factory):
    out = tmp_path_factory.mktemp("life")
    w = generate_world(seed=3, days=28, n_facts=60, n_changes=8)
    deps = build_deposits(w)
    (out / "truth.json").write_text(json.dumps(w.to_dict()))
    (out / "deposits.json").write_text(json.dumps(deposit_dicts(deps)))
    with open(out / "questions.jsonl", "w") as fh:
        for q in question_dicts(derive_questions(w, deps)):
            fh.write(json.dumps(q) + "\n")
    truth, deposits, qs = load(out)
    res = run(OracleSystem(truth, deposits, qs), out)
    return truth, deposits, res


def test_strict_twins_hold_a_value_no_deposit_has(life):
    truth, deposits, res = life
    rep = mutation_control(truth, deposits, res, LexicalJudge(truth, deposits))
    everything = normalize("\n".join(d["text"] for d in deposits))
    strict = [i for i in rep["items"] if i["mutation"]["strict"]
              and i["mutation"]["kind"] != "verbatim"]
    assert strict
    for i in strict:
        assert normalize(i["mutation"]["to"]) not in everything.split()
        assert i["mutation"]["to"] in i["content"]


def test_lexical_judge_catches_unknown_names_and_spares_verbatim(life):
    """A name found nowhere is exactly what the lexical judge can see. It is
    not the published judge: it misses a number hidden inside another one."""
    truth, deposits, res = life
    rep = mutation_control(truth, deposits, res, LexicalJudge(truth, deposits))
    names = rep["mutations"]["by_kind"]["person_outside"]
    assert names["n"] > 0 and names["rate"] == 1.0
    assert rep["verbatim"]["n"] > 0 and rep["verbatim"]["false_alarms"] == 0


def test_a_judge_that_accepts_everything_fails(life):
    truth, deposits, res = life

    class Lenient(LexicalJudge):
        name = "lenient"

        def label(self, memory):
            return {**super().label(memory), "support": "supported"}
    rep = mutation_control(truth, deposits, res, Lenient(truth, deposits))
    assert rep["mutations"]["strict"]["rate"] == 0.0 and not rep["passes"]


def test_a_judge_that_rejects_everything_fails(life):
    truth, deposits, res = life

    class Harsh(LexicalJudge):
        name = "harsh"

        def label(self, memory):
            return {**super().label(memory), "support": "unsupported"}
    rep = mutation_control(truth, deposits, res, Harsh(truth, deposits))
    assert rep["verbatim"]["rate"] == 1.0 and not rep["passes"]


def test_only_memories_the_judge_called_supported_are_edited(life):
    truth, deposits, res = life
    n = len(res["snapshots"][-1]["memories"])
    labels = [{"support": "unsupported"}] * n
    rep = mutation_control(truth, deposits, res, LexicalJudge(truth, deposits),
                           report={"snapshots": [{"labels": labels}]})
    assert rep["mutations"]["n"] == 0 and rep["verbatim"]["n"] == 0 and not rep["passes"]


def test_second_reader_sees_only_the_annotator_columns():
    seen = []

    def transport(body):
        seen.append(body["messages"][-1]["content"])
        return {"choices": [{"message": {"content": '{"label": "partial"}'
                                         if "Lisbon" in seen[-1] else "no idea"}}]}
    rows = [{"item": "1", "memory": "Lives in Lisbon.", "cited_excerpts": "I live in Lisbon",
             "cited_deposits_text": "I live in Lisbon now."},
            {"item": "2", "memory": "Runs daily.", "cited_excerpts": "", "cited_deposits_text": ""}]
    out = reread(rows, transport, "some-model")
    assert out["labels"] == {"1": "partial"} and out["unparsed"] == ["2"]
    assert out["reader"] == reader_name("some-model")
    assert "MEMORY: Lives in Lisbon." in seen[0] and "supported" in seen[0]
