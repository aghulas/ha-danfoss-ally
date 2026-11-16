"""Tests de la plateforme climate (coordinateur canard, sans démarrer Home Assistant).

Modèle : un climate par PIÈCE (DanfossRoomClimate) écrivant la consigne de groupe selon le mode
courant (confort = DP 118 ; réduit = DP 109 + 119) via client.async_set_group_setpoint ; les têtes
ISOLÉES gardent un climate en lecture seule (DanfossHeadClimate, sans TARGET_TEMPERATURE).
"""

import pytest
from homeassistant.components.climate import ClimateEntityFeature, HVACAction
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.exceptions import HomeAssistantError

from custom_components.danfoss_ally_cloud.api.client import CloudWriteError
from custom_components.danfoss_ally_cloud.api.rooms import RoomState
from custom_components.danfoss_ally_cloud.climate import DanfossHeadClimate, DanfossRoomClimate

from .common import tete


class _FakeClient:
    def __init__(self, exc=None):
        self.calls = []
        self._exc = exc

    async def async_set_group_setpoint(self, group_id, pid, dps, *, repush=True):
        self.calls.append((group_id, pid, dps, repush))
        if self._exc is not None:
            raise self._exc


class _FakeCoord:
    def __init__(self, rooms=None, data=None, client=None):
        self.rooms = rooms or {}
        self.data = data or {}
        self.client = client
        self.last_update_success = True
        self.refreshed = False
        self._group_of: dict[str, str] = {}

    def group_of(self, head_id):
        return self._group_of.get(head_id)

    async def async_request_refresh(self):
        self.refreshed = True


def _room(**kw) -> RoomState:
    base = dict(
        group_id="77",
        nom="Salle",
        pid="03wvrwpv",
        nb_tetes=2,
        en_ligne=True,
        temperature=19.5,
        consigne=6.0,
        consignes={"confort": 6.0, "reduit": 5.0},
        mode="at_home",
        chauffe=True,
        borne_basse=5.0,
        borne_haute=35.0,
    )
    base.update(kw)
    return RoomState(**base)


def _room_climate(room, client=None):
    coord = _FakeCoord(rooms={room.group_id: room}, client=client)
    return DanfossRoomClimate(coord, room.group_id), coord


# --- Climate de PIÈCE ---------------------------------------------------------------------------


def test_room_lecture_agregee():
    cl, _ = _room_climate(_room())
    assert cl.current_temperature == 19.5
    assert cl.target_temperature == 6.0
    assert cl.hvac_action == HVACAction.HEATING
    assert cl.available is True
    assert cl.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE
    assert cl.extra_state_attributes["nb_tetes"] == 2
    assert cl.extra_state_attributes["mode"] == "confort"


def test_room_indisponible_si_hors_ligne():
    cl, _ = _room_climate(_room(en_ligne=False))
    assert cl.available is False


def test_room_hvac_action_idle_et_none():
    cl_idle, _ = _room_climate(_room(chauffe=False))
    cl_none, _ = _room_climate(_room(chauffe=None))
    assert cl_idle.hvac_action == HVACAction.IDLE
    assert cl_none.hvac_action is None


@pytest.mark.parametrize(
    ("mode", "dps"),
    [
        ("at_home", {"118": 60}),  # confort
        ("leaving_home", {"109": 60, "119": 60}),  # réduit = les deux DP
    ],
)
async def test_room_ecrit_consigne_selon_mode(mode, dps):
    client = _FakeClient()
    cl, coord = _room_climate(_room(mode=mode), client)
    await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert client.calls == [("77", "03wvrwpv", dps, True)]  # 6,0 °C -> 60
    assert coord.refreshed is True


@pytest.mark.parametrize("mode", ["pause", "holiday", "manual", None])
async def test_room_refuse_hors_confort_reduit(mode):
    client = _FakeClient()
    cl, coord = _room_climate(_room(mode=mode), client)
    with pytest.raises(HomeAssistantError):
        await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert client.calls == []
    assert coord.refreshed is False


async def test_room_produit_non_verifie_lecture_seule():
    client = _FakeClient()
    cl, _ = _room_climate(_room(pid="autre"), client)
    assert cl.supported_features == ClimateEntityFeature(0)
    await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert client.calls == []  # produit hors garde-fou : aucune écriture


async def test_room_erreur_cloud_remonte():
    client = _FakeClient(exc=CloudWriteError("refus"))
    cl, coord = _room_climate(_room(), client)
    with pytest.raises(HomeAssistantError):
        await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert coord.refreshed is False


async def test_room_sans_temperature_ne_fait_rien():
    client = _FakeClient()
    cl, _ = _room_climate(_room(), client)
    await cl.async_set_temperature()
    assert client.calls == []


# --- Climate de tête ISOLÉE (lecture seule) -----------------------------------------------------


def test_head_climate_lecture_seule():
    dev = tete(temperature=12.8, consigne=6.0, ouverture_vanne=40)
    coord = _FakeCoord(data={dev.id: dev})
    cl = DanfossHeadClimate(coord, dev.id)
    assert cl.supported_features == ClimateEntityFeature(0)
    assert cl.current_temperature == 12.8
    assert cl.target_temperature == 6.0
    assert cl.hvac_action == HVACAction.HEATING
    assert cl.unique_id == dev.id
