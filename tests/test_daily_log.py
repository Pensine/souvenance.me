from pensine.mcp_server import _parse_daily_log


def test_quatre_champs_en_lignes():
    t = ("Fait du jour : signature du compromis.\n"
         "Décision : reporter le chantier au printemps.\n"
         "État : soulagé mais vidé.\n"
         "Cap de demain : appeler l'artisan.")
    f = _parse_daily_log(t)
    assert f["fait"] == "signature du compromis."
    assert f["decision"] == "reporter le chantier au printemps."
    assert f["etat"] == "soulagé mais vidé."
    assert f["cap"] == "appeler l'artisan."


def test_transcript_libre_ne_casse_pas():
    f = _parse_daily_log("journée sans structure, juste un vrac de pensées")
    assert set(f) == {"fait", "decision", "etat", "cap"}  # champs présents, vides
