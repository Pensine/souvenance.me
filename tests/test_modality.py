"""The right word in the wrong mood: conditional, future, negation... cited as facts."""

import json
from pathlib import Path

from pensine import evidence, integrity, modality

CASES = json.loads((Path(__file__).parent / "fixtures" / "modality_cases.json")
                   .read_text(encoding="utf-8"))


def test_cas_francais_et_anglais():
    for c in CASES:
        got = modality.mismatches(c["memoire"], [c["extrait"]])
        assert bool(got) == c["defaut"], (c, got)


def test_categories():
    m = modality.mismatches
    assert m("Kofi learned to sail.", ["Maybe I'll learn to sail this summer."]) \
        == ["futur", "hypothese"]
    assert m("Kofi signed up for a marathon.", ["I did not sign up for the marathon."]) \
        == ["negation"]
    assert m("Kofi's bike was stolen.", ["Hollis said their bike got stolen."]) == ["oui_dire"]
    assert m("Kofi has a dog.", ["I keep thinking about adopting a dog."]) == ["souhait"]
    assert m("Camille a signé.", ["Est-ce que je signe ?"]) == ["question"]
    # the marker must bear on what the memory asserts
    assert m("Priya is an operations manager.", ["Being a manager is never boring."]) == []
    assert m("Birthday on 1 May.", ["My birthday is on 1 May, reminder to plan something."]) == []
    # "extrait", "portrait" are not conditionals
    assert m("Camille a lu un extrait du portrait.", ["J'ai lu un extrait du portrait."]) == []


def test_cascade_derriere_un_reglage(monkeypatch):
    ev = {"id": 1, "occurred_at": "2026-09-14T08:00:00+00:00",
          "payload": {"t": "Peut-être que j'apprendrai la voile cet été."}}
    mem = {"type": "episodic", "content": "Camille a appris la voile.", "source_event_ids": [1],
           "preuve": ["Peut-être que j'apprendrai la voile cet été"]}
    assert evidence.check(mem, {1: ev})["status"] == "ok"            # default: unchanged
    monkeypatch.setattr("pensine.config.EVIDENCE_MODALITY", "signaler")
    res = evidence.check(mem, {1: ev})
    assert res["status"] == "flag" and res["motifs"] == ["modalité : futur, hypothese"]
    kept, rep = evidence.verify([mem], [ev], severity="strict")
    assert kept == [] and rep["issues"]["modalite"] == 1


def test_soutien_s4():
    ev = {"id": 1, "payload": {"t": "In the end I did not sign up for the marathon."}}
    mem = {"content": "Kofi signed up for the marathon.", "source_event_ids": [1],
           "evidence": {"citations": ["I did not sign up for the marathon"]}}
    c = integrity.support_check(mem, [ev])
    assert c["s1_extraits"] and not c["s4_modalite"]
    assert not c["soutenue"] and c["modes"] == ["negation"]
    out = integrity.support_rate([mem], {1: ev})
    assert out["modes_en_defaut"] == {"negation": 1}


def test_negation_elliptique_dans_la_memoire():
    assert modality.mismatches("Plus de café après seize heures.",
                               ["ne plus prendre de café après seize heures"]) == []
    assert modality.mismatches("Kofi quit smoking.", ["I don't smoke anymore."]) == []
