"""Harness tests: the scorer must give known answers on control systems."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourced.adapters.controls import InjectedSystem, OracleSystem, VerbatimSystem  # noqa: E402
from sourced.agreement import cohen_kappa  # noqa: E402
from sourced.deposits import build_deposits, deposit_dicts  # noqa: E402
from sourced.judge import LexicalJudge, ModelJudge, date_mentions, quote_found  # noqa: E402
from sourced.runner import run  # noqa: E402
from sourced.score import correct, score_run  # noqa: E402
from sourced.tasks import derive_questions, question_dicts  # noqa: E402
from sourced.world import generate_world  # noqa: E402


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    out = tmp_path_factory.mktemp("life")
    w = generate_world(seed=3, days=28, n_facts=60, n_changes=8)
    deps = build_deposits(w)
    qs = derive_questions(w, deps)
    (out / "truth.json").write_text(json.dumps(w.to_dict()))
    (out / "deposits.json").write_text(json.dumps(deposit_dicts(deps)))
    (out / "questions.jsonl").write_text("".join(json.dumps(q) + "\n"
                                                 for q in question_dicts(qs)))
    return out, w.to_dict(), deposit_dicts(deps), question_dicts(qs)


def score(system, data):
    out, truth, deps, qs = data
    res = json.loads(json.dumps(run(system, out)))
    return score_run(truth, deps, qs, res, LexicalJudge(truth, deps))


def test_oracle_is_perfect(data):
    _, truth, deps, qs = data
    h = score(OracleSystem(truth, deps, qs), data)["headline"]
    assert h["invention_rate"] == 0.0
    assert h["excerpt_support_rate"] == 1.0
    assert h["fact_recall"] == 1.0
    assert h["qa_accuracy"] == 1.0
    assert h["invented_answers"] == 0.0


@pytest.mark.parametrize("rate", [0.05, 0.2, 0.4])
def test_injected_rate_is_recovered(data, rate):
    _, truth, deps, qs = data
    rep = score(InjectedSystem(truth, deps, qs, rate=rate), data)
    snap = rep["snapshots"][-1]
    n_good = len([f for f in truth["facts"]])  # all facts seen by the end
    expected = round(n_good * rate / (1 - rate)) / (n_good + round(n_good * rate / (1 - rate)))
    assert abs(snap["invention_rate"] - expected) < 0.01
    # injected memories carry lower confidence: the curve separates them
    assert snap["curve"]["recall_at_inv_1pct"] == 1.0


def test_verbatim_never_invents_but_answers_poorly(data):
    h = score(VerbatimSystem(), data)["headline"]
    assert h["invention_rate"] == 0.0
    assert h["qa_accuracy"] < 0.5


def test_abstention_cannot_be_dodged(data):
    """A system that abstains on everything scores exactly the abstention share."""
    _, truth, deps, qs = data

    class Mute(VerbatimSystem):
        def answer(self, question, asked_at):
            from sourced.adapters.base import Answer
            return Answer("No information", abstained=True)
    h = score(Mute(), data)["headline"]
    share = sum(q["answer_type"] == "abstain" for q in qs) / len(qs)
    assert abs(h["qa_accuracy"] - share) < 1e-3


def test_answer_matching():
    q = {"answer_type": "date", "gold": "2025-02-08", "tolerance_days": 0, "aliases": []}
    assert correct(q, {"text": "On 8 February 2025."})
    assert correct(q, {"text": "2025-02-08"})
    assert not correct(q, {"text": "9 February 2025"})
    d = {"answer_type": "duration_days", "gold": "5", "tolerance_days": 1, "aliases": []}
    assert correct(d, {"text": "six days"}) and not correct(d, {"text": "two weeks"})
    a = {"answer_type": "abstain", "gold": "", "tolerance_days": 0, "aliases": []}
    assert correct(a, {"text": "No information"})
    assert not correct(a, {"text": "Biscuit"})
    t = {"answer_type": "text", "gold": "Porto", "tolerance_days": 0, "aliases": []}
    assert not correct(t, {"text": "I don't know, maybe Porto"})  # hedge = abstention


def test_quote_found_tolerates_disfluency():
    src = "So, um, I- I accepted the, uh, data analyst job at Northwind Analytics."
    assert quote_found("I accepted the data analyst job at Northwind Analytics", src)
    assert not quote_found("I accepted the backend engineer job at Lumen Robotics", src)
    assert date_mentions("met on February 8, 2025 and 2025-03-01") == {"2025-02-08",
                                                                       "2025-03-01"}


def test_model_judge_with_stub_transport(data):
    _, truth, deps, _ = data
    reply = {"choices": [{"message": {"content": '{"support": "unsupported", '
                                                 '"citation_supports": false, "facts": []}'}}]}
    j = ModelJudge(truth, deps, "http://stub", "stub-model", transport=lambda body: reply)
    lab = j.label({"content": "Something invented.", "citations": []})
    assert lab["support"] == "unsupported" and j.name.startswith("model:stub-model")


def test_kappa():
    assert cohen_kappa([("a", "a"), ("b", "b")]) == 1.0
    assert cohen_kappa([("a", "b"), ("b", "a")]) < 0


def test_label_tool_is_blind_and_resumable(tmp_path):
    import csv
    from sourced.label import run as label_run
    f = tmp_path / "ann.csv"
    with open(f, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["item", "memory", "cited_excerpts", "cited_deposits_text",
                    "human_support (supported|partial|unsupported)", "human_note"])
        for i in range(3):
            w.writerow([i + 1, f"memory {i}", "", "", "", ""])
    (tmp_path / "ann.judge.json").write_text('{"1": "SECRET_LABEL"}')
    shown = []
    answers = iter(["s", "q"])
    label_run(f, inp=lambda _: next(answers), out=shown.append)
    assert "SECRET_LABEL" not in "".join(shown)
    answers = iter(["u", "x", "p"])  # resumes at item 2; "x" is ignored
    res = label_run(f, inp=lambda _: next(answers), out=shown.append)
    assert res == {"labelled": 3, "total": 3}
    labels = [r[4] for r in csv.reader(open(f))][1:]
    assert labels == ["supported", "unsupported", "partial"]


def test_run_reports_progress_per_night_and_question(data):
    out, truth, _, qs = data
    lines = []
    run(VerbatimSystem(), out, progress=lines.append, limit_questions=3)
    nights = [x for x in lines if x.startswith("night ")]
    asked = [x for x in lines if x.startswith("question ")]
    assert len(nights) == truth["days"] and nights[-1].startswith(f"night {truth['days']}/")
    assert asked == [a for a in asked if "min left" in a] and len(asked) == 3
    assert asked[-1].startswith("question 3/3")
