"""Second development phrasing (dev2): same skeleton as dev, other words.

dev and test must not move by a byte (pinned hashes below, taken before
dev2 existed); dev2 must keep every ground-truth guarantee of dev: exact
spans, values stated, dating negations, hedged traps, alias only where dev
has it, never-stated slots never stated. No assertion here prints a test
wording: comparisons with the held-out set are counts only.
"""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sourced import phrasing_dev2 as P2  # noqa: E402
from sourced.deposits import FILLER, PHRASINGS, build_deposits, deposit_dicts  # noqa: E402
from sourced.judge import NOT_YET, STOP, LexicalJudge, tokens  # noqa: E402
from sourced.tasks import derive_questions, evidence_index, question_dicts  # noqa: E402
from sourced.world import FIRST_NAMES, generate_world  # noqa: E402

from test_generator import FULL, SMALL, UNSTATED_CUES  # noqa: E402

HEDGES = {"if", "maybe", "might", "thinking", "considering", "not", "didn't", "apparently",
          "said", "rumour", "rumor", "plans", "planning", "hopes"}  # judge.trap_hits
SEEDS = range(1, 9)

# sha256 of json.dumps([truth, deposits, questions], sort_keys=True), SMALL
# size, computed on the commit before dev2 was added
PINNED = {(1, "dev"): "f56275f7dad8649cbaba77685223a74b0d004cd366dad73e913485d72f16e94b",
          (5, "dev"): "e3ab64158910bbda7c2e6db9924c17d87defbb72234822b72d06e484a52be20c",
          (3, "test"): "454e70b80e990e2e97ac975a26079603e25fb410c232cfd0ae1fdb40d4c0cbdb",
          (6, "test"): "0163f6b576b043fea1aca31519f9b9be4c5536db316d08cc286611329822d31b"}


def build(seed, phrasing, **kw):
    from sourced import deposits
    if phrasing == "test" and isinstance(deposits.P, deposits._Private):
        pytest.skip("the held-out wordings are private")
    w = generate_world(seed=seed, **kw)
    return w, build_deposits(w, phrasing=phrasing)


def dump(seed, phrasing, **kw) -> str:
    w, d = build(seed, phrasing, **kw)
    return json.dumps([w.to_dict(), deposit_dicts(d), question_dicts(derive_questions(w, d))],
                      sort_keys=True)


def skeleton(d: dict) -> tuple:
    return (d["id"], d["kind"], d["created_at"], d["author"], d["recipient"], d["fact_ids"],
            d["trap_ids"], [(s["fact_id"], s["role"]) for s in d["spans"]], d["file"],
            sorted(d["meta"]), [t[0] for t in d["meta"].get("trap_spans", [])],
            [a[0] for a in d["meta"].get("alias_spans", [])], d["meta"].get("together"))


@pytest.mark.parametrize("seed,phrasing", sorted(PINNED))
def test_dev_and_test_unchanged_byte_for_byte(seed, phrasing):
    assert hashlib.sha256(dump(seed, phrasing, **SMALL).encode()).hexdigest() == \
        PINNED[(seed, phrasing)]


def test_phrasing_names():
    assert PHRASINGS == ("dev", "test", "dev2") and P2.PHRASINGS == PHRASINGS
    with pytest.raises(ValueError):
        build_deposits(generate_world(seed=1, **SMALL), phrasing="dev3")


@pytest.mark.parametrize("kw", [SMALL, FULL])
@pytest.mark.parametrize("seed", [1, 6])
def test_dev2_is_deterministic(seed, kw):
    assert dump(seed, "dev2", **kw) == dump(seed, "dev2", **kw)


@pytest.mark.parametrize("seed", SEEDS)
def test_dev2_same_skeleton_as_dev_other_words(seed):
    for kw in (SMALL, FULL) if seed <= 2 else (SMALL,):
        wd, dd = build(seed, "dev", **kw)
        w2, d2 = build(seed, "dev2", **kw)
        assert json.dumps(wd.to_dict()) == json.dumps(w2.to_dict())
        a, b = deposit_dicts(dd), deposit_dicts(d2)
        assert [skeleton(x) for x in a] == [skeleton(x) for x in b]
        assert sum(x["text"] == y["text"] for x, y in zip(a, b)) == 0
        assert question_dicts(derive_questions(wd, dd)) == question_dicts(derive_questions(w2, d2))


@pytest.mark.parametrize("seed", [1, 3, 6])
def test_dev2_is_not_the_held_out_wording(seed):
    """Counts only: no held-out text is ever shown."""
    _, dt = build(seed, "test", **SMALL)
    _, d2 = build(seed, "dev2", **SMALL)
    same = sum(x.text == y.text for x, y in zip(dt, d2))
    assert same == 0


@pytest.mark.parametrize("seed", SEEDS)
def test_dev2_spans_exact_and_values_stated(seed):
    for kw in (SMALL, FULL) if seed <= 3 else (SMALL,):
        w, deps = build(seed, "dev2", **kw)
        _, dev = build(seed, "dev", **kw)
        facts = {f.id: f for f in w.facts}
        assert {f for d in deps for f in d.fact_ids} == set(facts)
        for d in deps:
            assert set(d.fact_ids) == {s.fact_id for s in d.spans}
            for s in d.spans:
                ex = d.text[s.start:s.end]
                assert 0 <= s.start < s.end <= len(d.text) and ex and ex.strip() == ex
            for _, a, b in d.meta.get("trap_spans", []) + d.meta.get("alias_spans", []):
                assert d.text[a:b] and d.text[a:b].strip() == d.text[a:b]
        for fid, items in evidence_index(deps).items():
            for e in items:
                d = next(x for x in deps if x.id == e["deposit"])
                assert d.text[e["start"]:e["end"]] == e["excerpt"]

        def matchable(ds) -> set[str]:
            out = set()
            for d in ds:
                for s in d.spans:
                    f = facts[s.fact_id]
                    key = [k for k in tokens(f.answer) if k not in STOP] or tokens(f.answer)
                    mt = set(tokens(d.text[s.start:s.end]))
                    if set(key) <= mt and not (s.role == "not_yet" or
                                               (f.layer == "dating" and mt & NOT_YET)):
                        out.add(f.id)
            return out

        assert matchable(dev) <= matchable(deps)


@pytest.mark.parametrize("seed", SEEDS)
def test_dev2_dates_kept(seed):
    """A sentence dated by the dev wording keeps the same day: a relative
    word of the same day, or the same absolute date. Written deposits only:
    in a voice transcript a hesitation may fall inside the date."""
    w, deps = build(seed, "dev2", **SMALL)
    _, dev = build(seed, "dev", **SMALL)
    same_day = {"today": ("today", "this morning"), "yesterday": ("yesterday", "last night")}
    for a, b in zip(dev, deps):
        if a.kind in ("voice", "voice_in"):
            continue
        for sa, sb in zip(a.spans, b.spans):
            ea, eb = a.text[sa.start:sa.end].lower(), b.text[sb.start:sb.end].lower()
            for word, forms in same_day.items():
                if re.search(rf"\b{word}\b", ea):
                    assert any(x in eb for x in forms), (ea, eb)
            for day in re.findall(r"\b(\d{1,2}) (january|february|march|april|may|june|july|"
                                  r"august|september|october|november|december) (\d{4})", ea):
                d, m, y = day
                assert (f"{d} {m} {y}" in eb or f"{m} {d}, {y}" in eb
                        or re.search(rf"the {d}(st|nd|rd|th) of {m} {y}", eb)), (ea, eb)


@pytest.mark.parametrize("kw", [SMALL, FULL])
@pytest.mark.parametrize("seed", [1, 2, 6, 7])
def test_dev2_dating_bounds(seed, kw):
    w, deps = build(seed, "dev2", **kw)
    judge = LexicalJudge(w.to_dict(), deposit_dicts(deps))
    facts = {f.id: f for f in w.facts}
    roles = {"not_yet": 0, "already": 0}
    for d in deps:
        for s in d.spans:
            if s.role in roles:
                f, ex = facts[s.fact_id], d.text[s.start:s.end]
                assert f.value["item"] in ex
                assert (judge.value_matches(f.__dict__, ex) is None) == (s.role == "not_yet")
                assert not re.search(r"\d", ex)  # no day number, true or not
                assert f.valid_from not in d.text
                roles[s.role] += 1
    assert roles["not_yet"] == roles["already"] == len(w.dating)


@pytest.mark.parametrize("kw", [SMALL, FULL])
@pytest.mark.parametrize("seed", [1, 2, 6, 7])
def test_dev2_traps_stay_traps(seed, kw):
    w, deps = build(seed, "dev2", **kw)
    judge = LexicalJudge(w.to_dict(), deposit_dicts(deps))
    traps = {t.id: t for t in w.traps}
    for d in deps:
        for tid, a, b in d.meta.get("trap_spans", []):
            text = d.text[a:b]
            if traps[tid].kind != "attribution":
                assert HEDGES & set(tokens(text)), text
                assert text.lower() != traps[tid].sentence.lower()
                if d.kind != "voice":
                    assert text.count(". ") == 0 and text.endswith("."), text
            assert tid not in judge.trap_hits(text, []), text


@pytest.mark.parametrize("kw", [SMALL, FULL])
@pytest.mark.parametrize("seed", [1, 2, 6, 7])
def test_dev2_unstated_questions_stay_unanswerable(seed, kw):
    w, deps = build(seed, "dev2", **kw)
    text = " ".join(d.text for d in deps).lower()
    for u in w.unstated:
        slot = next(k for k in UNSTATED_CUES if k in u["question"].lower())
        for cue in UNSTATED_CUES[slot]:
            assert cue not in text, (u["question"], cue)
    # every cue, even for slots this life does not ask about
    for cues in UNSTATED_CUES.values():
        for cue in cues:
            if cue != "landlord":  # leases may name one; dev2 leases say lessor/agent
                assert cue not in text, cue


@pytest.mark.parametrize("kw", [SMALL, FULL])
@pytest.mark.parametrize("seed", [1, 2, 6, 7])
def test_dev2_alias_only_where_dev_has_it(seed, kw):
    """Roles may come without "my" in dev2: the role word is what counts."""
    w, deps = build(seed, "dev2", **kw)
    for x in w.identity:
        p = w.person(x["person"])
        first, core = p.name.split()[0], x["role"].removeprefix("my ")
        alias = [d for d in deps if any(a[0] == p.id for a in d.meta.get("alias_spans", []))]
        assert len(alias) == 1 and alias[0].kind in ("note", "message")
        a = alias[0].meta["alias_spans"][0]
        proof = alias[0].text[a[1]:a[2]]
        assert first in proof and core in proof and proof != x["alias_sentence"]
        role_dep = next(d for d in deps if x["role_trap"] in d.trap_ids)
        name_dep = next(d for d in deps if x["name_trap"] in d.trap_ids)
        assert core in role_dep.text and first not in role_dep.text
        assert w.person(x["contrast"]).name.split()[0] in role_dep.text
        assert first in name_dep.text and core not in name_dep.text
        for d, fid in ((role_dep, x["role_fact"]), (name_dep, x["name_fact"])):
            assert d.kind == "note" and d.fact_ids == [fid]
    for x in w.coverage:
        core, name = x["role"].removeprefix("my "), w.person(x["name_person"]).name.split()[0]
        both = [d for d in deps if core in d.text.lower() and name in d.text]
        assert len(both) == (1 if x["case"] == "together" else 0)
        for m in x["mentions"]:
            d = next(d for d in deps if m["fact"] in d.fact_ids and d.created_at[:10] == m["day"])
            assert d.kind == "note"
            assert (core in d.text.lower()) == m["by_role"]
            assert (name in d.text) == (not m["by_role"])


def test_dev2_fixed_lines_name_nobody_and_differ_from_dev():
    lines = P2.FILLER_DEV2 + P2.GREETINGS_DEV2 + P2.SIGNOFFS_DEV2
    relations = ("sister", "brother", "friend", "colleague", "cousin", "neighbour",
                 "manager", "partner", "aunt", "uncle", "godfather", "flatmate", "landlady",
                 "teacher")
    for s in lines:
        assert not any(n in s for n in FIRST_NAMES), s
        assert not any(r in s.lower() for r in relations), s
    assert not set(P2.FILLER_DEV2) & set(FILLER)
    assert P2.FILLER_TEST is P2.FILLER_DEV2  # the names deposits.py reads


def test_cli_accepts_dev2(tmp_path):
    subprocess.run([sys.executable, "-m", "sourced", "generate", "--out", str(tmp_path),
                    "--seed", "1", "--days", "14", "--facts", "30", "--changes", "4",
                    "--text-only", "--phrasing", "dev2"], cwd=ROOT, check=True,
                   capture_output=True)
    params = json.loads((tmp_path / "manifest.json").read_text())["params"]
    assert params["phrasing"] == "dev2"


def test_dev2_regenerates_the_committed_sample_byte_for_byte(tmp_path):
    subprocess.run([sys.executable, "-m", "sourced", "generate", "--out", str(tmp_path),
                    "--seed", "6", "--days", "14", "--facts", "30", "--changes", "4",
                    "--text-only", "--phrasing", "dev2"], cwd=ROOT, check=True,
                   capture_output=True)
    for f in ("truth.json", "deposits.json", "questions.jsonl", "evidence.json",
              "manifest.json"):
        assert hashlib.sha256((tmp_path / f).read_bytes()).hexdigest() == \
            hashlib.sha256((ROOT / "sample-dev2" / f).read_bytes()).hexdigest(), f
