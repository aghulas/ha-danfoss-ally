"""Regression for ``docs/z2m-cloud-parity.md`` §4: the Companion indexes rooms/holidays BY PREFIX.

Before this, ``native_rooms`` and ``holidays`` were single dictionaries replaced wholesale on every
``bridge/rooms`` / ``bridge/holidays`` message, so a second bridge (e.g. the standalone room
coordinator on ``danfoss-rooms``) overwrote the first (``danfoss2mqtt``). Synthetic data only.
"""

from __future__ import annotations

import json

import pytest
from homeassistant.core import HomeAssistant

from custom_components.danfoss_ally_cloud.mqtt_companion import MqttCompanionCoordinator


def _rooms(*group_ids: str) -> str:
    return json.dumps([{"group_id": g, "name": g.upper(), "members": []} for g in group_ids])


@pytest.mark.asyncio
async def test_two_bridges_rooms_do_not_overwrite(hass: HomeAssistant) -> None:
    comp = MqttCompanionCoordinator(hass, ("danfoss2mqtt", "danfoss-rooms"))

    comp.process_mqtt_message("danfoss2mqtt/bridge/rooms", _rooms("g1", "g2"))
    comp.process_mqtt_message("danfoss-rooms/bridge/rooms", _rooms("room-aa", "room-bb"))

    # Both bridges' rooms survive in the merged view.
    assert set(comp.native_rooms) == {"g1", "g2", "room-aa", "room-bb"}
    # And they are kept separate per source prefix (for write routing later).
    by_prefix = comp.native_rooms_by_prefix
    assert set(by_prefix["danfoss2mqtt"]) == {"g1", "g2"}
    assert set(by_prefix["danfoss-rooms"]) == {"room-aa", "room-bb"}
    assert comp.prefix_of_room("room-aa") == "danfoss-rooms"
    assert comp.prefix_of_room("g1") == "danfoss2mqtt"
    assert comp.prefix_of_room("nope") is None


@pytest.mark.asyncio
async def test_rooms_update_replaces_only_that_prefix(hass: HomeAssistant) -> None:
    comp = MqttCompanionCoordinator(hass, ("danfoss2mqtt", "danfoss-rooms"))
    comp.process_mqtt_message("danfoss2mqtt/bridge/rooms", _rooms("g1"))
    comp.process_mqtt_message("danfoss-rooms/bridge/rooms", _rooms("room-aa"))

    # A fresh publish on one prefix must not drop the other prefix's rooms.
    comp.process_mqtt_message("danfoss-rooms/bridge/rooms", _rooms("room-cc"))
    assert set(comp.native_rooms) == {"g1", "room-cc"}

    # An empty list on a prefix clears only that prefix.
    comp.process_mqtt_message("danfoss-rooms/bridge/rooms", "[]")
    assert set(comp.native_rooms) == {"g1"}


@pytest.mark.asyncio
async def test_two_bridges_holidays_do_not_overwrite(hass: HomeAssistant) -> None:
    comp = MqttCompanionCoordinator(hass, ("danfoss2mqtt", "danfoss-rooms"))
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/holidays", json.dumps({"home-1": {"active": True}})
    )
    comp.process_mqtt_message(
        "danfoss-rooms/bridge/holidays", json.dumps({"home-9": {"active": False}})
    )
    assert set(comp.holidays) == {"home-1", "home-9"}
    assert comp.holidays["home-1"]["active"] is True


@pytest.mark.asyncio
async def test_bad_payloads_leave_store_untouched(hass: HomeAssistant) -> None:
    comp = MqttCompanionCoordinator(hass, ("danfoss-rooms",))
    comp.process_mqtt_message("danfoss-rooms/bridge/rooms", _rooms("room-aa"))
    comp.process_mqtt_message("danfoss-rooms/bridge/rooms", "{not json")
    comp.process_mqtt_message("danfoss-rooms/bridge/rooms", json.dumps({"not": "a list"}))
    comp.process_mqtt_message("danfoss-rooms/bridge/holidays", "not json either")
    assert set(comp.native_rooms) == {"room-aa"}
