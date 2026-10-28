"""An assistant's memory: read in all its forms, compared in numbers."""

import json
import os
from datetime import datetime, timezone

import pytest

from pensine import vendor_memory as vm


def test_liste_a_puces_avec_dates_et_sections():
    text = """# Travail
- [2026-03-02] - Travaille sur une app de course à pied
  avec un modèle d'abonnement
- Préfère les réponses courtes

# Vie perso
- Court des trails en forÃªt
"""
    e = vm.split_text(text)
    assert [x["text"] for x in e] == [
        "Travaille sur une app de course à pied avec un modèle d'abonnement",
        "Préfère les réponses courtes",
        "Court des trails en forÃªt"]
    assert e[0]["saved_at"] == "2026-03-02" and e[0]["section"] == "Travail"
    assert e[2]["section"] == "Vie perso" and e[1]["saved_at"] is None


def test_paragraphes_et_decoupage_des_longs():
    long = " ".join(["Une phrase assez longue pour remplir le paragraphe."] * 60)
    e = vm.split_text(f"Premier paragraphe.\n\n{long}")
    assert e[0]["text"] == "Premier paragraphe."
    assert len(e) > 2 and all(len(x["text"]) <= vm.MAX_ENTRY_CHARS for x in e)


def test_json_inconnu_memoires_et_projets():
    data = {"memories": [{"content": "Habite près d'un lac", "created_at": "2026-05-01"},
                         "Aime le café filtre"],
            "projects": [{"name": "Coach", "description": "app", "prompt_template": "sois bref",
                          "docs": [{"filename": "plan.md", "content": "x" * 5000}]}]}
    entries, projects = vm._from_json(data)
    assert {x["text"] for x in entries} == {"Habite près d'un lac", "Aime le café filtre"}
    assert next(x for x in entries if "lac" in x["text"])["saved_at"] == "2026-05-01"
    assert projects[0]["name"] == "Coach"
    payload = vm._project_payload(projects[0])
    assert payload["docs"][0]["filename"] == "plan.md" and len(payload["docs"][0]["extrait"]) == 2000


def test_dossier_d_export(tmp_path):
    (tmp_path / "memories").mkdir()
    (tmp_path / "memories" / "profil.md").write_text("- Un\n- Deux\n- Trois\n", encoding="utf-8")
    (tmp_path / "projects").mkdir()
    (tmp_path / "projects" / "p1.json").write_text(json.dumps(
        {"name": "Pensine", "description": "mémoire", "docs": []}), encoding="utf-8")
    (tmp_path / "conversations.json").write_text("[]", encoding="utf-8")
    entries, projects, notes = vm.read_path(tmp_path)
    assert [x["text"] for x in entries] == ["Un", "Deux", "Trois"]
    assert projects[0]["name"] == "Pensine"
    assert any("import_history" in n for n in notes)

    events = vm.to_events(entries, projects, "claude")
    assert {e["kind"] for e in events} == {"memory_entry", "project"}
    assert all(e["payload"]["seconde_main"] for e in events)
    assert events[0]["payload"]["date_connue"] is False
    # without its own date: the file date, stable from one import to the next
    again = vm.to_events(*vm.read_path(tmp_path)[:2], "claude")
    assert [e["occurred_at"] for e in again] == [e["occurred_at"] for e in events]


def test_comparaison_par_classes():
    v = [{"id": 1, "text": "a", "vec": [1, 0, 0]},
         {"id": 2, "text": "b", "vec": [0.7, 0.7, 0]},
         {"id": 3, "text": "c", "vec": [0, 0, 1]}]
    o = [{"id": 10, "text": "A", "vec": [1, 0.05, 0]},
         {"id": 11, "text": "B", "vec": [0, 1, 0]}]
    r = vm.compare(v, o, shared=0.9, near=0.6)
    classes = {e["id"]: e["classe"] for e in r["assistant_vers_moi"]["elements"]}
    assert classes == {1: "partage", 2: "voisin", 3: "absent"}
    s = r["assistant_vers_moi"]["stats"]
    assert s["n"] == 3 and s["classes"] == {"partage": 1, "voisin": 1, "absent": 0 + 1}
    assert r["moi_vers_assistant"]["stats"]["n"] == 2


@pytest.mark.skipif(not os.environ.get("PENSINE_TEST_DB"),
                    reason="PENSINE_TEST_DB not set (integration test)")
def test_import_dans_le_log_et_dedoublonnage(monkeypatch, tmp_path):
    monkeypatch.setattr("pensine.config.DATABASE_URL", os.environ["PENSINE_TEST_DB"])
    from pensine import db
    from pensine.governor import Governor
    f = tmp_path / "memoire.md"
    f.write_text("- TestVendor : aime la forÃªt\n- TestVendor : boit du thé\n"
                 "- TestVendor : lit le soir\n", encoding="utf-8")
    events = vm.to_events(*vm.read_path(f)[:2], "claude")
    with db.connection() as conn:
        kept = Governor().filter_events(conn, events)
        first = [db.append_event(conn, source=e["source"], kind=e["kind"],
                                 occurred_at=e["occurred_at"], payload=e["payload"]) for e in kept]
        second = [db.append_event(conn, source=e["source"], kind=e["kind"],
                                  occurred_at=e["occurred_at"], payload=e["payload"]) for e in kept]
        conn.commit()
    assert all(first) and not any(second)


def test_rapport_du_miroir():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import vendor_mirror
    v = [{"id": 1, "text": "Claude croit X", "vec": [1, 0]},
         {"id": 2, "text": "Claude croit Y", "vec": [0, 1]}]
    o = [{"id": 10, "text": "Je sais X", "vec": [1, 0.02]}]
    r = vm.compare(v, o)
    md = vendor_mirror.render(r, "claude", [{"assistant": "a", "moi": "b",
                                             "verdict": "contradiction", "explication": "e"}],
                              "2026-10-23")
    assert "| What claude knows → in mine | 2 | 50.0 %" in md
    assert "Claude croit Y" in md.split("my memory does not")[1]
    assert "**Contradiction**" in md


def test_un_element_herite_du_dossier_de_son_document(tmp_path):
    from pensine.governor import Governor
    proj = tmp_path / "projects" / "ACME"
    proj.mkdir(parents=True)
    (proj / "contexte.md").write_text("- Réunion budget\n- Note interne\n- Calendrier\n",
                                      encoding="utf-8")
    (tmp_path / "running.md").write_text("- Court le dimanche\n- Prépare un trail\n- Aime la côte\n",
                                         encoding="utf-8")
    events = vm.to_events(*vm.read_path(tmp_path)[:2], "claude")
    g = Governor()
    g.rules = {**g.rules, "exclusions": {"sources": [], "motifs": ["ACME"]}}
    kept = [e for e in events if g.event_allowed(e["source"], e["payload"])[0]]
    assert {e["payload"]["file"] for e in kept} == {"running.md"}


def test_en_tete_contexte_herite_et_non_importe(tmp_path):
    from pensine.governor import Governor
    (tmp_path / "areas").mkdir()
    (tmp_path / "areas" / "ged.md").write_text(
        '---\nname: "ged"\ndescription: "Migration GED au ACME"\n---\n\n'
        "- Pilote la migration\n- Choix de SharePoint\n- Formation des agents\n",
        encoding="utf-8")
    entries, _, _ = vm.read_path(tmp_path)
    assert [e["text"] for e in entries] == ["Pilote la migration", "Choix de SharePoint",
                                            "Formation des agents"]
    assert entries[0]["document"] == "ged — Migration GED au ACME"
    g = Governor()
    g.rules = {**g.rules, "exclusions": {"sources": [], "motifs": ["ACME"]}}
    events = vm.to_events(entries, [], "claude")
    assert not any(g.event_allowed(e["source"], e["payload"])[0] for e in events)
