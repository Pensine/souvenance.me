"""Episodic -> semantic promotion.

What is locked down here is the restraint of the mechanism: abstracting too fast,
or abstracting a heterogeneous group, manufactures a false belief of the system about
the person -- and a false belief propagates to every later recall.
"""

from pensine import gist


# --- Thresholds: what prevents manufacturing a pattern ---------------------

def test_trois_occurrences_font_un_motif_deux_font_une_coincidence():
    assert gist.MIN_EPISODES >= 3


def test_on_laisse_le_temps_au_motif_de_se_former():
    """Abstracting the current month freezes a coincidence into a character trait."""
    assert gist.MATURATION_DAYS >= 30


def test_le_groupe_reste_homogene():
    """A distance that is too permissive would gather unrelated episodes."""
    assert 0 < gist.MAX_DISTANCE <= 0.5


def test_l_abstraction_est_lente():
    """As in a brain: a few patterns per night, not the whole corpus."""
    assert 0 < gist.MAX_CLUSTERS_PER_NIGHT <= 5
    assert gist.MAX_EPISODES >= gist.MIN_EPISODES


# --- Gist affect: average of what was lived, never an invention -------------

def test_la_charge_du_gist_est_la_moyenne_des_episodes():
    episodes = [
        {"valence": -0.6, "arousal": 0.8},
        {"valence": -0.4, "arousal": 0.6},
    ]
    assert gist._mean_affect(episodes) == (-0.5, 0.7)


def test_les_episodes_sans_affect_s_abstiennent_au_lieu_de_tirer_vers_le_neutre():
    """An episode whose load is unknown must not dilute the others' load."""
    episodes = [
        {"valence": -0.8, "arousal": 0.9},
        {"valence": None, "arousal": None},
    ]
    assert gist._mean_affect(episodes) == (-0.8, 0.9)


def test_aucun_affect_connu_donne_aucun_affect():
    episodes = [{"valence": None, "arousal": None}] * 3
    assert gist._mean_affect(episodes) == (None, None)


def test_les_deux_axes_sont_moyennes_separement():
    """Knowing the intensity without the valence is still information."""
    episodes = [
        {"valence": None, "arousal": 1.0},
        {"valence": 0.5, "arousal": 0.0},
    ]
    assert gist._mean_affect(episodes) == (0.5, 0.5)


# --- "No pattern" is a valid answer, not a failure -------------------------

class _FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    def complete(self, prompt, **kwargs):
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
    """The model is allowed to see no pattern; writing nothing is correct."""
    assert _abstract_with(monkeypatch, '{"gist": null, "confidence": 0.0}') is None


def test_gist_vide_ne_produit_rien(monkeypatch):
    assert _abstract_with(monkeypatch, '{"gist": "   ", "confidence": 0.9}') is None


def test_sortie_non_conforme_ne_produit_rien(monkeypatch):
    assert _abstract_with(monkeypatch, '["pas un objet"]') is None


def test_gist_valide_est_conserve(monkeypatch):
    out = _abstract_with(
        monkeypatch, '{"gist": "court tôt le matin", "confidence": 0.7}')
    assert out == {"content": "court tôt le matin", "confidence": 0.7}
