"""A cloud room sensor named on ``danfoss2mqtt/bridge/rooms`` (``sensor``) lands in its room.

End to end through the Companion: ``bridge/devices`` + ``bridge/rooms`` -> the adapter's
``sensor_rooms`` -> the side panel's overview payload. ``danfoss2mqtt`` publishes ``sensor`` only
from a proven link (the account's device -> Tuya room map, ``docs/companion-contract.md``); a
sensor it does not name stays without a room, whatever its name. Synthetic data only.
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
