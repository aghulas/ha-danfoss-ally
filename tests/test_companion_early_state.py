"""State and availability that arrive before ``bridge/devices`` are kept, then applied.

On (re)start the broker replays retained messages in no particular order across topics, so a
device's state can come before the ``bridge/devices`` that declares it. ``danfoss2mqtt`` republishes
a reading only when it changes: a dropped retained state left the entity unknown until then.
Synthetic data only.
"""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant

from custom_components.danfoss_ally_cloud.api import DanfossDevice, encode_z2m_descriptor
from custom_components.danfoss_ally_cloud.mqtt_companion import MqttCompanionCoordinator


def _sensor(dev_id: str, name: str) -> DanfossDevice:
    return DanfossDevice(
        id=dev_id,
        name=name,
        category="sensor",
        product_id="mxzo5rhf",
        online=True,
    )


def _devices(*devs: DanfossDevice) -> str:
    return json.dumps([encode_z2m_descriptor(d) for d in devs])


async def test_state_before_devices_is_applied_once_declared(hass: HomeAssistant) -> None:
    comp = MqttCompanionCoordinator(hass, ("danfoss2mqtt",))
    comp.process_mqtt_message(
        "danfoss2mqtt/X-0 Sensor", json.dumps({"temperature": 16.7, "humidity": 35.9})
    )
    comp.process_mqtt_message("danfoss2mqtt/X-0 Sensor/availability", "offline")
    assert "s-1" not in comp.data

    comp.process_mqtt_message("danfoss2mqtt/bridge/devices", _devices(_sensor("s-1", "X-0 Sensor")))

    dev = comp.data["s-1"]
    assert dev.temperature == 16.7
    assert dev.humidity == 35.9
    assert dev.online is False


async def test_latest_early_state_wins_and_is_applied_once(hass: HomeAssistant) -> None:
    comp = MqttCompanionCoordinator(hass, ("danfoss2mqtt",))
    comp.process_mqtt_message("danfoss2mqtt/X-0 Sensor", json.dumps({"temperature": 15.0}))
    comp.process_mqtt_message("danfoss2mqtt/X-0 Sensor", json.dumps({"temperature": 16.0}))
    comp.process_mqtt_message("danfoss2mqtt/bridge/devices", _devices(_sensor("s-1", "X-0 Sensor")))
    assert comp.data["s-1"].temperature == 16.0

    # A later live reading is applied as usual, and a re-published device list does not
    # replay the old early state over it.
    comp.process_mqtt_message("danfoss2mqtt/X-0 Sensor", json.dumps({"temperature": 17.5}))
    comp.process_mqtt_message("danfoss2mqtt/bridge/devices", _devices(_sensor("s-1", "X-0 Sensor")))
    assert comp.data["s-1"].temperature == 17.5


async def test_early_state_of_another_bridge_waits_for_its_own_devices(
    hass: HomeAssistant,
) -> None:
    comp = MqttCompanionCoordinator(hass, ("zigbee2mqtt", "danfoss2mqtt"))
    comp.process_mqtt_message("zigbee2mqtt/X-0 Sensor", json.dumps({"temperature": 18.0}))
    comp.process_mqtt_message("danfoss2mqtt/bridge/devices", _devices(_sensor("s-1", "X-0 Sensor")))
    # Same friendly name on another bridge: not this device's state.
    assert comp.data["s-1"].temperature is None


async def test_malformed_early_state_is_ignored(hass: HomeAssistant) -> None:
    comp = MqttCompanionCoordinator(hass, ("danfoss2mqtt",))
    comp.process_mqtt_message("danfoss2mqtt/X-0 Sensor", "not json")
    comp.process_mqtt_message("danfoss2mqtt/bridge/devices", _devices(_sensor("s-1", "X-0 Sensor")))
    assert comp.data["s-1"].temperature is None
