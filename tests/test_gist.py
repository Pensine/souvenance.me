"""Promotion épisodique → sémantique.

Ce qui est verrouillé ici, c'est la retenue du mécanisme : abstraire trop vite,
ou abstraire un groupe hétéroclite, fabrique une croyance fausse du système sur
la personne — et une croyance fausse se propage à tous les rappels suivants.
"""

from pensine import gist


# --- Seuils : ce qui empêche de fabriquer un motif ------------------------

def test_trois_occurrences_font_un_motif_deux_font_une_coincidence():
    assert gist.MIN_EPISODES >= 3


def test_on_laisse_le_temps_au_motif_de_se_former():
    """Abstraire le mois en cours fige une coïncidence en trait de caractère."""
    assert gist.MATURATION_DAYS >= 30


def test_le_groupe_reste_homogene():
    """Une distance trop permissive rassemblerait des épisodes sans rapport."""
    assert 0 < gist.MAX_DISTANCE <= 0.5


def test_l_abstraction_est_lente():
    """Comme dans un cerveau : quelques motifs par nuit, pas le corpus entier."""
    assert 0 < gist.MAX_CLUSTERS_PER_NIGHT <= 5
    assert gist.MAX_EPISODES >= gist.MIN_EPISODES


# --- Affect du gist : moyenne du vécu, jamais une invention ----------------

def test_la_charge_du_gist_est_la_moyenne_des_episodes():
    episodes = [
        {"valence": -0.6, "arousal": 0.8},
        {"valence": -0.4, "arousal": 0.6},
    ]
    assert gist._mean_affect(episodes) == (-0.5, 0.7)


def test_les_episodes_sans_affect_s_abstiennent_au_lieu_de_tirer_vers_le_neutre():
    """Un épisode dont on ignore la charge ne doit pas diluer celle des autres."""
    episodes = [
        {"valence": -0.8, "arousal": 0.9},
        {"valence": None, "arousal": None},
    ]
    assert gist._mean_affect(episodes) == (-0.8, 0.9)


def test_aucun_affect_connu_donne_aucun_affect():
    episodes = [{"valence": None, "arousal": None}] * 3
    assert gist._mean_affect(episodes) == (None, None)


def test_les_deux_axes_sont_moyennes_separement():
    """Connaître l'intensité sans la valence reste une information."""
    episodes = [
        {"valence": None, "arousal": 1.0},
        {"valence": 0.5, "arousal": 0.0},
    ]
    assert gist._mean_affect(episodes) == (0.5, 0.5)


# --- « Aucun motif » est une réponse valide, pas un échec -----------------

class _FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    def complete(self, prompt):
        return self.payload

    @staticmethod
    def extract_json(raw):
        import json
        return json.loads(raw)


def _abstract_with(monkeypatch, payload):
    fake = _FakeLLM(payload)
    monkeypatch.setattr(gist, "llm", fake)
    from datetime import datetime, timezone
    episodes = [{"content": "x", "valid_from": datetime.now(timezone.utc)}] * 3
    return gist._abstract(episodes, "X", "")


def test_gist_null_ne_produit_rien(monkeypatch):
    """Le modèle a le droit de ne voir aucun motif ; ne rien écrire est correct."""
    assert _abstract_with(monkeypatch, '{"gist": null, "confidence": 0.0}') is None


def test_gist_vide_ne_produit_rien(monkeypatch):
    assert _abstract_with(monkeypatch, '{"gist": "   ", "confidence": 0.9}') is None


def test_sortie_non_conforme_ne_produit_rien(monkeypatch):
    assert _abstract_with(monkeypatch, '["pas un objet"]') is None


def test_gist_valide_est_conserve(monkeypatch):
    out = _abstract_with(
        monkeypatch, '{"gist": "court tôt le matin", "confidence": 0.7}')
    assert out == {"content": "court tôt le matin", "confidence": 0.7}
