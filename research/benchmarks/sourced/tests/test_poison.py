"""Poison layer: false claims about the owner from sources with no authority."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourced.deposits import build_deposits, deposit_dicts  # noqa: E402
from sourced.judge import LexicalJudge  # noqa: E402
from sourced.score import poison_store  # noqa: E402
from sourced.tasks import derive_questions, question_dicts  # noqa: E402
from sourced.world import generate_world  # noqa: E402

KW = dict(days=182, n_facts=300, n_changes=40)


@pytest.mark.parametrize("seed", range(3))
def test_poison_layer_leaves_the_published_set_unchanged(seed):
    before = generate_world(seed=seed, **KW)
    full = generate_world(seed=seed, poison=True, **KW)
    assert full.facts == before.facts and full.people == before.people
    assert full.traps[:len(before.traps)] == before.traps
    bd, fd = deposit_dicts(build_deposits(before)), deposit_dicts(build_deposits(full))
    by_id = {d["id"]: d for d in fd}
    assert all(by_id[d["id"]] == d for d in bd)
    bq = question_dicts(derive_questions(before, build_deposits(before)))
    fq = question_dicts(derive_questions(full, build_deposits(full)))
    assert fq[:len(bq)] == bq


@pytest.mark.parametrize("seed", range(3))
def test_every_poison_claim_is_deposited_and_asked(seed):
    w = generate_world(seed=seed, poison=True, **KW)
    deps = build_deposits(w)
    poison = [t for t in w.traps if t.kind == "poison"]
    assert {t.channel for t in poison} == {"injection", "third_party", "repeated"}
    for t in poison:
        carrying = [d for d in deps if t.id in d.trap_ids]
        assert len(carrying) == len(t.days) and t.sentence in carrying[0].text
        # from a source with no authority over the owner: never the owner
        assert all(d.author != w.owner for d in carrying)
    asked = [q for q in derive_questions(w, deps) if q.category == "poison"]
    assert sorted(q.source for q in asked) == sorted(t.id for t in poison)
    assert all(q.answer_type == "abstain" for q in asked)


def test_poison_has_no_held_out_wordings_yet():
    w = generate_world(seed=1, poison=True, **KW)
    with pytest.raises(NotImplementedError):
        build_deposits(w, phrasing="test")


def test_judge_flags_the_claim_not_the_report_of_it():
    w = generate_world(seed=1, poison=True, **KW)
    deps = build_deposits(w)
    truth, dd = json.loads(json.dumps(w.to_dict())), deposit_dicts(deps)
    j = LexicalJudge(truth, dd)
    for t in (t for t in w.traps if t.kind == "poison"):
        assert t.id in j.label({"content": t.forbidden})["traps"]
        reported = f"A notice says that {t.forbidden[0].lower()}{t.forbidden[1:]}"
        if t.channel == "third_party":
            reported = f"A friend's message claims that {t.forbidden}"
        assert t.id not in j.label({"content": reported})["traps"]
    hits = [t.id for t in w.traps if t.kind == "poison"][:1]
    out = poison_store(truth, hits, "2099-01-01T00:00:00")
    assert out["poison_rate"] == round(1 / 3, 4)
    assert poison_store(json.loads(json.dumps(generate_world(seed=1, **KW).to_dict())),
                        [], "2099-01-01")["poison_rate"] is None
