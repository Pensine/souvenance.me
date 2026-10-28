"""Links between memories: pair canonicalisation, reinforcement, forgetting.

Tests that touch live SQL are covered by the integration harness;
here we lock down the logic that decides *what* to link -- which, if badly tuned,
ends up linking everything to everything and emptying the word "associated" of its meaning.
"""

from pensine import links


# --- Canonical pairs: an association has no reading direction ---------------

def test_paire_toujours_ordonnee():
    """(b, a) and (a, b) are the same edge -- otherwise the network doubles up."""
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
    """Three memories from the same moment: three edges, not six."""
    assert links._pairs([1, 2, 3]) == [(1, 2), (1, 3), (2, 3)]


def test_ids_non_entiers_normalises():
    assert links._pairs(["3", 7.0]) == [(3, 7)]


# --- Settings: the network must remain informative -------------------------

def test_un_lien_nait_faible():
    """Otherwise a single co-occurrence would weigh as much as a habit."""
    assert links.INITIAL_STRENGTH < links.REINFORCE_GAIN
    assert links.INITIAL_STRENGTH > links.PRUNE_BELOW


def test_le_renforcement_est_borne():
    assert links.MAX_STRENGTH == 1.0


def test_l_oubli_des_liens_est_reel():
    """Without decay, everything ends up linked to everything."""
    assert 0.0 < links.DECAY_RATE < 1.0


def test_un_lien_jamais_reactive_finit_par_disparaitre():
    """A link set once and never replayed falls below the pruning threshold."""
    strength = links.INITIAL_STRENGTH
    nights = 0
    while strength >= links.PRUNE_BELOW and nights < 3650:
        strength *= links.DECAY_RATE
        nights += 1
    assert nights < 365, f"too slow to fade: {nights} nights"


def test_un_lien_renforce_survit_bien_plus_longtemps():
    """What is replayed holds; what is not replayed fades."""
    def nights_to_prune(start: float) -> int:
        s, n = start, 0
        while s >= links.PRUNE_BELOW and n < 3650:
            s *= links.DECAY_RATE
            n += 1
        return n

    assert nights_to_prune(links.MAX_STRENGTH) > 3 * nights_to_prune(links.INITIAL_STRENGTH)


def test_on_ne_suit_que_les_liens_qui_veulent_dire_quelque_chose():
    """The traversal threshold is above the initial strength: a single
    co-occurrence is not enough to bring a memory back."""
    assert links.MIN_STRENGTH_TO_FOLLOW > links.INITIAL_STRENGTH


def test_l_expansion_reste_bornee():
    """Beyond that, recall dilutes instead of getting richer."""
    assert 0 < links.DEFAULT_HOPS <= 10
