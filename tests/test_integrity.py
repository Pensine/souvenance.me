"""Integrity indicators: verifiable counts, never content."""

import json
from datetime import datetime, timezone
from pathlib import Path

from pensine import evidence, integrity

NIGHTS = Path(__file__).parent / "fixtures" / "integrity_nights.json"


def _nights():
    return json.loads(NIGHTS.read_text(encoding="utf-8"))


def test_wilson_petit_echantillon():
    w = integrity.wilson(0, 5)
    assert w["p"] == 0 and w["ic95"][0] == 0
    assert 0.4 < w["ic95"][1] < 0.45            # "0 out of 5" leaves up to ~43%
    assert integrity.wilson(0, 0)["p"] is None
    big = integrity.wilson(10, 1000)
    assert big["ic95"][1] - big["ic95"][0] < 0.02


def test_invention_bilans_nouveaux_et_anciens():
    _, rep = evidence.verify(_nights()[0]["candidates"], _nights()[0]["events"],
                             owner="Camille")
    at = datetime(2026, 9, 15, 3, tzinfo=timezone.utc)
    ancien = {"verifiees": 4, "relues": 1, "corrigees": 0, "partielles": 0,
              "rejetees": 1, "a_verifier": 0}
    out = integrity.invention_at_write([{"at": at, "detail": json.dumps(rep)},
                                        {"at": at, "detail": ancien}])
    assert out["nuits"] == 2 and out["exact"] is False   # an old report: lower bound
    # night 1: 6 candidates, 2 rejected (excerpt not found, no excerpt),
    # 1 flagged: "12" and "d'Annecy" ("Course", at the start of a sentence,
    # is no longer taken for a proper noun); old night: 5 candidates, 1 rejected
    assert out["taux_invention_ecriture"]["k"] == 3 + 1
    assert out["taux_invention_ecriture"]["n"] == 11
    assert out["issues"]["details_absents"] == 1


def test_soutien_deterministe():
    ev = _nights()[0]["events"]
    by_id = {e["id"]: e for e in ev}
    bonne = {"content": "Dix kilomètres de course autour du lac avec Camille.",
             "source_event_ids": [101],
             "evidence": {"citations": ["j'ai couru dix kilomètres autour du lac avec Camille"],
                          "statut": "verifiee"}}
    ajout = {**bonne, "content": "Dix kilomètres autour du lac avec Camille, puis dîner à Lyon."}
    hors_sujet = {**bonne, "content": "Il prépare un marathon en solitaire cet hiver."}
    c = integrity.support_check(bonne, [by_id[101]])
    assert c["soutenue"] and c["recouvrement"] > 0.5
    c = integrity.support_check(ajout, [by_id[101]])
    assert not c["s2_details"] and c["manquants"] == ["Lyon"]
    assert not integrity.support_check(hors_sujet, [by_id[101]])["s3_recouvrement"]
    out = integrity.support_rate([bonne, ajout, {"content": "ancienne", "evidence": None},
                                  {**bonne, "source_event_ids": [999]}], by_id)
    assert out["taux_soutien"]["k"] == 1 and out["taux_soutien"]["n"] == 2
    assert out["sans_preuve_anterieures"] == 1 and out["sources_illisibles"] == 1


def test_soutien_relecture_modele_optionnelle():
    by_id = {e["id"]: e for e in _nights()[0]["events"]}
    m = {"content": "Course de dix kilomètres autour du lac.", "source_event_ids": [101],
         "evidence": {"citations": ["j'ai couru dix kilomètres autour du lac"]}}
    out = integrity.support_rate([m], by_id)
    assert "modele" not in out                         # disabled by default
    out = integrity.support_rate([m], by_id, ask=lambda p: '{"verdict": "soutenue"}',
                                 extract_json=json.loads)
    assert out["modele"]["taux_soutien"]["k"] == 1


def test_frontiere_monotone():
    out = integrity.frontier(_nights(), owner="Camille")
    pts = {p["severite"]: p for p in out["points"]}
    assert out["etiquetee"] and out["nuits"] == 2
    g = [pts[s]["gardees"]["k"] for s in ("desactive", "defaut", "strict")]
    assert g[0] >= g[1] >= g[2]                         # stricter, fewer kept
    inv = [pts[s]["inventions_gardees"]["k"] for s in ("desactive", "defaut", "strict")]
    assert inv[0] >= inv[1] >= inv[2] and inv[2] == 0
    assert pts["strict"]["rappel_fideles"]["k"] < pts["desactive"]["rappel_fideles"]["k"]


def test_frontiere_sans_etiquettes_et_rendu():
    nights = _nights()
    for n in nights:
        for c in n["candidates"]:
            c.pop("_verdict")
    out = integrity.frontier(nights)
    assert not out["etiquetee"] and "rappel_fideles" not in out["points"][0]
    md = integrity.render_markdown({"frontiere": out, "genere_le": "t"})
    assert "Unsupported among the kept" in md
    # publishable: no memory or deposit content in the rendering
    assert "kilomètres" not in md and "ACME" not in md


def test_nuits_depuis_le_banc_frugal():
    ds = {"batches": [{"night": "n1", "events": [{"id": 1}], "reference": []}]}
    run = {"results": [{"night": "n1", "memories": [{"content": "a"}, {"content": "b"}]},
                       {"night": "n2", "memories": None}]}
    verdicts = [{"night": "n1", "verdict": {"candidates": [{"verdict": "fidele"}]}}]
    out = integrity.nights_from_bench(ds, run, verdicts)
    assert len(out) == 1 and out[0]["candidates"][0]["_verdict"] == "fidele"
    assert "_verdict" not in out[0]["candidates"][1]


def test_severites_de_la_cascade():
    douteuse = {"type": "semantic", "content": "Course de 12 km au bord du lac.",
                "source_event_ids": [101], "preuve": ["j'ai couru dix kilomètres autour du lac"]}
    ev = _nights()[0]["events"]
    assert len(evidence.verify([douteuse], ev, severity="defaut")[0]) == 1   # kept, capped
    assert evidence.verify([douteuse], ev, severity="strict")[0] == []
    kept, rep = evidence.verify([{**douteuse, "preuve": []}], ev, severity="desactive")
    assert kept[0]["evidence"]["statut"] == "non_verifiee" and rep["rejetees"] == 0


def test_palier2_par_verdict_et_reference():
    ds = {"batches": [{"night": "n1",
                       "events": [{"id": 1, "occurred_at": "2026-09-14T08:00:00+00:00",
                                   "payload": {"t": "dix kilomètres avec Camille"}}],
                       "reference": [{"content": "Dix kilomètres avec Camille.",
                                      "source_event_ids": [1]}]}]}
    v = [{"night": "n1", "verdict": {"candidates": [{"verdict": "fidele"}]}}]
    nights = integrity.nights_from_bench(ds, None, v)
    out = integrity.palier2(nights)
    assert out["par_verdict"]["fidele"]["k"] == 0 and out["par_verdict"]["fidele"]["n"] == 1
