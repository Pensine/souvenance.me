"""Generator tests: determinism, validity intervals, complete labelling."""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourced.deposits import build_deposits, deposit_dicts  # noqa: E402
from sourced.tasks import derive_questions, question_dicts  # noqa: E402
from sourced.world import count_changes, generate_world  # noqa: E402

SMALL = dict(days=14, n_facts=30, n_changes=4)
FULL = dict(days=182, n_facts=300, n_changes=40)


def dump(seed, **kw):
    w = generate_world(seed=seed, **kw)
    d = build_deposits(w)
    q = derive_questions(w, d)
    return json.dumps([w.to_dict(), deposit_dicts(d), question_dicts(q)], sort_keys=True)


@pytest.mark.parametrize("kw", [SMALL, FULL])
def test_same_seed_same_bytes(kw):
    assert dump(11, **kw) == dump(11, **kw)


def test_different_seed_different_life():
    assert dump(1, **SMALL) != dump(2, **SMALL)


@pytest.mark.parametrize("seed", range(5))
def test_targets_reached(seed):
    """The targets size the base life; the identity layer adds its own few
    facts on top (background states and events: no change)."""
    w = generate_world(seed=seed, **FULL)
    assert len([f for f in w.facts if not f.layer]) == 300
    assert 36 <= count_changes(w.facts, w.start) <= 44
    s = generate_world(seed=seed, **SMALL)
    assert len([f for f in s.facts if not f.layer]) == 30
    assert count_changes(s.facts, s.start) >= 3


@pytest.mark.parametrize("seed", range(5))
def test_validity_intervals(seed):
    w = generate_world(seed=seed, **FULL)
    end = (date.fromisoformat(w.start) + timedelta(days=w.days)).isoformat()
    by_id = {f.id: f for f in w.facts}
    slots = {}
    for f in w.facts:
        if f.valid_to:
            assert f.valid_from < f.valid_to, f
            assert f.valid_to <= end
        if f.kind == "event":
            assert w.start <= f.valid_from < end
            assert f.valid_to is None
        if f.supersedes:
            prev = by_id[f.supersedes]
            assert prev.slot == f.slot
            assert prev.valid_to == f.valid_from, (prev, f)  # no gap, no overlap
            assert w.start <= f.valid_from < end
        slots.setdefault(f.slot, []).append(f)
    for slot, versions in slots.items():
        states = [v for v in versions if v.kind == "state"]
        # at most one version of a state slot is open at the end
        assert sum(1 for v in states if v.valid_to is None) <= 1, slot


@pytest.mark.parametrize("seed", range(5))
def test_every_fact_labelled_and_spans_exact(seed):
    w = generate_world(seed=seed, **FULL)
    deps = build_deposits(w)
    labelled = {f for d in deps for f in d.fact_ids}
    assert labelled == {f.id for f in w.facts}
    facts = {f.id: f for f in w.facts}
    for d in deps:
        assert set(d.fact_ids) == {s.fact_id for s in d.spans}
        for s in d.spans:
            assert 0 <= s.start < s.end <= len(d.text)
            excerpt = d.text[s.start:s.end]
            assert excerpt.strip() == excerpt and excerpt
        # a deposit never carries a fact before it is true, except announced
        # futures (offer letter, "I start on …"), labelled as such
        for s in d.spans:
            f = facts[s.fact_id]
            if s.role != "future" and f.kind == "event":
                assert f.valid_from <= d.created_at[:10]


@pytest.mark.parametrize("seed", range(3))
def test_value_appears_in_its_span(seed):
    """The key value of a fact is literally present in at least one of its
    spans (photos excepted: they carry coordinates, not a city name)."""
    w = generate_world(seed=seed, **FULL)
    deps = build_deposits(w)
    spans = {}
    for d in deps:
        for s in d.spans:
            spans.setdefault(s.fact_id, []).append(d.text[s.start:s.end].lower())
    for f in w.facts:
        if f.predicate in ("visited", "appointment", "birthday"):
            continue
        key = {"lives_at": f.value.get("street"), "works_at": f.value.get("employer"),
               "pays_rent": str(f.value.get("amount")), "health": f.value.get("condition"),
               "race": f.value.get("time"), "pet": f.value.get("name"),
               "lives_in": f.value.get("city"), "job": f.value.get("title")}.get(f.predicate)
        if key:
            assert any(key.lower() in s.replace("um, ", "").replace("uh, ", "")
                       or all(t in s for t in key.lower().split()) for s in spans[f.id]), \
                (f.canonical, spans[f.id])


def test_traps_placed_and_photos_trapped():
    w = generate_world(seed=4, **FULL)
    deps = build_deposits(w)
    placed = {t for d in deps for t in d.trap_ids}
    assert placed == {t.id for t in w.traps}
    for d in deps:
        if d.kind == "photo":
            assert d.trap_ids, "every neutral photo is a content trap"
            assert "GPS" in d.text and d.meta["lat"]


def test_no_labels_leak_into_views(tmp_path):
    from sourced.runner import view
    w = generate_world(seed=2, **SMALL)
    d = deposit_dicts(build_deposits(w))[0]
    v = view(d, {p.id: p.name for p in w.people}, tmp_path, "T")
    # position: a photo's device GPS (EXIF), the same metadata its text carries
    assert set(vars(v)) == {"id", "kind", "created_at", "author", "recipient", "text", "path",
                            "position"}


@pytest.mark.parametrize("seed", range(5))
def test_questions_derived_and_abstention_share(seed):
    w = generate_world(seed=seed, **FULL)
    deps = build_deposits(w)
    qs = derive_questions(w, deps)
    cats = {q.category for q in qs}
    assert {"present", "past", "when", "duration", "abstention"} <= cats
    share = sum(q.category == "abstention" for q in qs) / len(qs)
    assert 0.12 <= share <= 0.3
    for q in qs:
        if q.answer_type != "abstain":
            assert q.gold and q.fact_ids and q.deposit_ids
        else:
            assert not q.gold and q.source


def test_photo_exif_roundtrip(tmp_path):
    pytest.importorskip("PIL")
    from sourced.media import read_photo_exif, render_photo
    w = generate_world(seed=5, **SMALL)
    photo = next(d for d in build_deposits(w) if d.kind == "photo")
    p = tmp_path / "x.jpg"
    render_photo(photo, p, 5)
    ex = read_photo_exif(p)
    assert abs(ex["lat"] - photo.meta["lat"]) < 1e-4
    assert abs(ex["lon"] - photo.meta["lon"]) < 1e-4
    assert ex["datetime"].replace(":", "-", 2).replace(" ", "T") == photo.created_at


def test_pdf_is_valid_and_text_extractable(tmp_path):
    from sourced.media import render_pdf
    p = tmp_path / "x.pdf"
    render_pdf("LEASE (test)\nPremises: 1 Mill Road, Ghent", p)
    raw = p.read_bytes()
    assert raw.startswith(b"%PDF-1.4") and raw.rstrip().endswith(b"%%EOF")
    assert b"Premises: 1 Mill Road, Ghent" in raw and b"LEASE \\(test\\)" in raw


@pytest.mark.parametrize("seed", range(5))
def test_question_texts_are_unique(seed):
    w = generate_world(seed=seed, **FULL)
    qs = derive_questions(w, build_deposits(w))
    assert len({q.question for q in qs}) == len(qs)


# The word a deposit would need to answer each unstated slot. An abstention
# question whose answer sits in a deposit scores a correct answer as invented
# (the landlord question did: every lease names the landlord).
UNSTATED_CUES = {"car": ["drive", " car"], "blood type": ["blood"],
                 "university": ["universit"], "landlord": ["landlord"],
                 "shoe size": ["shoe size"], "pet": ["pet "],
                 "favourite band": ["band"], "school": ["school"],
                 "middle name": ["middle name"]}


@pytest.mark.parametrize("kw", [SMALL, FULL])
@pytest.mark.parametrize("seed", range(3))
def test_unstated_questions_are_unanswerable(seed, kw):
    w = generate_world(seed=seed, **kw)
    text = " ".join(d.text for d in build_deposits(w)).lower()
    for u in w.unstated:
        q = u["question"].lower()
        slot = next((k for k in UNSTATED_CUES if k in q), None)
        assert slot, f"no cue for unstated question: {u['question']}"
        for cue in UNSTATED_CUES[slot]:
            assert cue not in text, f"{u['question']!r} is answered by a deposit ({cue!r})"


@pytest.mark.parametrize("seed", range(5))
def test_voices_are_the_pinned_public_domain_set(seed):
    """Every speaker uses a slot both TTS engines pin by checksum (a reference
    clip for Chatterbox, a voice for Piper), and the owner's voice is never
    lent to anyone else."""
    from sourced.tts_worker import PIPER_VOICES, REFS

    VOICES = set(REFS) & set(PIPER_VOICES)

    w = generate_world(seed=seed, **FULL)
    owner = w.person(w.owner).voice
    assert all(p.voice in VOICES for p in w.people)
    assert all(p.voice != owner for p in w.people if p.id != w.owner)
    voiced = [d for d in build_deposits(w) if d.kind in ("voice", "voice_in")]
    assert voiced and all(d.meta["voice"] in VOICES for d in voiced)


# --- identity layer --------------------------------------------------------

@pytest.mark.parametrize("kw", [SMALL, FULL])
def test_identity_layer_leaves_the_base_life_unchanged(kw):
    """Own random streams: the base facts, traps, deposits (ids, texts, voice
    transcripts) and questions are the same with or without the layer."""
    base = generate_world(seed=1, identity=False, dating=False, coverage=False, **kw)
    full = generate_world(seed=1, dating=False, coverage=False, **kw)
    n = len(base.facts)
    assert [f for f in full.facts if not f.layer] == base.facts
    assert full.traps[:len(base.traps)] == base.traps
    bd, fd = deposit_dicts(build_deposits(base)), deposit_dicts(build_deposits(full))
    by_id = {d["id"]: d for d in fd}
    assert all(by_id[d["id"]] == d for d in bd)
    assert [d["created_at"] for d in fd] == sorted(d["created_at"] for d in fd)
    bq = question_dicts(derive_questions(base, build_deposits(base)))
    fq = question_dicts(derive_questions(full, build_deposits(full)))
    assert fq[:len(bq)] == bq
    assert all(f.layer == "identity" for f in full.facts[n:])


@pytest.mark.parametrize("kw", [SMALL, FULL])
@pytest.mark.parametrize("seed", range(3))
def test_alias_is_provable_in_one_place(seed, kw):
    """Role and name together only in the alias deposit; the role-only fact
    never names the person, the name-only fact never gives the role. No
    identity deposit is a voice memo."""
    w = generate_world(seed=seed, **kw)
    deps = build_deposits(w)
    traps = {t.id: t for t in w.traps}
    assert w.identity
    roles = [p.role for p in w.people if p.role]
    for x in w.identity:
        p = w.person(x["person"])
        first, role = p.name.split()[0], x["role"]
        assert roles.count(role) == 1                    # a role designates one person
        alias = [d for d in deps if any(a[0] == p.id for a in d.meta.get("alias_spans", []))]
        assert len(alias) == 1 and alias[0].kind in ("note", "message")
        a = alias[0].meta["alias_spans"][0]
        proof = alias[0].text[a[1]:a[2]]
        assert first in proof and role in proof
        role_dep = next(d for d in deps if x["role_trap"] in d.trap_ids)
        name_dep = next(d for d in deps if x["name_trap"] in d.trap_ids)
        assert role in role_dep.text and first not in role_dep.text
        assert first in name_dep.text and role not in name_dep.text
        for d, fid in ((role_dep, x["role_fact"]), (name_dep, x["name_fact"])):
            assert d.kind == "note" and d.fact_ids == [fid]
            s = d.spans[0]
            assert d.text[s.start:s.end] == traps[d.trap_ids[0]].sentence
        t = traps[x["role_trap"]]
        assert t.kind == "attribution" and t.subject == p.id
        assert w.owner in t.misattributed_to and x["contrast"] in t.misattributed_to


@pytest.mark.parametrize("seed", range(3))
def test_identity_questions_need_the_alias(seed):
    w = generate_world(seed=seed, **FULL)
    deps = build_deposits(w)
    qs = derive_questions(w, deps)
    alias = {d.id for d in deps if d.meta.get("alias_spans")}
    ident = [q for q in qs if q.category == "identity"]
    checks = [q for q in qs if q.category == "attribution_check"]
    assert len(ident) == 2 * len(w.identity) and checks
    for q in ident:
        assert q.gold and alias & set(q.deposit_ids)
    for q in checks:
        assert q.distractors and q.gold not in q.distractors
        assert (q.answer_type == "abstain") == (not q.gold)


# --- dating layer ----------------------------------------------------------

@pytest.mark.parametrize("kw", [SMALL, FULL])
def test_dating_layer_leaves_everything_before_it_unchanged(kw):
    """Own random streams, numbered last: base and identity facts, traps,
    deposits (ids, texts) and questions are the same with or without it."""
    before = generate_world(seed=1, dating=False, coverage=False, **kw)
    full = generate_world(seed=1, coverage=False, **kw)
    assert full.facts[:len(before.facts)] == before.facts and full.traps == before.traps
    assert all(f.layer == "dating" for f in full.facts[len(before.facts):])
    bd, fd = deposit_dicts(build_deposits(before)), deposit_dicts(build_deposits(full))
    by_id = {d["id"]: d for d in fd}
    assert all(by_id[d["id"]] == d for d in bd)
    assert [d["created_at"] for d in fd] == sorted(d["created_at"] for d in fd)
    bq = question_dicts(derive_questions(before, build_deposits(before)))
    fq = question_dicts(derive_questions(full, build_deposits(full)))
    assert fq[:len(bq)] == bq and {q["category"] for q in fq[len(bq):]} == {"bounded_date"}


@pytest.mark.parametrize("kw", [SMALL, FULL])
@pytest.mark.parametrize("seed", range(3))
def test_a_bracketed_date_is_written_nowhere(seed, kw):
    """The "not yet" deposit precedes the true day, the "already" deposit
    follows it, both are text, and no deposit states the true day."""
    w = generate_world(seed=seed, **kw)
    deps = build_deposits(w)
    facts = {f.id: f for f in w.facts}
    assert len(w.dating) >= 2
    for x in w.dating:
        f = facts[x["fact"]]
        assert x["not_yet_day"] < f.valid_from <= x["already_day"]
        carrying = [d for d in deps if f.id in d.fact_ids]
        roles = sorted(s.role for d in carrying for s in d.spans if s.fact_id == f.id)
        assert roles == ["already", "not_yet"]
        assert all(d.kind in ("note", "message") for d in carrying)
        for d in carrying:
            s = next(s for s in d.spans if s.fact_id == f.id)
            assert d.created_at[:10] == (x["not_yet_day"] if s.role == "not_yet"
                                         else x["already_day"])
            assert f.value["item"] in d.text[s.start:s.end]
        true = date.fromisoformat(f.valid_from)
        for form in (f.valid_from, f"{true.day} {true.strftime('%B')}"):
            assert not any(form in d.text for d in carrying)


@pytest.mark.parametrize("seed", range(3))
def test_bounded_date_questions_carry_the_interval(seed):
    w = generate_world(seed=seed, **FULL)
    deps = build_deposits(w)
    qs = [q for q in derive_questions(w, deps) if q.category == "bounded_date"]
    assert len(qs) == len(w.dating)
    for q, x in zip(sorted(qs, key=lambda q: q.fact_ids[0]),
                    sorted(w.dating, key=lambda x: x["fact"])):
        assert q.answer_type == "interval"
        assert q.gold == f"{x['not_yet_day']}/{x['already_day']}"
        assert len(q.deposit_ids) == 2


# --- coverage layer --------------------------------------------------------

@pytest.mark.parametrize("kw", [SMALL, FULL])
def test_coverage_layer_leaves_everything_before_it_unchanged(kw):
    before = generate_world(seed=1, coverage=False, **kw)
    full = generate_world(seed=1, **kw)
    assert full.facts[:len(before.facts)] == before.facts
    assert full.people[:len(before.people)] == before.people
    bd, fd = deposit_dicts(build_deposits(before)), deposit_dicts(build_deposits(full))
    by_id = {d["id"]: d for d in fd}
    assert all(by_id[d["id"]] == d for d in bd)
    assert question_dicts(derive_questions(before, build_deposits(before))) == \
        question_dicts(derive_questions(full, build_deposits(full)))


@pytest.mark.parametrize("kw", [SMALL, FULL])
@pytest.mark.parametrize("seed", range(3))
def test_coverage_role_and_name_are_never_written_together(seed, kw):
    """Each attribute deposit names the role or the name, never both; only
    the `together` decoy's lunch names both, as two people. The converging
    pair shares two specific attributes, the decoys one specific at most."""
    w = generate_world(seed=seed, **kw)
    deps = build_deposits(w)
    facts = {f.id: f for f in w.facts}
    assert [x["case"] for x in w.coverage] == ["converging", "one_attribute", "generic",
                                               "together"]
    for x in w.coverage:
        role, name = x["role"], w.person(x["name_person"]).name.split()[0]
        both = [d for d in deps if role in d.text.lower() and name in d.text]
        if x["case"] == "together":
            assert len(both) == 1 and f"{role} and {name}" in both[0].text
        else:
            assert not both
        assert all(d.kind == "note" for d in deps
                   if any(m["fact"] in d.fact_ids for m in x["mentions"]))
        shared = {(facts[m["fact"]].predicate, json.dumps(facts[m["fact"]].value))
                  for m in x["mentions"] if m["by_role"]} & \
                 {(facts[m["fact"]].predicate, json.dumps(facts[m["fact"]].value))
                  for m in x["mentions"] if not m["by_role"]}
        specific = [s for s in shared if s[0] != "works_from"]
        assert len(specific) == {"converging": 2, "one_attribute": 1, "generic": 1,
                                 "together": 2}[x["case"]]
        assert x["same"] == (x["case"] == "converging")
