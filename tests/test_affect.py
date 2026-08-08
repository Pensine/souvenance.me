"""Charge affective : les deux axes, et le droit de ne pas savoir."""

import pytest

from pensine import affect

_affect = affect.parse


# --- Le second axe sépare ce qu'un curseur bon/mauvais confondrait ----------

def test_chagrin_et_colere_ne_sont_pas_le_meme_souvenir():
    """Tous deux pénibles ; l'un est sourd, l'autre vif."""
    chagrin = affect.label(valence=-0.7, arousal=0.1)
    colere = affect.label(valence=-0.7, arousal=0.9)
    assert chagrin != colere
    assert "sourd" in chagrin and "intense" in colere


def test_serenite_et_euphorie_ne_sont_pas_le_meme_souvenir():
    assert affect.label(0.7, 0.1) != affect.label(0.7, 0.9)


def test_tension_neutre_reste_chargee():
    """Valence neutre mais forte activation : l'épisode compte quand même."""
    assert affect.label(0.0, 0.9) == "neutre, sous tension"


# --- « Non déterminé » n'est pas « neutre » --------------------------------

def test_charge_inconnue_ne_produit_aucun_libelle():
    assert affect.label(None, None) is None
    assert affect.describe(None, None) is None


def test_un_seul_axe_connu_reste_une_information():
    """Savoir que c'était intense sans savoir si c'était bon se conserve."""
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


# --- Extraction : refuser plutôt qu'inventer -------------------------------

@pytest.mark.parametrize("payload", [
    {},                                        # rien d'exprimé
    {"valence": None, "arousal": None},
    {"valence": "beaucoup", "arousal": "peu"},  # non numérique
    {"valence": -3.0, "arousal": 7.0},          # hors bornes
])
def test_affect_invalide_devient_none_jamais_zero(payload):
    """Un affect faux contamine le corpus ; l'absence, non."""
    assert _affect(payload) == (None, None)


def test_affect_valide_est_conserve():
    assert _affect({"valence": -0.5, "arousal": 0.8}) == (-0.5, 0.8)


def test_bornes_exactes_acceptees():
    assert _affect({"valence": -1.0, "arousal": 0.0}) == (-1.0, 0.0)
    assert _affect({"valence": 1.0, "arousal": 1.0}) == (1.0, 1.0)


def test_un_axe_valide_survit_a_l_autre_invalide():
    """Une valeur aberrante n'emporte pas celle qui tient."""
    assert _affect({"valence": -0.5, "arousal": 42}) == (-0.5, None)
