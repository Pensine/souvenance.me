"""The entailment rescue tier: a paraphrase the word-level check refuses."""

import pytest

from pensine import evidence, readers

pytestmark = pytest.mark.skipif(readers._nli() is None, reason="NLI model not installed")

SOURCE = {"id": 1, "payload": {"text": "Went to the movies with Kasper last night, we laughed a lot."}}


def test_a_paraphrase_is_kept_by_entailment_not_reread():
    m = {"type": "episodic", "source_event_ids": [1],
         "preuve": ["Went to the movies with Kasper last night"],
         "content": "Went to the Cinema with Kasper."}
    asked = []
    kept, report = evidence.verify([m], [SOURCE], ask=lambda *a, **k: asked.append(1) or "{}",
                                   extract_json=lambda s: {})
    assert [k["evidence"]["statut"] for k in kept] == ["verifiee_nli"]
    assert report["issues"].get("nli_soutenue") == 1 and not asked


def test_an_unstated_detail_is_not_entailed():
    m = {"type": "episodic", "source_event_ids": [1],
         "preuve": ["Went to the movies with Kasper last night"],
         "content": "Went to the movies with Kasper in Ghent."}
    kept, report = evidence.verify([m], [SOURCE])
    assert report["issues"].get("nli_soutenue") is None
    assert all(k["evidence"]["statut"] != "verifiee_nli" for k in kept)


def test_a_number_is_never_rescued():
    src = {"id": 2, "payload": {"text": "j'ai couru dix kilomètres autour du lac"}}
    m = {"type": "semantic", "source_event_ids": [2], "preuve": ["j'ai couru dix kilomètres autour du lac"],
         "content": "Course de 12 km au bord du lac."}
    _, report = evidence.verify([m], [src])
    assert report["issues"].get("nli_soutenue") is None
