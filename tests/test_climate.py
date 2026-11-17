"""Climate platform tests (fake coordinator, without starting Home Assistant).

Model: one climate per ROOM (DanfossRoomClimate) writing the group setpoint per the current mode
(comfort = DP 118; setback = DP 109 + 119) via client.async_set_group_setpoint; ISOLATED heads keep
a read-only climate (DanfossHeadClimate, without TARGET_TEMPERATURE).
"""

import pytest
from homeassistant.components.climate import ClimateEntityFeature, HVACAction
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.exceptions import HomeAssistantError

from custom_components.danfoss_ally_cloud.api.client import CloudWriteError
from custom_components.danfoss_ally_cloud.api.rooms import RoomState
from custom_components.danfoss_ally_cloud.climate import DanfossHeadClimate, DanfossRoomClimate

from .common import head


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
        name="Salle",
        pid="03wvrwpv",
        head_count=2,
        online=True,
        temperature=19.5,
        setpoint=6.0,
        setpoints={"comfort": 6.0, "setback": 5.0},
        mode="at_home",
        heating=True,
        min_setpoint=5.0,
        max_setpoint=35.0,
    )
    base.update(kw)
    return RoomState(**base)


def _room_climate(room, client=None):
    coord = _FakeCoord(rooms={room.group_id: room}, client=client)
    return DanfossRoomClimate(coord, room.group_id), coord


# --- ROOM climate -----------------------------------------------------------------------------


def test_room_lecture_agregee():
    cl, _ = _room_climate(_room())
    assert cl.current_temperature == 19.5
    assert cl.target_temperature == 6.0
    assert cl.hvac_action == HVACAction.HEATING
    assert cl.available is True
    assert cl.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE
    assert cl.extra_state_attributes["head_count"] == 2
    assert cl.extra_state_attributes["mode"] == "comfort"


def test_room_unavailable_if_offline():
    cl, _ = _room_climate(_room(online=False))
    assert cl.available is False


def test_room_hvac_action_idle_and_none():
    cl_idle, _ = _room_climate(_room(heating=False))
    cl_none, _ = _room_climate(_room(heating=None))
    assert cl_idle.hvac_action == HVACAction.IDLE
    assert cl_none.hvac_action is None


@pytest.mark.parametrize(
    ("mode", "dps"),
    [
        ("at_home", {"118": 60}),  # comfort
        ("leaving_home", {"109": 60, "119": 60}),  # setback = both DPs
    ],
)
async def test_room_writes_setpoint_per_mode(mode, dps):
    client = _FakeClient()
    cl, coord = _room_climate(_room(mode=mode), client)
    await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert client.calls == [("77", "03wvrwpv", dps, True)]  # 6,0 °C -> 60
    assert coord.refreshed is True


@pytest.mark.parametrize("mode", ["pause", "holiday", "manual", None])
async def test_room_refuses_outside_comfort_setback(mode):
    client = _FakeClient()
    cl, coord = _room_climate(_room(mode=mode), client)
    with pytest.raises(HomeAssistantError):
        await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert client.calls == []
    assert coord.refreshed is False


async def test_room_unverified_product_read_only():
    client = _FakeClient()
    cl, _ = _room_climate(_room(pid="autre"), client)
    assert cl.supported_features == ClimateEntityFeature(0)
    await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert client.calls == []  # product outside the guard-rail: no write


async def test_room_erreur_cloud_remonte():
    client = _FakeClient(exc=CloudWriteError("refus"))
    cl, coord = _room_climate(_room(), client)
    with pytest.raises(HomeAssistantError):
        await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert coord.refreshed is False


async def test_room_without_temperature_does_nothing():
    client = _FakeClient()
    cl, _ = _room_climate(_room(), client)
    await cl.async_set_temperature()
    assert client.calls == []


# --- ISOLATED head climate (read-only) --------------------------------------------------------


def test_head_climate_lecture_seule():
    dev = head(temperature=12.8, setpoint=6.0, valve_opening=40)
    coord = _FakeCoord(data={dev.id: dev})
    cl = DanfossHeadClimate(coord, dev.id)
    assert cl.supported_features == ClimateEntityFeature(0)
    assert cl.current_temperature == 12.8
    assert cl.target_temperature == 6.0
    assert cl.hvac_action == HVACAction.HEATING
    assert cl.unique_id == dev.id
