"""Cited evidence: what cannot be verified in the deposit does not get in."""

import json

from pensine import evidence

DEPOT = {"id": 6, "occurred_at": "2026-08-05T14:29:30+00:00",
         "payload": {"filename": "Route d'Annecy.m4a", "kind": "audio"},
         "media_transcript": "Oui, j'étais juste en train de faire ma première recording de "
                             "moi-même, on est au cinquième, et je suis dans ma voiture en allant "
                             "à Albertville. Dans quelques années, je voudrais pouvoir lui reparler."}
LOG = {"id": 8, "occurred_at": "2026-08-06T10:54:35+00:00",
       "payload": {"transcript": "Pensine est le nom du projet."}}
BY_ID = {6: DEPOT, 8: LOG}


def test_normalisation():
    assert evidence.normalize("J’étais « là », Albertville !") == "j'etais la albertville"


def test_extrait_exact_ou_presque():
    src = evidence.source_text(DEPOT)
    assert evidence.quote_found("je suis dans ma voiture en allant à Albertville", src)
    assert evidence.quote_found("Je suis dans ma voiture, en allant a Albertville", src)  # typo
    # one word changed: rejected on a short excerpt (a dropped "ne" would invert the meaning)...
    assert not evidence.quote_found("je suis dans la voiture en allant à Albertville", src)
    # ... tolerated on a long excerpt, where one word weighs little
    assert evidence.quote_found("on est au cinquième et je suis dans la voiture en allant "
                                "à Albertville dans quelques années", src)
    assert not evidence.quote_found("je suis dans le train pour Lyon ce matin", src)
    assert not evidence.quote_found("Oui", src)                                          # too short


def test_details_absents():
    src = evidence.source_text(DEPOT)
    ignore = evidence._dates_ignore([DEPOT], "Camille")
    # "7 ans" appears nowhere; Camille is the owner; 5 and 2026 are the deposit date
    assert evidence.unsupported_details(
        "Le 5 août 2026, Camille veut lui reparler dans 7 ans depuis Chambéry.", src, ignore
    ) == ["7", "Chambéry"]
    assert evidence.unsupported_details(
        "Il enregistre son premier mémo en allant à Albertville.", src, ignore) == []


def test_paliers_en_code():
    ok = {"content": "Premier mémo vocal, en voiture vers Albertville.", "source_event_ids": [6],
          "preuve": ["je suis dans ma voiture en allant à Albertville"]}
    assert evidence.check(ok, BY_ID, "Camille")["status"] == "ok"
    sans = {**ok, "preuve": []}
    assert evidence.check(sans, BY_ID)["status"] == "reject"
    faux = {**ok, "preuve": ["je pars demain en Islande avec LÃ©a"]}
    assert evidence.check(faux, BY_ID)["status"] == "reject"
    douteux = {**ok, "content": "Il veut lui reparler dans 7 ans.",
               "preuve": ["Dans quelques années, je voudrais pouvoir lui reparler"]}
    res = evidence.check(douteux, BY_ID, "Camille")
    assert res["status"] == "flag" and "7" in res["motifs"][0]


def _ask(answer):
    calls = []

    def ask(prompt):
        calls.append(prompt)
        return json.dumps(answer)
    return ask, calls


def test_relecture_des_seules_memoires_douteuses():
    sure = {"type": "episodic", "content": "Premier mémo vocal vers Albertville.",
            "source_event_ids": [6], "confidence": .9,
            "preuve": ["je suis dans ma voiture en allant à Albertville"]}
    douteuse = {"type": "semantic", "content": "Il veut lui reparler dans 7 ans.",
                "source_event_ids": [6], "confidence": .9,
                "preuve": ["Dans quelques années, je voudrais pouvoir lui reparler"]}
    inventee = {"type": "semantic", "content": "Il part en Islande.", "source_event_ids": [6],
                "preuve": ["je pars en Islande"]}

    ask, calls = _ask({"verdict": "partielle",
                       "correction": "Il veut lui reparler dans quelques années."})
    kept, rep = evidence.verify([sure, douteuse, inventee], [DEPOT, LOG], owner="Camille",
                                ask=ask, extract_json=json.loads)
    assert len(calls) == 1                      # only the doubtful one is re-read
    assert "MATERIAU-" in calls[0]              # and the re-read is fenced off
    assert [k["evidence"]["statut"] for k in kept] == ["verifiee", "corrigee"]
    assert kept[1]["content"] == "Il veut lui reparler dans quelques années."
    assert kept[1]["evidence"]["avant"] == "Il veut lui reparler dans 7 ans."
    assert {k: rep[k] for k in ("verifiees", "relues", "corrigees", "partielles",
                                "rejetees", "a_verifier")} == {
        "verifiees": 1, "relues": 1, "corrigees": 1, "partielles": 0,
        "rejetees": 1, "a_verifier": 0}
    # the outcome of each candidate is logged, without content
    assert rep["candidates"] == 3 and rep["signalees"] == 1
    assert rep["issues"] == {"ok": 1, "details_absents": 1, "relecture_partielle": 1,
                             "extrait_introuvable": 1}

    ask, _ = _ask({"verdict": "non_soutenue", "correction": None})
    kept, rep = evidence.verify([douteuse], [DEPOT], owner="Camille", ask=ask,
                                extract_json=json.loads)
    assert kept == [] and rep["rejetees"] == 1 and rep["non_soutenues"] == 1


def test_mode_frugal_sans_relecture():
    douteuse = {"type": "semantic", "content": "Il veut lui reparler dans 7 ans.",
                "source_event_ids": [6], "confidence": .9,
                "preuve": ["Dans quelques années, je voudrais pouvoir lui reparler"]}
    kept, rep = evidence.verify([douteuse], [DEPOT], owner="Camille")
    assert kept[0]["evidence"]["statut"] == "a_verifier"
    assert kept[0]["confidence"] == .5           # kept, but capped
    assert rep["a_verifier"] == 1


def test_transcription_isolee_dans_un_processus_enfant(monkeypatch, tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "consolidation"))
    import media_pipeline
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout='bruit\n{"text": "bonjour", "duration": 3}\n',
                                           stderr="")
    monkeypatch.setattr(media_pipeline.subprocess, "run", fake_run)
    assert media_pipeline.transcribe_isolated(tmp_path / "a.m4a") == ("bonjour", 3)
    assert seen["cmd"][1].endswith("media_pipeline.py") and seen["cmd"][2] == "--transcribe"

    monkeypatch.setattr(media_pipeline.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, -9, stdout="", stderr="Killed"))
    try:
        media_pipeline.transcribe_isolated(tmp_path / "a.m4a")
        raise AssertionError("a killed transcription must raise, so it is retried on the next cycle")
    except RuntimeError as exc:
        assert "Killed" in str(exc)


def test_pas_de_diarisation_sans_empreinte():
    from pathlib import Path
    from pensine import speakers

    class Conn:
        def execute(self, sql, params=None):
            class R:
                def fetchone(self_inner):
                    return None
            return R()
    assert speakers.identify_segments(Conn(), Path("x.wav")) is None


def test_palier2_tete_de_phrase_et_elision():
    src = "Ce matin j'ai couru dix kilomètres autour du lac avec Camille. Rendez-vous chez ACME."
    ign = evidence._dates_ignore([], "")
    # common word at the start of a sentence or bullet: not a proper noun
    assert evidence.unsupported_details("Course autour du lac. Stratégie : courir.", src, ign) == []
    assert evidence.unsupported_details("- Conséquence : il court.", src, ign) == []
    # ... but a name the source writes with a capital stays checked at the start
    assert evidence.unsupported_details("Camille court.", src, ign) == []
    # elided proper noun, straight or typographic apostrophe
    assert evidence.unsupported_details("Le tour du lac d'Annecy.", src, ign) == ["Annecy"]
    assert evidence.unsupported_details("Le tour du lac d’Annecy.", src, ign) == ["Annecy"]
    assert evidence.unsupported_details("L'Atelier de Lyon.", src, ign) == ["Atelier", "Lyon"]
    assert evidence.unsupported_details("Il cite l'ACME.", src, ign) == []
    # name between straight quotes
    assert evidence.unsupported_details("Le projet 'Orion' avance.", src, ign) == ["Orion"]


def test_palier2_heure_du_depot_toleree(monkeypatch):
    monkeypatch.setattr("pensine.config.TIMEZONE", "Europe/Paris")
    ev = {"occurred_at": "2026-08-05T18:29:30+00:00"}
    ign = evidence._dates_ignore([ev], "")
    assert {"18", "20", "29"} <= ign                    # UTC and local time (summer: +2)
    assert evidence.unsupported_details("Dépôt à 20 h 29, puis 7 km.", "", ign) == ["7"]
