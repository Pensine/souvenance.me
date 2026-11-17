"""Pensine, scripted mode, end to end on a throwaway database.

Skipped unless SOURCED_DB_PORT points at a PostgreSQL with pgvector and
unaccent where the role `sourced` (password `sourced`) may create databases
(docker-compose.yml in this folder, or any local server). No model is
loaded: the consolidation model is Pensine's `fake` backend fed by the
scripted extractor, and embeddings are switched off.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sourced.judge import LexicalJudge  # noqa: E402
from sourced.runner import load, run  # noqa: E402
from sourced.score import score_run  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[1] / "sample"

pytestmark = pytest.mark.skipif(not os.environ.get("SOURCED_DB_PORT"),
                                reason="SOURCED_DB_PORT not set (throwaway database)")


@pytest.fixture(scope="module")
def scored():
    os.environ["PENSINE_EMBEDDINGS"] = "0"     # never load an embedding model here
    os.environ["PENSINE_RERANKER"] = ""
    from sourced.adapters.pensine import PensineSystem
    truth, deps, qs = load(SAMPLE)
    owner = next(p["name"] for p in truth["people"] if p["id"] == truth["owner"])
    system = PensineSystem(owner=owner, mode="scripted", truth=truth, deposits=deps)
    res = json.loads(json.dumps(run(system, SAMPLE, qa=False, progress=None)))
    return truth, res, score_run(truth, deps, qs, res, LexicalJudge(truth, deps))


def test_attribution_is_measured_for_pensine(scored):
    """Pensine declares a subject per memory (migration 016), so the rate is
    a number: the scripted extractor's careless trap memories ("<owner>
    works at <the sister's employer>") count as errors."""
    _, _, rep = scored
    snap = rep["snapshots"][-1]
    assert rep["headline"]["attribution_error_rate"] is not None
    assert snap["attribution_reason"] is None
    assert snap["attribution_measurable"] > 0
    assert 0 < snap["attribution_error_rate"] < 0.5


def test_a_role_lands_on_the_person_the_deposit_names(scored):
    """"My sister works at …" is written by role; the subject Pensine exposes
    is the person the alias deposit proved, resolved in code."""
    truth, res, _ = scored
    mems = res["snapshots"][-1]["memories"]
    for x in truth["identity"]:
        p = next(q for q in truth["people"] if q["id"] == x["person"])
        role = x["role"]
        by_role = [m for m in mems if m["content"].lower().startswith(role)]
        assert by_role, role
        assert {m["subject"] for m in by_role} == {p["name"].split()[0]}


def test_pensine_brackets_dates_in_code_and_refuses_exact_ones(scored):
    """The scripted extractor proposes "not yet" / "already" bounds and an
    injected `exact` bound on a relation quote; Pensine refuses the exact one,
    derives [A, B] in code, and the store shows no invented precision."""
    truth, res, rep = scored
    snap = rep["snapshots"][-1]
    assert snap["store_dating"]["facts"] == len(truth["dating"]) > 0
    assert snap["store_dating"]["justified"] == len(truth["dating"])
    assert snap["store_invented_precision_rate"] == 0.0
    mems = res["snapshots"][-1]["memories"]
    for x in truth["dating"]:
        f = next(f for f in truth["facts"] if f["id"] == x["fact"])
        timed = [m for m in mems if f["value"]["item"] in m["content"]]
        assert {(m["event_earliest"], m["event_latest"]) for m in timed} == \
            {(x["not_yet_day"], x["already_day"])}
    refused = sum(n.get("time_bounds_refused") or 0 for n in res["system"]["evidence_gate"])
    assert refused == len(truth["dating"])


def test_identity_coverage_inferred_hedged_decoys_unlinked(scored):
    """The careless linker proposes every coverage pair; Pensine's code keeps
    the converging one as an INFERRED claim and links no decoy."""
    truth, res, rep = scored
    snap = rep["snapshots"][-1]
    d = snap["alias_detail"]
    assert snap["alias_precision"] == 1.0 and not d["false_links"]
    assert d["recall_by_kind"] == {"written_together": 1.0, "converging": 1.0}
    assert d["recall_by_tier"]["inferred"] == round(1 / d["true_identities"], 4)
    conv = next(x for x in truth["coverage"] if x["case"] == "converging")
    tiers = {(a["alias"], a["tier"]) for a in res["snapshots"][-1]["aliases"]}
    assert (conv["role"], "inferred") in tiers
