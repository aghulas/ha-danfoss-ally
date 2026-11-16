"""Tests de la plateforme climate (coordinateur canard, sans démarrer Home Assistant).

Cible la VRAIE voie-1a de consigne durable : écriture au niveau PIÈCE (groupe) selon le mode
courant (confort = DP 118 ; réduit = DP 109 + 119), via ``client.async_set_room_setpoint`` — pas
le DP du mode sur la tête (PR #8) ni le DP16, qui ne tiennent pas sur une tête programmée.
"""

import pytest
from homeassistant.components.climate import HVACAction
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.exceptions import HomeAssistantError

from custom_components.danfoss_ally_cloud.api import CloudWriteError
from custom_components.danfoss_ally_cloud.climate import DanfossClimate

from .common import tete


class _FakeClient:
    def __init__(self, set_room_exc=None):
        self.calls = []
        self._set_room_exc = set_room_exc

    async def async_set_room_setpoint(self, dev_id, dps, *, repush=True):
        self.calls.append((dev_id, dps, repush))
        if self._set_room_exc is not None:
            raise self._set_room_exc
        return "90000001"


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
    ("mode", "dps"),
    [
        ("at_home", {"118": 60}),  # confort
        ("leaving_home", {"109": 60, "119": 60}),  # réduit = les deux DP
    ],
)
async def test_ecrit_la_consigne_de_piece_selon_mode(mode, dps):
    dev = tete(mode=mode)
    client = _FakeClient()
    cl, coord = _climate(dev, client)
    await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert client.calls == [(dev.id, dps, True)]  # 6,0 °C -> 60 (dixièmes)
    assert coord.refreshed is True


@pytest.mark.parametrize("mode", ["pause", "holiday", "manual", None])
async def test_refuse_hors_confort_reduit(mode):
    dev = tete(mode=mode)
    client = _FakeClient()
    cl, coord = _climate(dev, client)
    with pytest.raises(HomeAssistantError):
        await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert client.calls == []
    assert coord.refreshed is False


async def test_refuse_modele_non_autorise():
    dev = tete(mode="at_home", product_id="inconnu")
    client = _FakeClient()
    cl, _ = _climate(dev, client)
    await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert client.calls == []  # produit hors garde-fou : aucune écriture


async def test_tete_non_groupee_remonte_une_erreur():
    dev = tete(mode="at_home")
    client = _FakeClient(set_room_exc=CloudWriteError("tête non groupée"))
    cl, coord = _climate(dev, client)
    with pytest.raises(HomeAssistantError):
        await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert coord.refreshed is False


async def test_sans_temperature_ne_fait_rien():
    dev = tete(mode="at_home")
    client = _FakeClient()
    cl, _ = _climate(dev, client)
    await cl.async_set_temperature()
    assert client.calls == []
