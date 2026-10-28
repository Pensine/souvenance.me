"""Recall: query terms, rank fusion, reranker and its fallback,
temporal cues in the question. Everything is computed in code, hence testable."""

import os
from datetime import date, datetime, timezone

import pytest

from pensine import config, retrieval, temporal

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


# --- query terms --------------------------------------------------------------

def test_terms_retire_mots_vides_accents_doublons():
    assert retrieval.terms("Qu'est-ce que j'ai fait à Chambéry, à Chambéry ?") == [
        "chambery"]
    assert retrieval.terms("When did Caroline go to the LGBTQ support group?") == [
        "caroline", "go", "lgbtq", "support", "group"]


def test_terms_ne_laisse_passer_aucune_syntaxe_tsquery():
    for w in retrieval.terms("a & b | !c :* (d) 'e' été2026 l'été"):
        assert w.isascii() and all(ch.isalnum() or ch == "_" for ch in w)


def test_terms_ignore_ecritures_non_latines():
    assert retrieval.terms("東京 trip") == ["trip"]


def test_lexeme_prefixe_les_mots_longs_seulement(monkeypatch):
    monkeypatch.setattr(retrieval, "LEX_PREFIX", True)
    assert retrieval.lexeme("camped") == "camp:*"
    assert retrieval.lexeme("lgbtq") == "lgbtq"      # short: exact
    assert retrieval.lexeme("2023") == "2023"        # number: exact
    monkeypatch.setattr(retrieval, "LEX_PREFIX", False)
    assert retrieval.lexeme("camped") == "camped"


# --- fusion -------------------------------------------------------------------

def test_fuse_rrf_favorise_le_consensus():
    vector = [{"id": 1, "distance": 0.2}, {"id": 2, "distance": 0.3},
              {"id": 3, "distance": 0.4}]
    lexical = [{"id": 3, "distance": None}, {"id": 4, "distance": None},
               {"id": 1, "distance": None}]
    out = retrieval.fuse([vector, lexical])
    ids = [r["id"] for r in out]
    # 1: 1/61 + 1/63; 3: 1/63 + 1/61 -- tie, broken by arrival order
    assert ids[:2] == [1, 3]
    assert set(ids) == {1, 2, 3, 4}
    assert [r["fusion_rank"] for r in out] == [0, 1, 2, 3]
    # the vector distance survives the fusion, even for a seen row
    # first without it
    assert next(r for r in out if r["id"] == 3)["distance"] == 0.4


def test_fuse_formule_exacte_et_poids():
    out = retrieval.fuse([[{"id": 7}], [{"id": 8}]], k=60, weights=[2.0, 1.0])
    assert [r["id"] for r in out] == [7, 8]
    assert out[0]["rrf"] == pytest.approx(2 / 61)
    assert out[1]["rrf"] == pytest.approx(1 / 61)


def test_fuse_listes_vides():
    assert retrieval.fuse([]) == []
    assert retrieval.fuse([[], []]) == []


# --- reranker and fallback -------------------------------------------------------

ROWS = [{"id": i, "content": c} for i, c in
        enumerate(["la météo", "le chat Mistigri", "les impôts"])]


class FakeModel:
    def predict(self, pairs, **_):
        return [1.0 if "chat" in doc else 0.0 for _, doc in pairs]


def test_rerank_desactive_par_defaut(monkeypatch):
    monkeypatch.setattr(config, "RERANKER_MODEL", "")
    assert retrieval.rerank("mon chat", list(ROWS)) == ROWS


def test_rerank_retrie_la_tete(monkeypatch):
    monkeypatch.setattr(config, "RERANKER_MODEL", "faux")
    monkeypatch.setattr(retrieval, "_load_reranker", lambda: FakeModel())
    out = retrieval.rerank("mon chat", [dict(r) for r in ROWS], top=2)
    # only the first 2 are re-read; the 3rd keeps its place behind
    assert [r["id"] for r in out] == [1, 0, 2]
    assert [r["fusion_rank"] for r in out] == [0, 1, 2]
    assert retrieval.last_rerank_ms is not None


def test_rerank_repli_si_le_modele_ne_charge_pas(monkeypatch, caplog):
    monkeypatch.setattr(config, "RERANKER_MODEL", "modele/inexistant")
    monkeypatch.setattr(retrieval, "_reranker", None)
    monkeypatch.setattr(retrieval, "_reranker_failed", False)
    import sys
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)  # import impossible
    rows = [dict(r) for r in ROWS]
    assert retrieval.rerank("mon chat", rows) == rows
    assert retrieval._reranker_failed is True
    assert "Reranker unavailable" in caplog.text
    # a single attempt per process: no reload on every question
    assert retrieval._load_reranker() is None


def test_rerank_repli_si_la_prediction_echoue(monkeypatch):
    class Broken:
        def predict(self, *a, **k):
            raise RuntimeError("mémoire épuisée")
    monkeypatch.setattr(config, "RERANKER_MODEL", "faux")
    monkeypatch.setattr(retrieval, "_load_reranker", lambda: Broken())
    rows = [dict(r) for r in ROWS]
    assert retrieval.rerank("mon chat", rows) == rows


# --- temporal cues in the question --------------------------------------------

def cue(q, landmarks=None):
    c = temporal.cues(q, NOW, landmarks)
    return (c["debut"], c["fin"]) if c else None


@pytest.mark.parametrize("q, expected", [
    ("Qu'est-ce que j'ai fait l'été dernier ?", (date(2026, 6, 1), date(2026, 9, 1))),
    ("What did I do last summer?", (date(2026, 6, 1), date(2026, 9, 1))),
    ("cet automne", (date(2026, 9, 1), date(2026, 12, 1))),
    ("l'hiver dernier", (date(2025, 12, 1), date(2026, 3, 1))),
    ("in the summer of 2022", (date(2022, 6, 1), date(2022, 9, 1))),
    ("en mai", (date(2026, 5, 1), date(2026, 6, 1))),
    ("en novembre", (date(2025, 11, 1), date(2025, 12, 1))),  # the last one elapsed
    ("in May 2023", (date(2023, 5, 1), date(2023, 6, 1))),
    ("le 8 mai 2023", (date(2023, 5, 7), date(2023, 5, 10))),
    ("on June 9, 2023", (date(2023, 6, 8), date(2023, 6, 11))),
    ("2023-05-08", (date(2023, 5, 7), date(2023, 5, 10))),
    ("hier", (date(2026, 10, 27), date(2026, 10, 28))),
    ("la semaine dernière", (date(2026, 10, 19), date(2026, 10, 26))),
    ("le mois dernier", (date(2026, 9, 1), date(2026, 10, 1))),
    ("l'an dernier", (date(2025, 1, 1), date(2026, 1, 1))),
    ("en 2023", (date(2023, 1, 1), date(2024, 1, 1))),
])
def test_cues_periodes(q, expected):
    assert cue(q) == expected


def test_cues_il_y_a():
    start, end = cue("il y a 3 semaines")
    assert start < date(2026, 10, 7) < end
    start, end = cue("two weeks ago")
    assert start < date(2026, 10, 14) < end


@pytest.mark.parametrize("q", [
    "Who is Caroline?",
    "What may happen next?",        # "may" the verb, not the month
    "the summer",                   # nothing anchors it in time
    "mon chat Mistigri",
])
def test_cues_absentes(q):
    assert cue(q) is None


def test_cues_jalons():
    lms = [{"name": "Déménagement à Chambéry", "at_date": date(2026, 9, 1)}]
    assert cue("avant le déménagement", lms) == (None, date(2026, 9, 1))
    assert cue("depuis le déménagement à Chambéry", lms) == (date(2026, 9, 1), None)
    start, end = cue("au moment du déménagement", lms)
    assert start < date(2026, 9, 1) < end


def test_cues_passee_et_bornes():
    c = temporal.cues("l'été dernier", NOW)
    assert c["passee"] is True
    assert temporal.cues("cette semaine", NOW)["passee"] is False
    start, end = temporal.window_bounds(c)
    assert start == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert temporal.window_bounds(None) is None


# --- time modulates the fusion rank --------------------------------------------

def row(i, when, rank):
    return {"id": i, "valid_from": when, "valid_to": None, "superseded_by": None,
            "archived_at": None, "distance": None, "fusion_rank": rank}


def test_rank_suit_le_rang_de_fusion():
    rows = [row(1, NOW, 1), row(2, NOW, 0)]
    assert [r["id"] for r in temporal.rank(rows, None, now=NOW)] == [2, 1]


def test_rank_fait_remonter_la_periode_visee():
    july = datetime(2026, 7, 10, tzinfo=timezone.utc)
    rows = [row(i, NOW, i) for i in range(6)] + [row(99, july, 6)]
    window = (datetime(2026, 6, 1, tzinfo=timezone.utc),
              datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert temporal.rank(rows, None, now=NOW)[-1]["id"] == 99
    assert temporal.rank(rows, None, now=NOW, window=window)[0]["id"] == 99


# --- integration: hybrid search on a real database -----------------------------

@pytest.mark.skipif(not os.environ.get("PENSINE_TEST_DB"),
                    reason="PENSINE_TEST_DB not set (integration test)")
def test_hybride_trouve_un_nom_que_le_vecteur_ignore(monkeypatch):
    monkeypatch.setattr("pensine.config.DATABASE_URL", os.environ["PENSINE_TEST_DB"])
    monkeypatch.setattr(config, "RERANKER_MODEL", "")
    from pensine import db

    with db.connection() as conn:
        mid = conn.execute(
            """INSERT INTO memories (type, content, confidence, importance, valid_from)
               VALUES ('semantic', 'TestHybride : rendez-vous chez Zorglubienne à Écully',
                       0.9, 0.5, '2026-06-01') RETURNING id""").fetchone()["id"]
        found = db.search_memories(conn, "zorglubienne ecully", None, mark=False)
        assert mid in [r["id"] for r in found]
        # the targeted period excludes nothing: a memory outside the period remains findable
        window = (datetime(2020, 1, 1, tzinfo=timezone.utc),
                  datetime(2020, 2, 1, tzinfo=timezone.utc))
        found = db.search_memories(conn, "zorglubienne", None, mark=False, window=window)
        assert mid in [r["id"] for r in found]
        conn.rollback()
