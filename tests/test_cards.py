"""MCP Apps cards: valid pages, correct data, nothing external."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from pensine import cards, places, widgets

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("name", widgets.NAMES)
def test_page_de_carte_autonome(name):
    page = widgets.html(name)
    assert page.startswith("<!doctype html>")
    assert "globalThis.ExtApps={" in page           # bundled module, rewritten as a global
    assert "/*__EXT_APPS_BUNDLE__*/" not in page and "/*__BASE_CSS__*/" not in page
    assert "https://esm.sh" not in page and "cdn." not in page  # no external script
    assert "App" in page.split("globalThis.ExtApps={", 1)[1][:4000]


def test_outils_et_ressources_declares():
    import asyncio
    from pensine.mcp_server import mcp
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    for name, card in [("listen", "listen"), ("memory_card", "memory"), ("timeline", "timeline")]:
        assert tools[name].meta["ui"]["resourceUri"] == widgets.uri(card)
    for hidden in ("listen_words", "memory_photo", "media_link"):
        assert tools[hidden].meta["ui"]["visibility"] == ["app"]
    res = {str(r.uri): r for r in asyncio.run(mcp.list_resources())}
    for card in widgets.NAMES:
        assert res[widgets.uri(card)].mime_type == widgets.MIME


def test_mots_horodates(tmp_path, monkeypatch):
    monkeypatch.setattr(cards.config, "MEDIA_ROOT", tmp_path)
    (tmp_path / "a.m4a.whisperx.json").write_text(json.dumps({"segments": [
        {"words": [{"word": "Oui,", "start": 0.965, "end": 1.626}, {"word": "bon"}]},
        {"words": [{"word": "voilà", "start": 2.0, "end": 2.4}]}]}), encoding="utf-8")
    assert cards.words("a.m4a") == [{"w": "Oui,", "s": 0.96, "e": 1.63},
                                    {"w": "voilà", "s": 2.0, "e": 2.4}]
    assert cards.words("absent.m4a") == []


def test_vignette_photo(tmp_path, monkeypatch):
    PIL = pytest.importorskip("PIL.Image")
    monkeypatch.setattr(cards.config, "MEDIA_ROOT", tmp_path)
    PIL.new("RGB", (3000, 2000), (200, 120, 60)).save(tmp_path / "p.jpg")
    url = cards.thumbnail("p.jpg")
    assert url.startswith("data:image/jpeg;base64,") and len(url) < 200_000
    assert cards.thumbnail("absent.jpg") is None


def test_mini_carte_hors_ligne(tmp_path, monkeypatch):
    rows = [["1", "Montpellier", "", "", "43.61092", "3.87723", "P", "", "FR", "", "76"],
            ["2", "Lattes", "", "", "43.56667", "3.9", "P", "", "FR", "", "76"],
            ["3", "Annecy", "", "", "45.90878", "6.12565", "P", "", "FR", "", "84"]]
    (tmp_path / "cities1000.txt").write_text(
        "\n".join("\t".join(r + [""] * 8) for r in rows), encoding="utf-8")
    monkeypatch.setattr(places, "GEO_DIR", tmp_path)
    places._index.cache_clear()
    m = cards.mini_map(43.611, 3.873)
    names = [p["name"] for p in m["points"]]
    assert names == ["Montpellier", "Lattes"]          # Annecy is outside the radius
    assert 5 <= m["radius_km"] <= 30                    # scale adapted
    lattes = m["points"][1]
    assert lattes["y"] < 0 and lattes["x"] > 0          # south-east
    places._index.cache_clear()


class _Conn:
    def __init__(self, landmarks):
        self.landmarks = landmarks

    def execute(self, sql, params=None):
        rows = self.landmarks if "FROM landmarks" in sql else []

        class R:
            def fetchall(self_inner):
                return rows
        return R()


def test_frise_en_quatre_temps(monkeypatch):
    monkeypatch.setattr(cards.db, "chapters", lambda conn: [])
    monkeypatch.setattr(cards.db, "memory_snippets", lambda conn, ids: {3: "Version à jour"})
    d = lambda days: NOW + timedelta(days=days)  # noqa: E731
    rows = [
        {"id": 1, "type": "semantic", "content": "Ancienne version", "valid_from": d(-150),
         "valid_to": d(-30), "superseded_by": 3, "revision_note": "a changé de cap"},
        {"id": 2, "type": "episodic", "content": "Fini sans suite", "valid_from": d(-90),
         "valid_to": d(-10), "superseded_by": None, "revision_note": None},
        {"id": 3, "type": "semantic", "content": "Version à jour", "valid_from": d(-30),
         "valid_to": None, "superseded_by": None},
        {"id": 4, "type": "semantic", "content": "Projet daté", "valid_from": d(40),
         "valid_to": None, "superseded_by": None},
    ]
    landmarks = [{"name": "Lancement Atelier Nova Arena", "at_date": date(2026, 12, 1), "kind": "life_event"},
                 {"name": "Marathon d'Annecy", "at_date": date(2027, 4, 20), "kind": "race"}]
    out = cards.timeline(_Conn(landmarks), rows, "Atelier Nova", now=NOW)
    lanes = out["lanes"]
    assert [i["id"] for i in lanes["etait"]] == [1, 2]
    assert lanes["change"] == [{"id": 1, "date": d(-30).isoformat(), "quand": "il y a 4 semaines",
                                "raison": "a changé de cap", "de": "Ancienne version",
                                "vers": "Version à jour", "vers_id": 3}]
    assert [i["id"] for i in lanes["est"]] == [3]
    # sorted by date (Dec 1 before Dec 2); the marathon is not about the subject
    assert [i["content"] for i in lanes["vient"]] == ["Lancement Atelier Nova Arena", "Projet daté"]


def test_un_episode_ancien_va_dans_l_histoire(monkeypatch):
    monkeypatch.setattr(cards.db, "chapters", lambda conn: [])
    monkeypatch.setattr(cards.db, "memory_snippets", lambda conn, ids: {})
    d = lambda days: NOW + timedelta(days=days)  # noqa: E731
    rows = [{"id": 1, "type": "episodic", "content": "A quitté son employeur en mai",
             "valid_from": d(-160), "valid_to": None, "superseded_by": None},
            {"id": 2, "type": "episodic", "content": "Réunion de la semaine",
             "valid_from": d(-5), "valid_to": None, "superseded_by": None},
            {"id": 3, "type": "semantic", "content": "Fait durable ancien",
             "valid_from": d(-160), "valid_to": None, "superseded_by": None}]
    lanes = cards.timeline(_Conn([]), rows, "x", now=NOW)["lanes"]
    assert [i["id"] for i in lanes["etait"]] == [1]
    assert sorted(i["id"] for i in lanes["est"]) == [2, 3]
