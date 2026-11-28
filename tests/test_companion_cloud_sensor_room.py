"""A cloud room sensor named by ``danfoss2mqtt`` lands in its room.

End to end through the Companion: ``bridge/devices`` + ``bridge/rooms`` -> the adapter's
``sensor_rooms`` -> the side panel's overview payload. An isolated head (no schedule group) names
its room's sensor in ``bridge/devices`` (``danfoss.room_sensor``) instead, and the sensor lands in
the head's single-head room. ``danfoss2mqtt`` publishes both only from a proven link (the account's
device -> Tuya room map, ``docs/companion-contract.md``); a sensor it does not name stays without a
room, whatever its name. Synthetic data only.
"""

from __future__ import annotations

import json

import pytest
from homeassistant.core import HomeAssistant

from custom_components.danfoss_ally_cloud import ops_views
from custom_components.danfoss_ally_cloud.api import DanfossDevice, encode_z2m_descriptor
from custom_components.danfoss_ally_cloud.companion_adapter import build_companion_store
from custom_components.danfoss_ally_cloud.companion_rooms import CompanionRoomManager
from custom_components.danfoss_ally_cloud.mqtt_companion import MqttCompanionCoordinator


def _head(dev_id: str, name: str) -> DanfossDevice:
    return DanfossDevice(
        id=dev_id,
        name=name,
        category="head",
        product_id="03wvrwpv",
        online=True,
        temperature=19.5,
        setpoint=20.0,
        mode="at_home",
    )


def _sensor(dev_id: str, name: str) -> DanfossDevice:
    return DanfossDevice(
        id=dev_id,
        name=name,
        category="sensor",
        product_id="mxzo5rhf",
        online=True,
        temperature=20.2,
        humidity=48.0,
    )


@pytest.mark.asyncio
async def test_cloud_sensor_named_by_bridge_rooms_is_placed_in_its_room(
    hass: HomeAssistant,
) -> None:
    comp = MqttCompanionCoordinator(hass, ("danfoss2mqtt",))
    head = _head("h-1", "X-0 Room 1 head")
    linked = _sensor("s-1", "X-0 Room 1 sensor")
    # Same name as the room, but not named by bridge/rooms: never placed by its name.
    unlinked = _sensor("s-2", "X-0 Room 1")
    comp.process_mqtt_message("danfoss2mqtt/bridge/state", '{"state": "online"}')
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/devices",
        json.dumps([encode_z2m_descriptor(d) for d in (head, linked, unlinked)]),
    )
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/rooms",
        json.dumps(
            [
                {
                    "group_id": "g-1",
                    "name": "X-0 Room 1",
                    "home_id": "home-1",
                    "members": ["h-1"],
                    "head_count": 1,
                    "online": True,
                    "temperature": 19.5,
                    "sensor": "s-1",
                },
                {
                    "group_id": "g-2",
                    "name": "X-0 Room 2",
                    "home_id": "home-1",
                    "members": [],
                    "head_count": 0,
                    "sensor": None,  # the bridge found no proven sensor for this room
                },
            ]
        ),
    )

    store = build_companion_store(comp, CompanionRoomManager(comp))
    view = store["coordinator"]
    assert view.sensor_rooms() == {"s-1": "g-1"}

    overview = ops_views.overview_payload(store)
    placed = {s["device_id"]: s["room_id"] for home in overview["homes"] for s in home["sensors"]}
    assert placed == {"s-1": "g-1", "s-2": None}


def _descriptor(dev: DanfossDevice, **ext: object) -> dict:
    desc = encode_z2m_descriptor(dev)
    desc["danfoss"].update(ext)
    return desc


@pytest.mark.asyncio
async def test_cloud_sensor_named_by_an_isolated_head_lands_in_its_single_head_room(
    hass: HomeAssistant,
) -> None:
    comp = MqttCompanionCoordinator(hass, ("danfoss2mqtt",))
    grouped = _head("h-1", "X-0 Room 1 head")
    isolated = _head("h-9", "X-0 Office")
    sensor = _sensor("s-9", "X-0 Office sensor")
    # A grouped head that names a sensor anyway: ignored, a grouped head's room is its group's.
    stray = _sensor("s-8", "X-0 Room 1 sensor")
    comp.process_mqtt_message("danfoss2mqtt/bridge/state", '{"state": "online"}')
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/devices",
        json.dumps(
            [
                _descriptor(grouped, home_id="home-1", room_sensor="s-8"),
                _descriptor(isolated, home_id="home-1", room_sensor="s-9"),
                _descriptor(sensor),  # no home of its own: it takes its head's
                _descriptor(stray, home_id="home-1"),
            ]
        ),
    )
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/rooms",
        json.dumps(
            [
                {
                    "group_id": "g-1",
                    "name": "X-0 Room 1",
                    "home_id": "home-1",
                    "members": ["h-1"],
                    "head_count": 1,
                    "online": True,
                    "sensor": None,
                }
            ]
        ),
    )

    store = build_companion_store(comp, CompanionRoomManager(comp))
    view = store["coordinator"]
    assert view.sensor_rooms() == {"s-9": "h-9"}

    overview = ops_views.overview_payload(store)
    (home,) = overview["homes"]
    assert home["gid"] == "home-1"
    single = next(r for r in home["rooms"] if r["id"] == "h-9")
    assert single["kind"] == "single_head"
    placed = {s["device_id"]: s["room_id"] for s in home["sensors"]}
    assert placed == {"s-9": "h-9", "s-8": None}


@pytest.mark.asyncio
async def test_isolated_head_room_sensor_dropped_when_the_bridge_stops_naming_it(
    hass: HomeAssistant,
) -> None:
    comp = MqttCompanionCoordinator(hass, ("danfoss2mqtt",))
    isolated = _head("h-9", "X-0 Office")
    sensor = _sensor("s-9", "X-0 Office sensor")
    comp.process_mqtt_message("danfoss2mqtt/bridge/state", '{"state": "online"}')
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/devices",
        json.dumps([_descriptor(isolated, room_sensor="s-9"), _descriptor(sensor)]),
    )
    view = build_companion_store(comp, CompanionRoomManager(comp))["coordinator"]
    assert view.sensor_rooms() == {"s-9": "h-9"}
    # Ambiguous now (the bridge names no sensor): the link goes, no name fallback.
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/devices",
        json.dumps([_descriptor(isolated), _descriptor(sensor)]),
    )
    assert view.sensor_rooms() == {}
    # A sensor id the fleet does not carry is never placed.
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/devices",
        json.dumps([_descriptor(isolated, room_sensor="s-404"), _descriptor(sensor)]),
    )
    assert view.sensor_rooms() == {}
    # The head gone from the bridge: its entry goes too.
    comp.process_mqtt_message("danfoss2mqtt/bridge/devices", json.dumps([_descriptor(sensor)]))
    assert comp.head_room_sensor == {}
