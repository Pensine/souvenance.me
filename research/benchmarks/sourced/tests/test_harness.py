"""Harness tests: the scorer must give known answers on control systems."""

import json
import re
from datetime import date
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
    the = {"answer_type": "text", "gold": "the harbour footpath", "tolerance_days": 0, "aliases": []}
    assert correct(the, {"text": "Harbour footpath"})
    assert not correct(the, {"text": "the harbour"})


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


# --- attribution -----------------------------------------------------------

def test_oracle_has_no_attribution_error(data):
    _, truth, deps, qs = data
    rep = score(OracleSystem(truth, deps, qs), data)
    snap = rep["snapshots"][-1]
    assert rep["headline"]["attribution_error_rate"] == 0.0
    assert snap["attribution_measurable"] == snap["memories"]
    by_cat = rep["qa"]["by_category"]
    assert by_cat["identity"]["accuracy"] == 1.0 and by_cat["attribution_check"]["n"]


@pytest.mark.parametrize("rate", [0.1, 0.3])
def test_injected_misattribution_is_recovered(data, rate):
    """Only the declared subject is wrong: attribution moves, invention not.
    Recovered within 0.03 (a wrong subject can coincide with the subject of
    another fact sharing the value, which the lexical judge then accepts)."""
    _, truth, deps, qs = data
    snap = score(InjectedSystem(truth, deps, qs, rate=0.2, misattribution=rate),
                 data)["snapshots"][-1]
    n_good = len(truth["facts"])
    assert abs(snap["attribution_error_rate"] - round(n_good * rate) / n_good) <= 0.03
    clean = score(InjectedSystem(truth, deps, qs, rate=0.2), data)["snapshots"][-1]
    assert snap["invention_rate"] == clean["invention_rate"]


def test_no_subject_means_not_measurable_never_zero(data):
    snap = score(VerbatimSystem(), data)["snapshots"][-1]
    assert snap["attribution_error_rate"] is None
    assert snap["attribution_reason"] == "system does not declare memory subjects"


def test_lexical_judge_tells_the_subject(data):
    _, truth, deps, _ = data
    j = LexicalJudge(truth, deps)
    x = truth["identity"][0]
    person = next(p for p in truth["people"] if p["id"] == x["person"])
    owner = next(p for p in truth["people"] if p["id"] == truth["owner"])["name"]
    fact = next(f for f in truth["facts"] if f["id"] == x["role_fact"])
    trap = x["role_trap"]
    employer = fact["value"]["employer"]
    by_role = j.label({"content": f"{x['role'].capitalize()} works at {employer}.",
                       "subject": x["role"]})
    by_name = j.label({"content": f"{person['name']} works at {employer}.",
                       "subject": person["name"]})
    wrong = j.label({"content": f"{owner} works at {employer}.", "subject": owner})
    for lab in (by_role, by_name):
        assert trap not in lab["traps"] and lab["subject_ok"] is True
        assert {"fact_id": fact["id"], "status": "correct"} in lab["facts"]
    assert trap in wrong["traps"] and wrong["support"] == "unsupported"
    assert wrong["subject_ok"] is False and fact["id"] in wrong["stated"]
    assert j.label({"content": f"{person['name']} works at {employer}."})["subject_ok"] is None


# --- bounded dating --------------------------------------------------------

@pytest.fixture(scope="module")
def big(tmp_path_factory):
    """Enough bracketed facts (8) for rates to mean something."""
    out = tmp_path_factory.mktemp("big")
    w = generate_world(seed=5, days=120, n_facts=240, n_changes=20)
    deps = build_deposits(w)
    qs = derive_questions(w, deps)
    (out / "truth.json").write_text(json.dumps(w.to_dict()))
    (out / "deposits.json").write_text(json.dumps(deposit_dicts(deps)))
    (out / "questions.jsonl").write_text("".join(json.dumps(q) + "\n"
                                                 for q in question_dicts(qs)))
    return out, w.to_dict(), deposit_dicts(deps), question_dicts(qs)


def test_interval_answers_are_scored_in_code():
    from sourced.score import answer_dates, interval_verdict
    q = {"answer_type": "interval", "gold": "2025-02-05/2025-02-11", "tolerance_days": 0,
         "aliases": []}
    v = lambda text, **k: interval_verdict(q, {"text": text, **k})  # noqa: E731
    assert v("Between 5 February 2025 and 11 February 2025.") == "correct"
    assert v("between 6 and 9 February 2025") == "correct"           # inside: correct
    assert v("2025-02-05/2025-02-11") == "correct"
    assert v("On 8 February 2025.") == "invented_precision"
    assert v("between 1 February and 11 February 2025") == "wrong"   # wider than the evidence
    assert v("Sometime in February") == "wrong"
    assert v("No information") == "abstained"
    assert v("8 February 2025", abstained=True) == "abstained"
    assert answer_dates("between 28 January and 3 February 2025") == [
        date(2025, 1, 28), date(2025, 2, 3)]
    tolerant = {**q, "tolerance_days": 1}
    assert interval_verdict(tolerant, {"text": "between 4 and 12 February 2025"}) == "correct"


def test_oracle_never_invents_precision(big):
    _, truth, deps, qs = big
    rep = score(OracleSystem(truth, deps, qs), big)
    qa, snap = rep["qa"], rep["snapshots"][-1]
    assert qa["bounded_date"]["n"] == len(truth["dating"]) == 8
    assert qa["invented_precision_rate"] == 0.0 and qa["bounded_date"]["correct"] == 8
    assert rep["headline"]["invented_precision_rate"] == 0.0
    assert snap["store_dating"]["justified"] == 8 and snap["store_invented_precision_rate"] == 0.0
    assert rep["headline"]["invention_rate"] == 0.0 and rep["headline"]["fact_recall"] == 1.0


@pytest.mark.parametrize("rate", [0.25, 0.5])
def test_injected_imprecision_is_recovered(big, rate):
    _, truth, deps, qs = big
    rep = score(InjectedSystem(truth, deps, qs, rate=0.0, imprecision=rate), big)
    assert rep["qa"]["invented_precision_rate"] == rate
    assert rep["qa"]["bounded_date"]["correct"] == round(8 * (1 - rate))


def test_abstaining_on_a_date_is_not_invented_precision(big):
    _, truth, deps, qs = big

    class Shy(OracleSystem):
        def answer(self, question, asked_at):
            from sourced.adapters.base import Answer
            if "get the" in question:
                return Answer("No information", abstained=True)
            return super().answer(question, asked_at)
    qa = score(Shy(truth, deps, qs), big)["qa"]
    assert qa["invented_precision_rate"] == 0.0 and qa["bounded_date"]["abstained"] == 8
    assert qa["by_category"]["bounded_date"]["accuracy"] == 0.0


def test_store_dating_not_measurable_without_bounds(data):
    snap = score(VerbatimSystem(), data)["snapshots"][-1]
    assert snap["store_dating"] is None and snap["store_invented_precision_rate"] is None
    assert snap["store_dating_reason"] == "system exposes no event bounds"


def test_a_not_yet_deposit_does_not_state_the_fact(data):
    _, truth, deps, _ = data
    j = LexicalJudge(truth, deps)
    x = truth["dating"][0]
    f = next(f for f in truth["facts"] if f["id"] == x["fact"])
    who = next(p for p in truth["people"] if p["id"] == f["subject"])["name"].split()[0]
    item = f["value"]["item"]
    assert f["id"] in j.label({"content": f"{who} has the {item}."})["stated"]
    assert f["id"] not in j.label({"content": f"{who} has not got the {item} yet."})["stated"]


def test_an_event_date_recorded_in_a_field_states_the_date(data):
    _, truth, deps, _ = data
    j = LexicalJudge(truth, deps)
    ids = lambda m: {x["fact_id"] for x in j.label(m)["facts"]}  # noqa: E731
    undated = lambda f: re.sub(r" on \d{1,2} \w+ \d{4}", "", f["canonical"])  # noqa: E731
    f = next(f for f in truth["facts"] if f["kind"] == "event" and f["predicate"] != "news"
             and f["id"] in ids({"content": f"{undated(f)} on {f['valid_from']}"}))
    bare = {"content": undated(f)}
    assert f["id"] not in ids(bare)
    assert f["id"] in ids({**bare, "valid_from": f["valid_from"]})
    assert f["id"] in ids({**bare, "event_earliest": f["valid_from"],
                           "event_latest": f["valid_from"]})
    # a range states no date, a wrong date is no date
    assert f["id"] not in ids({**bare, "event_earliest": "2000-01-01",
                               "event_latest": f["valid_from"]})
    assert f["id"] not in ids({**bare, "valid_from": "2000-01-01"})


# --- identity coverage -----------------------------------------------------

def test_oracle_links_every_identity_and_no_decoy(data):
    _, truth, deps, qs = data
    rep = score(OracleSystem(truth, deps, qs), data)
    snap = rep["snapshots"][-1]
    assert rep["headline"]["alias_recall"] == 1.0 and rep["headline"]["alias_precision"] == 1.0
    d = snap["alias_detail"]
    assert d["recall_by_kind"] == {"written_together": 1.0, "converging": 1.0}
    assert d["true_identities"] == len(truth["identity"]) + 1 and not d["false_links"]
    assert all(s["alias_recall"] == 1.0 for s in rep["snapshots"] if s["alias_recall"] is not None)


@pytest.mark.parametrize("k", [1, 3])
def test_injected_false_links_are_recovered(data, k):
    _, truth, deps, qs = data
    snap = score(InjectedSystem(truth, deps, qs, rate=0.0, false_links=k), data)["snapshots"][-1]
    n = snap["alias_detail"]["true_identities"]
    assert snap["alias_precision"] == round(n / (n + k), 4) and snap["alias_recall"] == 1.0
    assert len(snap["alias_detail"]["false_links"]) == k


def test_no_links_exposed_means_null_never_zero(data):
    snap = score(VerbatimSystem(), data)["snapshots"][-1]
    assert snap["alias_recall"] is None and snap["alias_precision"] is None
    assert snap["alias_reason"] == "system does not expose identity links"


def test_a_photo_position_is_read_in_code_like_exif(data):
    from sourced.adapters.pensine import photo_position
    from sourced.runner import view
    out, truth, deps, _ = data
    people = {p["id"]: p["name"] for p in truth["people"]}
    photos = [d for d in deps if d["kind"] == "photo"]
    assert photos
    for d in photos:
        v = view(d, people, out, "T")
        assert photo_position(v) == {"lat": d["meta"]["lat"], "lon": d["meta"]["lon"],
                                     "source": "exif"}
    note = next(d for d in deps if d["kind"] == "note")
    assert photo_position(view(note, people, out, "T")) is None


def test_graphiti_adapter_reads_its_model_replies_and_needs_no_graphiti_to_import():
    import pytest as _pytest
    from sourced.adapters.graphiti import parse_json
    assert parse_json('Sure.\n```json\n{"a": [1, {"b": 2}]}\n```') == {"a": [1, {"b": 2}]}
    with _pytest.raises(ValueError):
        parse_json("no json here")
