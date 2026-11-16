"""Tests de fumée : l'intégration s'importe et les constantes tiennent."""

from custom_components.danfoss_ally_cloud import const


def test_domain():
    assert const.DOMAIN == "danfoss_ally_cloud"


def test_dp_pieges():
    # Pièges repris du schéma officiel : à ne pas inverser.
    assert const.DP_UPPER_TEMP == 18  # borne haute, pas la consigne
    assert const.DP_SETPOINT == 171  # consigne en cours
    assert const.DP_PREHEAT == 1
    assert const.ZB_ATTR_PROGRAMMING_MODE == 0x0025


def test_platforms_non_vide():
    assert "climate" in const.PLATFORMS
