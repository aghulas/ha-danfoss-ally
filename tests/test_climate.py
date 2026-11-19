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
        self.commanded: list[str] = []

    def group_of(self, head_id):
        return self._group_of.get(head_id)

    def note_commanded(self, head_ids):
        self.commanded.extend(head_ids)

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


async def test_room_setpoint_notes_group_heads_commanded():
    # R-3: after a setpoint write the room's member heads are marked for the per-device refresh.
    client = _FakeClient()
    cl, coord = _room_climate(_room(), client)
    coord.data = {
        "h1": head("h1"),
        "h2": head("h2"),
        "other": head("other"),
    }
    coord._group_of = {"h1": "77", "h2": "77", "other": "99"}
    await cl.async_set_temperature(**{ATTR_TEMPERATURE: 6.0})
    assert sorted(coord.commanded) == ["h1", "h2"]  # only this room's heads


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
    # TARGET_TEMPERATURE is declared so HA publishes the active setpoint; writes are refused.
    assert cl.supported_features == ClimateEntityFeature.TARGET_TEMPERATURE
    assert cl.current_temperature == 12.8
    assert cl.target_temperature == 6.0
    assert cl.hvac_action == HVACAction.HEATING
    assert cl.unique_id == dev.id


def test_head_climate_hvac_action_follows_work_state():
    # Real-hardware R-1: work_state NoHeat with a cracked valve (1 %) -> idle, not heating.
    dev = head(temperature=18.7, setpoint=14.0, valve_opening=1, state="NoHeat")
    coord = _FakeCoord(data={dev.id: dev})
    cl = DanfossHeadClimate(coord, dev.id)
    assert cl.hvac_action == HVACAction.IDLE


async def test_head_climate_publishes_active_setpoint_as_target(hass):
    # The active setpoint (DP 171, 14.0) is what the Danfoss app shows: HA must publish it as the
    # climate's `temperature` attribute, which it only does when TARGET_TEMPERATURE is declared.
    dev = head(setpoint=14.0, mode="leaving_home", setpoints={"comfort": 21.0, "setback": 14.0})
    coord = _FakeCoord(data={dev.id: dev})
    cl = DanfossHeadClimate(coord, dev.id)
    cl.hass = hass
    assert cl.target_temperature == 14.0
    assert cl.state_attributes[ATTR_TEMPERATURE] == 14.0


async def test_head_climate_refuses_setpoint_write():
    dev = head(setpoint=14.0)
    coord = _FakeCoord(data={dev.id: dev})
    cl = DanfossHeadClimate(coord, dev.id)
    with pytest.raises(HomeAssistantError, match="Read-only"):
        await cl.async_set_temperature(**{ATTR_TEMPERATURE: 20.0})


def test_head_climate_setpoint_attributes():
    dev = head(
        setpoint=14.0,
        mode="leaving_home",
        setpoints={"temp_set": 21.0, "comfort": 21.0, "setback": 14.0},
    )
    coord = _FakeCoord(data={dev.id: dev})
    attrs = DanfossHeadClimate(coord, dev.id).extra_state_attributes
    assert attrs["active_setpoint"] == 14.0
    assert attrs["setpoints"]["comfort"] == 21.0
    assert attrs["setpoints"]["temp_set"] == 21.0
    # Deprecated alias kept for existing automations: DP 16, NOT the active setpoint.
    assert attrs["setpoints"]["setpoint"] == 21.0
    assert dev.setpoints == {"temp_set": 21.0, "comfort": 21.0, "setback": 14.0}  # not mutated


def test_room_setpoint_attributes():
    room = _room(setpoint=14.0, setpoints={"temp_set": 21.0, "comfort": 21.0, "setback": 14.0})
    coord = _FakeCoord(rooms={"77": room})
    attrs = DanfossRoomClimate(coord, "77").extra_state_attributes
    assert attrs["active_setpoint"] == 14.0
    assert attrs["setpoints"]["setback"] == 14.0
    assert attrs["setpoints"]["setpoint"] == 21.0  # deprecated alias of temp_set


def test_setpoint_attributes_without_temp_set_has_no_alias():
    dev = head(setpoint=None, setpoints={"comfort": 21.0})
    coord = _FakeCoord(data={dev.id: dev})
    attrs = DanfossHeadClimate(coord, dev.id).extra_state_attributes
    assert "active_setpoint" not in attrs
    assert attrs["setpoints"] == {"comfort": 21.0}
