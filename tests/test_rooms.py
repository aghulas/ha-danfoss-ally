"""Tests de l'agrégation d'une pièce (pur, sans réseau ni Home Assistant)."""

from custom_components.danfoss_ally_cloud.api.rooms import Piece, aggregate_room

from .common import tete


def _piece(membre_ids):
    return Piece("77", "Salle", "03wvrwpv", "1", tuple(membre_ids))


def test_aggregate_moyenne_et_chauffe():
    m1 = tete("a", "A", temperature=20.0, ouverture_vanne=0, mode="at_home", consigne=6.0)
    m2 = tete("b", "B", temperature=22.0, ouverture_vanne=30, mode="at_home", consigne=6.0)
    r = aggregate_room(_piece(["a", "b"]), [m1, m2])
    assert r.temperature == 21.0  # moyenne des têtes en ligne
    assert r.en_ligne is True
    assert r.chauffe is True  # m2 ouvre sa vanne
    assert r.consigne == 6.0
    assert r.mode == "at_home"
    assert r.nb_tetes == 2


def test_aggregate_chauffe_false_si_aucune_vanne():
    m = tete("a", "A", ouverture_vanne=0)
    assert aggregate_room(_piece(["a"]), [m]).chauffe is False


def test_aggregate_ignore_hors_ligne_pour_la_moyenne():
    m1 = tete("a", "A", temperature=10.0, en_ligne=False)
    m2 = tete("b", "B", temperature=20.0, en_ligne=True)
    r = aggregate_room(_piece(["a", "b"]), [m1, m2])
    assert r.temperature == 20.0  # seule la tête en ligne compte


def test_aggregate_toutes_hors_ligne():
    m = tete("a", "A", temperature=20.0, en_ligne=False)
    r = aggregate_room(_piece(["a"]), [m])
    assert r.en_ligne is False
    assert r.temperature is None
    assert r.chauffe is None


def test_aggregate_sans_membre_present():
    r = aggregate_room(_piece(["a", "b"]), [])
    assert r.en_ligne is False and r.temperature is None and r.consigne is None
    assert r.nb_tetes == 2  # taille déclarée de la pièce, même sans membre présent
