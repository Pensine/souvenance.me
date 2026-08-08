"""Liaisons entre souvenirs : canonisation des paires, renforcement, oubli.

Les tests qui portent sur SQL vivant sont couverts par le harnais d'intégration ;
ici on verrouille la logique qui décide *quoi* lier — c'est elle qui, mal réglée,
finit par tout relier à tout et vide le mot « associé » de son sens.
"""

from pensine import links


# --- Paires canoniques : une association n'a pas de sens de lecture --------

def test_paire_toujours_ordonnee():
    """(b, a) et (a, b) sont la même arête — sinon le réseau se dédouble."""
    assert links._pairs([7, 3]) == [(3, 7)]
    assert links._pairs([3, 7]) == [(3, 7)]


def test_pas_de_boucle_sur_soi():
    assert links._pairs([5, 5]) == []


def test_doublons_ecartes():
    assert links._pairs([2, 9, 2]) == [(2, 9)]


def test_une_seule_memoire_ne_produit_aucun_lien():
    assert links._pairs([42]) == []
    assert links._pairs([]) == []


def test_toutes_les_paires_d_un_episode():
    """Trois mémoires d'un même moment : trois arêtes, pas six."""
    assert links._pairs([1, 2, 3]) == [(1, 2), (1, 3), (2, 3)]


def test_ids_non_entiers_normalises():
    assert links._pairs(["3", 7.0]) == [(3, 7)]


# --- Réglages : le réseau doit rester informatif ---------------------------

def test_un_lien_nait_faible():
    """Sinon une co-occurrence unique pèserait autant qu'une habitude."""
    assert links.INITIAL_STRENGTH < links.REINFORCE_GAIN
    assert links.INITIAL_STRENGTH > links.PRUNE_BELOW


def test_le_renforcement_est_borne():
    assert links.MAX_STRENGTH == 1.0


def test_l_oubli_des_liens_est_reel():
    """Sans décroissance, tout finit relié à tout."""
    assert 0.0 < links.DECAY_RATE < 1.0


def test_un_lien_jamais_reactive_finit_par_disparaitre():
    """Un lien posé une fois et jamais rejoué passe sous le seuil d'élagage."""
    strength = links.INITIAL_STRENGTH
    nights = 0
    while strength >= links.PRUNE_BELOW and nights < 3650:
        strength *= links.DECAY_RATE
        nights += 1
    assert nights < 365, f"trop lent à s'effacer : {nights} nuits"


def test_un_lien_renforce_survit_bien_plus_longtemps():
    """Ce qu'on rejoue tient ; ce qu'on ne rejoue pas s'efface."""
    def nights_to_prune(start: float) -> int:
        s, n = start, 0
        while s >= links.PRUNE_BELOW and n < 3650:
            s *= links.DECAY_RATE
            n += 1
        return n

    assert nights_to_prune(links.MAX_STRENGTH) > 3 * nights_to_prune(links.INITIAL_STRENGTH)


def test_on_ne_suit_que_les_liens_qui_veulent_dire_quelque_chose():
    """Le seuil de parcours est au-dessus de la force initiale : une
    co-occurrence unique ne suffit pas à ramener un souvenir."""
    assert links.MIN_STRENGTH_TO_FOLLOW > links.INITIAL_STRENGTH


def test_l_expansion_reste_bornee():
    """Au-delà, le rappel se dilue au lieu de s'enrichir."""
    assert 0 < links.DEFAULT_HOPS <= 10
