"""État des liens : ce qui bouge entre deux personnes, et dans quel sens.

Ce qui est verrouillé ici : les deux axes ne se confondent pas, une variation
insignifiante n'est pas annoncée comme une évolution, et un état vide n'entre
pas dans l'histoire de la relation.
"""

from datetime import datetime, timezone

from pensine import relations


def _state(closeness=None, valence=None, note=None, when=None):
    return {"closeness": closeness, "valence": valence, "note": note,
            "valid_from": when or datetime(2026, 1, 1, tzinfo=timezone.utc),
            "valid_to": None}


# --- Deux axes, parce qu'un seul confondrait des situations opposées -------

def test_proche_et_tendu_n_est_pas_lointain_et_chaleureux():
    """Une famille et un vieil ami perdu de vue : un curseur unique les
    rendrait équivalents alors qu'ils n'ont rien à voir."""
    famille = _state(closeness=0.9, valence=-0.5)
    vieil_ami = _state(closeness=0.2, valence=0.8)
    assert famille["closeness"] != vieil_ami["closeness"]
    assert famille["valence"] != vieil_ami["valence"]


def test_les_deux_axes_evoluent_independamment():
    """Une relation peut se rapprocher en se tendant — c'est même fréquent."""
    now, before = _state(0.8, -0.4), _state(0.3, 0.3)
    out = relations.trajectory([now, before])
    assert "rapprochée" in out["evolution"] and "tendue" in out["evolution"]


# --- Une variation insignifiante n'est pas une nouvelle -------------------

def test_un_fremissement_n_est_pas_une_evolution():
    """Deux nuits de consolidation ne donnent jamais le même chiffre ;
    signaler ce bruit comme un changement serait mentir."""
    assert relations.trajectory([_state(0.52, 0.3), _state(0.50, 0.3)]) is None


def test_un_mouvement_franc_est_signale():
    out = relations.trajectory([_state(0.2, 0.0), _state(0.8, 0.0)])
    assert out is not None and "distendue" in out["evolution"]


def test_le_seuil_laisse_passer_le_reel_et_arrete_le_bruit():
    assert 0.05 < relations.SIGNIFICANT_DELTA < 0.5


def test_un_seul_etat_ne_donne_aucune_trajectoire():
    """Sans passé, il n'y a pas d'évolution — seulement un état."""
    assert relations.trajectory([_state(0.5, 0.5)]) is None
    assert relations.trajectory([]) is None
    assert relations.trajectory(None) is None


def test_un_axe_inconnu_n_invente_pas_de_mouvement():
    assert relations.trajectory([_state(0.9, None), _state(0.2, None)]) is not None
    assert relations.trajectory([_state(None, None), _state(None, None)]) is None


def test_le_refroidissement_se_dit_dans_le_bon_sens():
    """Le cas exact demandé : une proximité qui se refroidit."""
    out = relations.trajectory([_state(0.3, -0.4), _state(0.8, 0.5)])
    assert "distendue" in out["evolution"] and "tendue" in out["evolution"]


# --- Refuser plutôt qu'inventer -------------------------------------------

class _Conn:
    def __init__(self):
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append(" ".join(sql.split()))

        class _C:
            @staticmethod
            def fetchone():
                return {"id": 1}
        return _C()


def test_un_etat_sans_aucun_axe_n_est_pas_enregistre():
    """Il n'apprendrait rien et occuperait une ligne dans l'histoire."""
    conn = _Conn()
    assert relations.set_state(conn, 1, closeness=None, valence=None) is None
    assert not conn.queries


def test_un_seul_axe_suffit_a_enregistrer():
    conn = _Conn()
    assert relations.set_state(conn, 1, valence=0.7) == 1


def test_le_nouvel_etat_ferme_le_precedent():
    """Sans fermeture, deux états courants coexisteraient."""
    conn = _Conn()
    relations.set_state(conn, 1, closeness=0.5)
    assert any("UPDATE relation_states SET valid_to" in q for q in conn.queries)


def test_valeurs_hors_bornes_refusees():
    assert relations._clamp(3.0, 0.0, 1.0) is None
    assert relations._clamp(-2.0, -1.0, 1.0) is None
    assert relations._clamp("beaucoup", 0.0, 1.0) is None
    assert relations._clamp(True, 0.0, 1.0) is None


def test_valeurs_valides_conservees():
    assert relations._clamp(0.0, 0.0, 1.0) == 0.0
    assert relations._clamp(-1.0, -1.0, 1.0) == -1.0


def test_entite_inconnue_ignoree():
    """On n'invente pas une personne pour lui attribuer un climat."""
    conn = _Conn()
    assert relations.ingest(conn, [{"entity": "fantôme", "valence": 0.5}], {}, []) == 0
    assert not conn.queries
