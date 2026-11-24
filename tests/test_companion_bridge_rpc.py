"""End-to-end tests for Companion <-> danfoss2mqtt schedule RPC (bridge/request/+).

Verifies the full round-trip between ``operations.{get,set,restore}_schedule`` on a Companion
entry and ``api.bridge_daemon.async_run_bridge`` over an in-memory MQTT broker:
- ``get_schedule`` reads the real cloud schedule via ``bridge/request/get_schedule`` (with cache)
- ``set_schedule`` executes ``client.async_set_schedule_days`` and awaits confirmation
- ``restore_schedule`` executes ``client.async_restore_schedule`` and awaits confirmation
- Errors (``bridge_offline``, ``bridge_timeout``, ``cloud_refused``, ``unknown_target``,
  ``ScheduleValidationError``, ``bridge_stopped``) propagate as clean contract ``OperationError``s.
Synthetic data only.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.components import mqtt as mqtt_mod
from homeassistant.core import HomeAssistant

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud.api.bridge_daemon import (
    BridgeConfig,
    _topic_matches,
    async_run_bridge,
)
from custom_components.danfoss_ally_cloud.api.client import (
    CloudError,
    ScheduleValidationError,
    UnknownTargetError,
)
from custom_components.danfoss_ally_cloud.companion_adapter import build_companion_store
from custom_components.danfoss_ally_cloud.companion_rooms import CompanionRoomManager
from custom_components.danfoss_ally_cloud.mqtt_companion import (
    CompanionBridgeError,
    MqttCompanionCoordinator,
)
from custom_components.danfoss_ally_cloud.ops_common import OperationError

PREFIX = "danfoss2mqtt"
GROUP_ID = "grp-profs"


class _InMemoryBroker:
    """Minimal in-memory MQTT broker bridging ``MqttCompanionCoordinator`` and ``bridge_daemon``."""

    def __init__(self, companion: MqttCompanionCoordinator) -> None:
        self._companion = companion
        self._subs: list[tuple[str, Any]] = []

    def publish(self, topic: str, payload: str, *, retain: bool = False) -> None:
        self._companion.process_mqtt_message(topic, payload)
        for pattern, cb in list(self._subs):
            if _topic_matches(pattern, topic):
                cb(topic, payload)

    def subscribe(self, topic: str, callback: Any) -> None:
        self._subs.append((topic, callback))

    async def ha_publish(self, _hass: Any, topic: str, payload: str, **_kw: Any) -> None:
        self.publish(topic, payload)


def _setup_companion_with_room(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict, MqttCompanionCoordinator, _InMemoryBroker]:
    comp = MqttCompanionCoordinator(hass, (PREFIX,))
    broker = _InMemoryBroker(comp)
    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    monkeypatch.setattr(mqtt_mod, "async_subscribe", AsyncMock(return_value=lambda: None))
    monkeypatch.setattr(mqtt_mod, "async_publish", broker.ha_publish)
    monkeypatch.setattr(ops, "_defer_verification", lambda *a, **k: None)

    comp.process_mqtt_message(f"{PREFIX}/bridge/state", "online")
    comp.process_mqtt_message(
        f"{PREFIX}/bridge/devices",
        json.dumps(
            [
                {
                    "ieee_address": "bf_h1",
                    "friendly_name": "Salle profs #1",
                    "definition": {"vendor": "Danfoss", "model": "014G2461"},
                    "danfoss": {"dev_id": "bf_h1", "product_id": "03wvrwpv", "category": "head"},
                }
            ]
        ),
    )
    comp.process_mqtt_message(
        f"{PREFIX}/bridge/rooms",
        json.dumps(
            [
                {
                    "group_id": GROUP_ID,
                    "name": "Salle des professeurs",
                    "home_id": "home-1",
                    "members": ["bf_h1"],
                }
            ]
        ),
    )
    store = build_companion_store(comp, CompanionRoomManager(comp))
    return store, comp, broker


async def test_companion_to_danfoss2mqtt_schedule_rpc_roundtrip(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full end-to-end get_schedule / set_schedule / restore_schedule over MQTT RPC."""
    store, _comp, broker = _setup_companion_with_room(hass, monkeypatch)

    cloud_schedule = {
        "target": {"type": "room", "id": GROUP_ID},
        "name": "Salle des professeurs",
        "days": {"mon": [{"start": "08:00", "end": "18:00"}]},
        "source": "cloud",
        "read_at": "2026-11-24T12:00:00+01:00",
    }
    fake_client = AsyncMock()
    fake_client.async_list_devices = AsyncMock(return_value=[])
    fake_client.async_get_schedule = AsyncMock(return_value=cloud_schedule)
    fake_client.async_set_schedule_days = AsyncMock(return_value=None)
    fake_client.async_restore_schedule = AsyncMock(return_value=None)

    stop_event = asyncio.Event()
    bridge_task = asyncio.create_task(
        async_run_bridge(
            BridgeConfig(base_topic=PREFIX, poll_interval=60),
            transport=broker,
            client=fake_client,
            stop_event=stop_event,
        )
    )
    await asyncio.sleep(0.05)

    try:
        target = {"type": "room", "id": GROUP_ID}
        # 1) get_schedule -> real cloud read via RPC + cached on second call
        sched = await ops.get_schedule(store, target)
        assert sched == cloud_schedule
        assert fake_client.async_get_schedule.await_count == 1
        sched_cached = await ops.get_schedule(store, target)
        assert sched_cached == cloud_schedule
        assert fake_client.async_get_schedule.await_count == 1

        # 2) set_schedule -> real cloud HTTP write via RPC + cache invalidated
        new_days = {"mon": [{"start": "08:30", "end": "22:30"}]}
        job = await ops.set_schedule(hass, store, target, new_days)
        assert job["kind"] == "set_schedule"
        fake_client.async_set_schedule_days.assert_awaited_once_with(target, new_days)

        # 3) restore_schedule -> real cloud HTTP restore via RPC
        restore = await ops.restore_schedule(hass, store, target)
        assert restore["kind"] == "restore"
        fake_client.async_restore_schedule.assert_awaited_once_with(target)

        # 4) Cloud / validation / unknown-target errors propagate cleanly
        fake_client.async_get_schedule.side_effect = UnknownTargetError("missing")
        with pytest.raises(OperationError) as err:
            await ops.get_schedule(store, target, refresh=True)
        assert err.value.code == "unknown_target"

        fake_client.async_restore_schedule.side_effect = CloudError("rate limited")
        with pytest.raises(OperationError) as err:
            await ops.restore_schedule(hass, store, target)
        assert err.value.code == "cloud_refused"

        fake_client.async_set_schedule_days.side_effect = ScheduleValidationError(
            [{"code": "too_many_transitions", "message": "too many", "day": "mon"}]
        )
        with pytest.raises(OperationError) as err:
            await ops.set_schedule(hass, store, target, new_days)
        assert err.value.code == "too_many_transitions"
        assert err.value.day == "mon"
    finally:
        stop_event.set()
        await bridge_task


async def test_bridge_rpc_offline_timeout_and_stop(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline bridge, timeout, unknown prefix, invalid payload, and stop cancellation."""
    store, comp, _broker = _setup_companion_with_room(hass, monkeypatch)
    target = {"type": "room", "id": GROUP_ID}

    # Unknown prefix
    with pytest.raises(CompanionBridgeError) as err:
        await comp.async_bridge_request("other", "get_schedule", {})
    assert err.value.code == "bridge_unknown"

    # Offline bridge -> refused immediately without publishing
    comp.process_mqtt_message(f"{PREFIX}/bridge/state", "offline")
    with pytest.raises(OperationError) as op_err:
        await ops.set_schedule(hass, store, target, {"mon": [{"start": "08:00", "end": "12:00"}]})
    assert op_err.value.code == "bridge_offline"

    # Online bridge with no listener -> timeout
    comp.process_mqtt_message(f"{PREFIX}/bridge/state", "online")
    with pytest.raises(CompanionBridgeError) as err:
        await comp.async_bridge_request(PREFIX, "get_schedule", {"target": target}, timeout_s=0.02)
    assert err.value.code == "bridge_timeout"

    # In-flight RPC cancelled cleanly on async_stop()
    rpc_task = asyncio.create_task(
        comp.async_bridge_request(PREFIX, "get_schedule", {"target": target}, timeout_s=5.0)
    )
    await asyncio.sleep(0.01)
    await comp.async_stop()
    with pytest.raises(CompanionBridgeError) as err:
        await rpc_task
    assert err.value.code == "bridge_stopped"

    # Malformed bridge/response payloads are ignored safely
    comp.process_mqtt_message(f"{PREFIX}/bridge/response/get_schedule", "not-json")
    comp.process_mqtt_message(f"{PREFIX}/bridge/response/get_schedule", "[]")
    comp.process_mqtt_message(
        f"{PREFIX}/bridge/response/get_schedule", json.dumps({"status": "ok"})
    )
