"""Affective load: the two axes, and the right not to know."""

import pytest

from pensine import affect

_affect = affect.parse


# --- The second axis separates what a good/bad slider would conflate --------

def test_chagrin_et_colere_ne_sont_pas_le_meme_souvenir():
    """Both painful; one is dull, the other sharp."""
    chagrin = affect.label(valence=-0.7, arousal=0.1)
    colere = affect.label(valence=-0.7, arousal=0.9)
    assert chagrin != colere
    assert "sourd" in chagrin and "intense" in colere


def test_serenite_et_euphorie_ne_sont_pas_le_meme_souvenir():
    assert affect.label(0.7, 0.1) != affect.label(0.7, 0.9)


def test_tension_neutre_reste_chargee():
    """Neutral valence but high arousal: the episode still counts."""
    assert affect.label(0.0, 0.9) == "neutre, sous tension"


# --- "Undetermined" is not "neutral" -------------------------------------

def test_charge_inconnue_ne_produit_aucun_libelle():
    assert affect.label(None, None) is None
    assert affect.describe(None, None) is None


def test_un_seul_axe_connu_reste_une_information():
    """Knowing it was intense without knowing whether it was good is worth keeping."""
    assert affect.label(None, 0.9) == "intense"
    assert affect.label(-0.8, None) == "pénible"


def test_neutre_explicite_se_distingue_de_l_inconnu():
    assert affect.describe(0.0, 0.0) is not None
    assert affect.describe(None, None) is None


def test_describe_porte_le_libelle_et_les_valeurs():
    out = affect.describe(-0.62, 0.81)
    assert out["ressenti"] == "pénible, intense"
    assert out["valence"] == -0.62 and out["intensite"] == 0.81


def test_describe_omet_l_axe_inconnu():
    out = affect.describe(None, 0.9)
    assert "valence" not in out and out["intensite"] == 0.9


# --- Extraction: refuse rather than invent ---------------------------------

@pytest.mark.parametrize("payload", [
    {},                                        # nothing expressed
    {"valence": None, "arousal": None},
    {"valence": "beaucoup", "arousal": "peu"},  # non-numeric
    {"valence": -3.0, "arousal": 7.0},          # out of bounds
])
def test_affect_invalide_devient_none_jamais_zero(payload):
    """A false affect contaminates the corpus; absence does not."""
    assert _affect(payload) == (None, None)


def test_affect_valide_est_conserve():
    assert _affect({"valence": -0.5, "arousal": 0.8}) == (-0.5, 0.8)


def test_bornes_exactes_acceptees():
    assert _affect({"valence": -1.0, "arousal": 0.0}) == (-1.0, 0.0)
    assert _affect({"valence": 1.0, "arousal": 1.0}) == (1.0, 1.0)


def test_un_axe_valide_survit_a_l_autre_invalide():
    """An outlier value does not take down the one that holds."""
    assert _affect({"valence": -0.5, "arousal": 42}) == (-0.5, None)
