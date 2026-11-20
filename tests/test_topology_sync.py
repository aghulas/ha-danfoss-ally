"""Runtime topology sync: entities follow rooms and memberships without an entry reload.

The "add" side (hass harness, synthetic data): a room that appears, a head that becomes isolated,
and the isolated-head numbers when the cloud-MQTT write option is on. The retirement rules
(``DanfossCoordinator.room_retired``) are covered in ``test_setup.py``.
"""

from unittest.mock import AsyncMock, patch

import paho.mqtt.client as paho
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud.api import GatewayKey
from custom_components.danfoss_ally_cloud.const import (
    CONF_ENABLE_CLOUD_MQTT,
    DATA_COORDINATOR,
    DOMAIN,
)
from custom_components.danfoss_ally_cloud.coordinator import DanfossCoordinator

from .common import ENTRY_DATA, FakeCloudClient, head
from .test_mqtt_client import _FakePaho

_ROOM = [{"group_id": 77, "name": "Salle", "pid": "03wvrwpv", "head_count": 2}]
_GW = {"gw-1": GatewayKey("gw-1", "GW", "0123456789abcdef", ip="10.0.0.1")}
_ROOM_NUMBERS = ("77_comfort_setpoint", "77_setback_setpoint")
_HEAD_NUMBERS = (
    "upper_bound",
    "lower_bound",
    "comfort_setpoint",
    "setback_setpoint",
    "pause_setpoint",
)


async def _setup(hass: HomeAssistant, fake: FakeCloudClient, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr", options=options or {}
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value=_GW),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator: DanfossCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    return entry, coordinator, er.async_get(hass)


async def _new_topology(hass, coordinator, fake, groups, members):
    """The cloud topology changed (as after a room write): next refresh reads it again."""
    fake._groups = groups
    fake._members = members
    coordinator.invalidate_topology()
    await coordinator.async_refresh()
    await hass.async_block_till_done()


def _climate(registry, unique_id):
    return registry.async_get_entity_id("climate", DOMAIN, unique_id)


def _number(registry, unique_id):
    return registry.async_get_entity_id("number", DOMAIN, unique_id)


async def test_room_appearing_at_runtime_gets_its_entities(hass: HomeAssistant):
    """Two isolated heads are put in a new room: the room gets its climate and both setpoint
    numbers, with live states, and the heads lose their own climate."""
    fake = FakeCloudClient(devices=[head("a", "A"), head("b", "B")])
    entry, coordinator, registry = await _setup(hass, fake)
    assert _climate(registry, "a") is not None and _climate(registry, "b") is not None
    assert _climate(registry, "77") is None
    assert all(_number(registry, uid) is None for uid in _ROOM_NUMBERS)

    await _new_topology(hass, coordinator, fake, _ROOM, {"77": ["a", "b"]})

    room_climate = _climate(registry, "77")
    assert room_climate is not None
    # Really added to Home Assistant (a state), not only reserved in the registry.
    assert hass.states.get(room_climate) is not None
    for uid in _ROOM_NUMBERS:
        entity_id = _number(registry, uid)
        assert entity_id is not None and hass.states.get(entity_id) is not None
    assert _climate(registry, "a") is None and _climate(registry, "b") is None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_room_appearing_twice_is_added_once(hass: HomeAssistant):
    """Later updates with the same topology add nothing more (no duplicate-entity error)."""
    fake = FakeCloudClient(devices=[head("a", "A"), head("b", "B")])
    entry, coordinator, registry = await _setup(hass, fake)
    await _new_topology(hass, coordinator, fake, _ROOM, {"77": ["a", "b"]})
    room_climate = _climate(registry, "77")

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert _climate(registry, "77") == room_climate
    assert len([e for e in registry.entities.values() if e.unique_id == "77"]) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_head_becoming_isolated_gets_a_climate(hass: HomeAssistant):
    """A head detached from its room, the room living on: the head gets its own climate, the
    room keeps its entities, and the head still in the room gets none."""
    fake = FakeCloudClient(
        devices=[head("a", "A"), head("b", "B"), head("c", "C")],
        groups=_ROOM,
        members={"77": ["a", "b", "c"]},
    )
    entry, coordinator, registry = await _setup(hass, fake)
    room_climate = _climate(registry, "77")
    assert room_climate is not None
    assert all(_climate(registry, h) is None for h in ("a", "b", "c"))

    await _new_topology(hass, coordinator, fake, _ROOM, {"77": ["a", "b"]})

    head_climate = _climate(registry, "c")
    assert head_climate is not None and hass.states.get(head_climate) is not None
    assert _climate(registry, "a") is None and _climate(registry, "b") is None
    assert _climate(registry, "77") == room_climate
    assert all(_number(registry, uid) is not None for uid in _ROOM_NUMBERS)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_isolated_head_numbers_follow_with_cloud_mqtt(hass: HomeAssistant, monkeypatch):
    """With ``enable_cloud_mqtt`` on, a head leaving its room gets its bounds and setpoint numbers
    at runtime, and loses them when it joins a room again."""
    _FakePaho.instances.clear()
    monkeypatch.setattr(paho, "Client", _FakePaho)
    fake = FakeCloudClient(
        devices=[head("a", "A"), head("b", "B"), head("c", "C")],
        groups=_ROOM,
        members={"77": ["a", "b", "c"]},
    )
    entry, coordinator, registry = await _setup(hass, fake, {CONF_ENABLE_CLOUD_MQTT: True})
    client = _FakePaho.instances[-1]
    client.on_connect(client, None, None, 0)
    assert all(_number(registry, f"c_{key}") is None for key in _HEAD_NUMBERS)

    await _new_topology(hass, coordinator, fake, _ROOM, {"77": ["a", "b"]})

    for key in _HEAD_NUMBERS:
        entity_id = _number(registry, f"c_{key}")
        assert entity_id is not None, key
        assert hass.states.get(entity_id) is not None, key
    # Heads still in the room get none.
    assert all(_number(registry, f"a_{key}") is None for key in _HEAD_NUMBERS)

    await _new_topology(hass, coordinator, fake, _ROOM, {"77": ["a", "b", "c"]})

    assert all(_number(registry, f"c_{key}") is None for key in _HEAD_NUMBERS)
    assert _climate(registry, "c") is None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_no_isolated_head_number_at_runtime_without_cloud_mqtt(hass: HomeAssistant):
    """Option off (the default): a head becoming isolated gets its climate and no number."""
    fake = FakeCloudClient(
        devices=[head("a", "A"), head("b", "B"), head("c", "C")],
        groups=_ROOM,
        members={"77": ["a", "b", "c"]},
    )
    entry, coordinator, registry = await _setup(hass, fake)

    await _new_topology(hass, coordinator, fake, _ROOM, {"77": ["a", "b"]})

    assert _climate(registry, "c") is not None
    assert all(_number(registry, f"c_{key}") is None for key in _HEAD_NUMBERS)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
