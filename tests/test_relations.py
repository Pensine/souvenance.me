"""State of relationships: what shifts between two people, and in which direction.

What is locked down here: the two axes are not conflated, an insignificant
variation is not announced as an evolution, and an empty state does not enter
the history of the relationship.
"""

from datetime import datetime, timezone

from pensine import relations


def _state(closeness=None, valence=None, note=None, when=None):
    return {"closeness": closeness, "valence": valence, "note": note,
            "valid_from": when or datetime(2026, 1, 1, tzinfo=timezone.utc),
            "valid_to": None}


# --- Two axes, because a single one would conflate opposite situations -----

def test_proche_et_tendu_n_est_pas_lointain_et_chaleureux():
    """A family and an old friend lost touch with: a single slider would
    make them equivalent when they have nothing to do with each other."""
    famille = _state(closeness=0.9, valence=-0.5)
    vieil_ami = _state(closeness=0.2, valence=0.8)
    assert famille["closeness"] != vieil_ami["closeness"]
    assert famille["valence"] != vieil_ami["valence"]


def test_les_deux_axes_evoluent_independamment():
    """A relationship can grow closer while becoming strained -- it is even common."""
    now, before = _state(0.8, -0.4), _state(0.3, 0.3)
    out = relations.trajectory([now, before])
    assert "rapprochée" in out["evolution"] and "tendue" in out["evolution"]


# --- An insignificant variation is not news --------------------------------

def test_un_fremissement_n_est_pas_une_evolution():
    """Two consolidation nights never give the same figure;
    reporting this noise as a change would be lying."""
    assert relations.trajectory([_state(0.52, 0.3), _state(0.50, 0.3)]) is None


def test_un_mouvement_franc_est_signale():
    out = relations.trajectory([_state(0.2, 0.0), _state(0.8, 0.0)])
    assert out is not None and "distendue" in out["evolution"]


def test_le_seuil_laisse_passer_le_reel_et_arrete_le_bruit():
    assert 0.05 < relations.SIGNIFICANT_DELTA < 0.5


def test_un_seul_etat_ne_donne_aucune_trajectoire():
    """Without a past, there is no evolution -- only a state."""
    assert relations.trajectory([_state(0.5, 0.5)]) is None
    assert relations.trajectory([]) is None
    assert relations.trajectory(None) is None


def test_un_axe_inconnu_n_invente_pas_de_mouvement():
    assert relations.trajectory([_state(0.9, None), _state(0.2, None)]) is not None
    assert relations.trajectory([_state(None, None), _state(None, None)]) is None


def test_le_refroidissement_se_dit_dans_le_bon_sens():
    """The exact case requested: a closeness that is cooling."""
    out = relations.trajectory([_state(0.3, -0.4), _state(0.8, 0.5)])
    assert "distendue" in out["evolution"] and "tendue" in out["evolution"]


# --- Refuse rather than invent ---------------------------------------------

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
    """It would teach nothing and take up a line in the history."""
    conn = _Conn()
    assert relations.set_state(conn, 1, closeness=None, valence=None) is None
    assert not conn.queries


def test_un_seul_axe_suffit_a_enregistrer():
    conn = _Conn()
    assert relations.set_state(conn, 1, valence=0.7) == 1


def test_le_nouvel_etat_ferme_le_precedent():
    """Without closing, two current states would coexist."""
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
    """We do not invent a person to assign them a climate."""
    conn = _Conn()
    assert relations.ingest(conn, [{"entity": "fantôme", "valence": 0.5}], {}, []) == 0
    assert not conn.queries
