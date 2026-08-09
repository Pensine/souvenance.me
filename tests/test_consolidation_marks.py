"""« Vu, rien à en tirer » doit rester une conclusion.

Sans marqueur, un événement stérile — un log vide, un test — revient chaque
nuit indéfiniment : un appel au modèle par nuit, pour rien, et un prompt qui
grossit du même déchet à chaque cycle.
"""

from pathlib import Path

from pensine import db


class _Conn:
    def __init__(self, produced_rows=None):
        self.produced_rows = produced_rows or []
        self.marks: list[tuple] = []
        self.queries: list[str] = []

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self.queries.append(flat)
        if "INSERT INTO consolidation_marks" in flat:
            self.marks.append(params)
        outer = self

        class _C:
            @staticmethod
            def fetchall():
                return outer.produced_rows

            @staticmethod
            def fetchone():
                return None
        return _C()


def test_un_evenement_sterile_est_marque_quand_meme():
    """Le cœur du correctif : ne rien produire n'est pas ne pas avoir été vu."""
    conn = _Conn(produced_rows=[])
    db.mark_examined(conn, [12], memory_ids=set())
    assert conn.marks == [(12, False)]


def test_un_evenement_productif_est_marque_comme_tel():
    conn = _Conn(produced_rows=[{"eid": 7}])
    db.mark_examined(conn, [7], memory_ids={101})
    assert conn.marks == [(7, True)]


def test_le_lot_distingue_les_productifs_des_steriles():
    """Un même cycle voit les deux ; le marqueur doit refléter chacun."""
    conn = _Conn(produced_rows=[{"eid": 7}])
    db.mark_examined(conn, [7, 12], memory_ids={101})
    assert conn.marks == [(7, True), (12, False)]


def test_aucun_evenement_ne_declenche_aucune_ecriture():
    conn = _Conn()
    db.mark_examined(conn, [], memory_ids=set())
    assert not conn.queries


def test_le_marquage_ne_casse_pas_sur_un_reexamen():
    """Rejouer un événement déjà marqué ne doit pas faire échouer le cycle."""
    conn = _Conn(produced_rows=[])
    db.mark_examined(conn, [12], memory_ids=set())
    assert "ON CONFLICT (event_id) DO NOTHING" in " ".join(conn.queries)


def test_la_requete_du_jour_exclut_les_evenements_marques():
    conn = _Conn()
    db.unconsolidated_events(conn)
    sql = " ".join(conn.queries)
    assert "consolidation_marks" in sql
    # second filet conservé pour les events d'avant les marqueurs
    assert "source_event_ids" in sql


def test_le_rejeu_complet_reste_possible():
    """La promesse centrale : un meilleur moteur relit la même vie.
    Elle n'est vraie que si le marqueur est jetable."""
    migration = (Path(__file__).resolve().parent.parent
                 / "db" / "migrations" / "008_consolidation_marks.sql").read_text()
    assert "DELETE FROM consolidation_marks" in migration
