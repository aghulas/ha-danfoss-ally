"""Tests for Companion integration with standalone ``danfoss-room-coordinator`` bridges.

Covers:
- Two-segment ``bridge/response/#`` RPC routing (e.g. ``bridge/response/room/set-setpoint``)
- ``is_coordinator_room`` discrimination vs ``danfoss2mqtt`` and local virtual rooms
- Room setpoint routing through ``<prefix>/bridge/request/room/set-setpoint``
- Room schedule routing (``get_schedule`` / ``set_schedule`` / ``restore_schedule``) via RPC
- Single-owner-per-head telemetry skip when a bridge owns the head
- Room climate unavailability when its owning bridge is offline, and ``HomeAssistantError`` on
  refused/closed bridge requests
- Dynamic ``DanfossBridgeHeatDemandSensor`` creation and validity-window expiry.

Synthetic data only.
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.components import mqtt as mqtt_mod
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud.climate import DanfossRoomClimate
from custom_components.danfoss_ally_cloud.companion_adapter import build_companion_store
from custom_components.danfoss_ally_cloud.companion_rooms import (
    CompanionRoomConfig,
    CompanionRoomManager,
)
from custom_components.danfoss_ally_cloud.const import (
    CONF_CONNECTION_MODE,
    CONF_MQTT_PREFIXES,
    CONNECTION_MODE_MQTT_COMPANION,
    DOMAIN,
)
from custom_components.danfoss_ally_cloud.mqtt_companion import (
    CompanionBridgeError,
    MqttCompanionCoordinator,
)
from custom_components.danfoss_ally_cloud.ops_common import OperationError
from custom_components.danfoss_ally_cloud.sensor import DanfossBridgeHeatDemandSensor

Z2M = "zigbee2mqtt"
COORD = "danfoss_rooms"
ROOM_ID = "room-1"


def _setup_coord_companion(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict, MqttCompanionCoordinator, CompanionRoomManager, list[tuple[str, dict[str, Any]]]]:
    sent: list[tuple[str, dict[str, Any]]] = []

    async def _publish(_hass: Any, topic: str, payload: str, **_kw: Any) -> None:
        sent.append((topic, json.loads(payload)))

    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    monkeypatch.setattr(mqtt_mod, "async_subscribe", AsyncMock(return_value=lambda: None))
    monkeypatch.setattr(mqtt_mod, "async_publish", _publish)
    monkeypatch.setattr(ops, "_defer_verification", lambda *a, **k: None)

    comp = MqttCompanionCoordinator(hass, (Z2M, COORD))
    comp.process_mqtt_message(f"{Z2M}/bridge/state", "online")
    comp.process_mqtt_message(
        f"{Z2M}/bridge/devices",
        json.dumps(
            [
                {
                    "ieee_address": "0xA1",
                    "friendly_name": "Head A1",
                    "definition": {"vendor": "Danfoss", "model": "014G2461"},
                },
                {
                    "ieee_address": "0xS1",
                    "friendly_name": "Sensor S1",
                    "definition": {"vendor": "Danfoss", "model": "014G2480"},
                },
            ]
        ),
    )
    comp.process_mqtt_message(f"{Z2M}/Head A1", json.dumps({"occupied_heating_setpoint": 20.0}))
    comp.process_mqtt_message(f"{Z2M}/Sensor S1", json.dumps({"temperature": 19.3}))

    comp.process_mqtt_message(f"{COORD}/bridge/state", "online")
    comp.process_mqtt_message(
        f"{COORD}/bridge/rooms",
        json.dumps(
            [
                {
                    "group_id": ROOM_ID,
                    "name": "Living",
                    "prefix": Z2M,
                    "members": ["0xA1"],
                    "sensor": "0xS1",
                    "temperature": 19.3,
                }
            ]
        ),
    )

    mgr = CompanionRoomManager(comp)
    store = build_companion_store(comp, mgr)
    return store, comp, mgr, sent


async def test_coordinator_room_setpoint_routes_via_bridge_rpc(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, comp, mgr, sent = _setup_coord_companion(hass, monkeypatch)
    assert comp.is_coordinator_room(ROOM_ID) is True
    assert mgr.build_rooms()[ROOM_ID].temperature == 19.3

    # Intercept bridge/request/room/set-setpoint and answer on two-segment response topic.
    orig_pub = mqtt_mod.async_publish

    async def _reply_on_setpoint(_hass: Any, topic: str, payload: str, **kw: Any) -> None:
        await orig_pub(_hass, topic, payload, **kw)
        body = json.loads(payload)
        if topic == f"{COORD}/bridge/request/room/set-setpoint":
            comp.process_mqtt_message(
                f"{COORD}/bridge/response/room/set-setpoint",
                json.dumps(
                    {
                        "status": "ok",
                        "job_status": "applied",
                        "transaction": body["transaction"],
                    }
                ),
            )

    monkeypatch.setattr(mqtt_mod, "async_publish", _reply_on_setpoint)

    climate = DanfossRoomClimate(store["coordinator"], ROOM_ID)
    assert climate.available is True
    await climate.async_set_temperature(temperature=21.5)
    assert any(t == f"{COORD}/bridge/request/room/set-setpoint" for t, _ in sent)
    assert not any(t.endswith("/set") for t, _ in sent)

    # Closed room response -> CompanionBridgeError("closed") -> HomeAssistantError.
    async def _reply_closed(_hass: Any, topic: str, payload: str, **kw: Any) -> None:
        body = json.loads(payload)
        comp.process_mqtt_message(
            f"{COORD}/bridge/response/room/set-setpoint",
            json.dumps(
                {
                    "status": "closed",
                    "error": "room is not armed",
                    "transaction": body["transaction"],
                }
            ),
        )

    monkeypatch.setattr(mqtt_mod, "async_publish", _reply_closed)
    with pytest.raises(HomeAssistantError, match="not armed"):
        await climate.async_set_temperature(temperature=21.5)

    # Bridge offline -> climate becomes unavailable.
    comp.process_mqtt_message(f"{COORD}/bridge/state", "offline")
    assert climate.available is False


async def test_coordinator_room_schedules_route_via_bridge_rpc(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, comp, _mgr, sent = _setup_coord_companion(hass, monkeypatch)
    orig_pub = mqtt_mod.async_publish

    async def _reply_sched(_hass: Any, topic: str, payload: str, **kw: Any) -> None:
        await orig_pub(_hass, topic, payload, **kw)
        body = json.loads(payload)
        action = topic.rsplit("/", 1)[-1]
        if action == "get_schedule":
            reply = {
                "status": "ok",
                "transaction": body["transaction"],
                "data": {
                    "target": {"type": "room", "id": ROOM_ID},
                    "days": {"mon": [{"start": "07:00", "end": "22:00"}]},
                    "source": "coordinator",
                },
            }
        else:
            reply = {
                "status": "ok",
                "transaction": body["transaction"],
                "data": {"target": {"type": "room", "id": ROOM_ID}, "written": True},
            }
        comp.process_mqtt_message(f"{COORD}/bridge/response/{action}", json.dumps(reply))

    monkeypatch.setattr(mqtt_mod, "async_publish", _reply_sched)

    target = {"type": "room", "id": ROOM_ID}
    got = await ops.get_schedule(store, target)
    assert got["source"] == "coordinator"

    await ops.set_schedule(hass, store, target, {"mon": [{"start": "08:00", "end": "20:00"}]})
    await ops.restore_schedule(hass, store, target)
    assert [t for t, _ in sent] == [
        f"{COORD}/bridge/request/get_schedule",
        f"{COORD}/bridge/request/set_schedule",
        f"{COORD}/bridge/request/restore_schedule",
    ]

    # Bridge offline refuses cleanly.
    comp.process_mqtt_message(f"{COORD}/bridge/state", "offline")
    with pytest.raises(OperationError) as exc:
        await ops.set_schedule(hass, store, target, {"mon": []})
    assert exc.value.code == "bridge_offline"


async def test_telemetry_skips_heads_owned_by_bridge_room(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store, _comp, mgr, sent = _setup_coord_companion(hass, monkeypatch)
    mgr.feed_external_sensor = True
    mgr.add_virtual_room(
        CompanionRoomConfig(
            room_id="virt-dup",
            name="Dup",
            head_ids=["0xA1"],
            sensor_id="0xS1",
        )
    )
    res = await mgr.async_sync_telemetry(now=100.0)
    assert res == {"external_sensor_writes": 0, "load_mean_writes": 0}
    assert sent == []


async def test_heat_demand_sensor_and_expiry(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONNECTION_MODE: CONNECTION_MODE_MQTT_COMPANION,
            CONF_MQTT_PREFIXES: [Z2M, COORD],
        },
        options={CONF_MQTT_PREFIXES: [Z2M, COORD]},
    )
    entry.add_to_hass(hass)

    store, comp, _mgr, _sent = _setup_coord_companion(hass, monkeypatch)
    now = int(time.time())
    comp.process_mqtt_message(
        f"{COORD}/bridge/heat_demand",
        json.dumps(
            {
                "calling": True,
                "rooms_calling": [{"group_id": ROOM_ID, "name": "Living", "valve": 65.0}],
                "max_valve": 65.0,
                "ts": now,
                "valid_for_s": 900,
            }
        ),
    )

    sensor = DanfossBridgeHeatDemandSensor(entry.entry_id, comp, COORD)
    assert sensor.available is True
    assert sensor.native_value == 65.0
    assert sensor.extra_state_attributes["calling"] is True

    # Stale timestamp -> sensor marks itself unavailable (§5.7).
    comp.process_mqtt_message(
        f"{COORD}/bridge/heat_demand",
        json.dumps(
            {
                "calling": True,
                "rooms_calling": [],
                "max_valve": 65.0,
                "ts": now - 1000,
                "valid_for_s": 900,
            }
        ),
    )
    assert sensor.available is False

    # Bad JSON ignored; offline bridge marks unavailable.
    comp.process_mqtt_message(f"{COORD}/bridge/heat_demand", "{bad")
    comp.process_mqtt_message(f"{COORD}/bridge/state", "offline")
    assert sensor.available is False

    # Dynamic registration via sensor.async_setup_entry when bridge/heat_demand arrives later.
    from custom_components.danfoss_ally_cloud import sensor as sensor_mod

    comp2 = MqttCompanionCoordinator(hass, (Z2M, COORD))
    comp2.process_mqtt_message(f"{COORD}/bridge/state", "online")
    mgr2 = CompanionRoomManager(comp2)
    store2 = build_companion_store(comp2, mgr2)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = store2
    added: list[Any] = []
    await sensor_mod.async_setup_entry(hass, entry, added.extend)
    assert added == []
    comp2.process_mqtt_message(
        f"{COORD}/bridge/heat_demand",
        json.dumps({"calling": False, "rooms_calling": [], "max_valve": 0.0}),
    )
    assert len(added) == 1
    assert isinstance(added[0], DanfossBridgeHeatDemandSensor)
    assert added[0].native_value == 0.0
    assert added[0].available is True


async def test_companion_subscriptions_include_heat_demand_and_wildcard_response(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    subs: list[str] = []

    async def _sub(_hass: Any, topic: str, _cb: Any) -> Any:
        subs.append(topic)
        return lambda: None

    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    monkeypatch.setattr(mqtt_mod, "async_subscribe", _sub)

    comp = MqttCompanionCoordinator(hass, (COORD,))
    await comp.async_start()
    assert f"{COORD}/bridge/heat_demand" in subs
    assert f"{COORD}/bridge/response/#" in subs
    assert CompanionBridgeError("closed", "closed").code == "closed"
