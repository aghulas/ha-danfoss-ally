"""Tests de la plateforme climate (coordinateur canard, sans démarrer Home Assistant).

Cible le correctif d'écriture de consigne : on écrit le DP du RÉGLAGE DU MODE ACTIF
(at_home_setting…), pas le DP16 temp_set qui ne tient pas sur une tête programmée.
"""

import pytest
from homeassistant.components.climate import HVACAction
from homeassistant.const import ATTR_TEMPERATURE

from custom_components.danfoss_ally_cloud.climate import DanfossClimate

from .common import tete


class _FakeClient:
    def __init__(self):
        self.calls = []

    async def async_write_setting(self, dev_id, pid, dps):
        self.calls.append((dev_id, pid, dps))


class _FakeCoord:
    def __init__(self, data, client=None, last_update_success=True):
        self.data = data
        self.client = client
        self.last_update_success = last_update_success
        self.refreshed = False

    async def async_request_refresh(self):
        self.refreshed = True


def _climate(dev, client=None):
    coord = _FakeCoord({dev.id: dev}, client=client)
    return DanfossClimate(coord, dev.id), coord


async def test_lecture_temperature_et_consigne():
    dev = tete(temperature=12.8, consigne=6.0)
    cl, _ = _climate(dev)
    assert cl.current_temperature == 12.8
    assert cl.target_temperature == 6.0


async def test_hvac_action_selon_vanne():
    cl_chauffe, _ = _climate(tete(ouverture_vanne=40))
    cl_idle, _ = _climate(tete(ouverture_vanne=0))
    assert cl_chauffe.hvac_action == HVACAction.HEATING
    assert cl_idle.hvac_action == HVACAction.IDLE


@pytest.mark.parametrize(
    ("mode", "dp"),
    [
        ("at_home", "118"),  # confort
        ("leaving_home", "119"),  # réduit
        ("pause", "120"),
        ("holiday", "121"),  # vacances
        ("manual", "114"),
    ],
)
async def test_ecrit_le_dp_du_mode_actif(mode, dp):
    dev = tete(mode=mode)
    client = _FakeClient()
    cl, coord = _climate(dev, client)
    await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert client.calls == [(dev.id, dev.product_id, {dp: 60})]  # 6,0 °C -> 60
    assert coord.refreshed is True


async def test_repli_sur_dp16_si_mode_inconnu():
    dev = tete(mode=None)
    client = _FakeClient()
    cl, _ = _climate(dev, client)
    await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert client.calls == [(dev.id, dev.product_id, {"16": 60})]


async def test_refuse_modele_non_autorise():
    dev = tete(mode="at_home", product_id="inconnu")
    client = _FakeClient()
    cl, _ = _climate(dev, client)
    await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert client.calls == []  # produit hors garde-fou : aucune écriture


async def test_sans_temperature_ne_fait_rien():
    dev = tete(mode="at_home")
    client = _FakeClient()
    cl, _ = _climate(dev, client)
    await cl.async_set_temperature()
    assert client.calls == []
