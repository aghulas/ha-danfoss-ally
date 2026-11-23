"""Regression for docs/bug-schedule-services-companion.md: the schedule & vacation service ops
dereferenced ``coordinator.client`` (the legacy cloud API client), which a Companion store's
``CompanionCoordinatorView`` does not have — so ``set_schedule`` / ``get_schedule`` /
``restore_schedule`` (and the vacation ops) raised ``AttributeError`` -> HTTP 500 and changed
nothing on a ponts+Companion entry. They must instead route through ``room_manager`` (as the
climate setpoint path already does) and, for vacation, refuse cleanly (no proven Companion route).
Synthetic data only."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.components import mqtt as mqtt_mod
from homeassistant.core import HomeAssistant

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud.companion_adapter import build_companion_store
from custom_components.danfoss_ally_cloud.companion_rooms import CompanionRoomManager
from custom_components.danfoss_ally_cloud.const import DATA_VACATION_WRITE
from custom_components.danfoss_ally_cloud.mqtt_companion import MqttCompanionCoordinator
from custom_components.danfoss_ally_cloud.ops_common import OperationError

PREFIX = "danfoss2mqtt"
GROUP_ID = "grp-profs"
HEADS = {"0x01": "Salle profs #1", "0x02": "Salle profs #2"}
Sent = list[tuple[str, dict[str, Any]]]


def _companion_store(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> tuple[dict, Sent]:
    """A Companion store backed by a native ``danfoss2mqtt`` room of two heads (the bug target)."""
    sent: Sent = []

    async def _publish(_hass: Any, topic: str, payload: str, **_kw: Any) -> None:
        sent.append((topic, json.loads(payload)))

    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    monkeypatch.setattr(mqtt_mod, "async_subscribe", AsyncMock(return_value=lambda: None))
    monkeypatch.setattr(mqtt_mod, "async_publish", _publish)
    # The deferred R7 verification schedules an async_call_later timer; not under test here.
    monkeypatch.setattr(ops, "_defer_verification", lambda *a, **k: None)

    comp = MqttCompanionCoordinator(hass, (PREFIX,))
    comp.process_mqtt_message(f"{PREFIX}/bridge/state", '{"state": "online"}')
    devices = [
        {
            "ieee_address": ieee,
            "friendly_name": name,
            "definition": {"vendor": "Danfoss", "model": "014G2461"},
        }
        for ieee, name in HEADS.items()
    ]
    comp.process_mqtt_message(f"{PREFIX}/bridge/devices", json.dumps(devices))
    comp.process_mqtt_message(
        f"{PREFIX}/bridge/rooms",
        json.dumps(
            [
                {
                    "group_id": GROUP_ID,
                    "name": "Salle des professeurs",
                    "home_id": "home-1",
                    "members": list(HEADS),
                }
            ]
        ),
    )
    room_mgr = CompanionRoomManager(comp)
    store = build_companion_store(comp, room_mgr)
    store[DATA_VACATION_WRITE] = True  # exercise the companion guard, not the disabled-gate
    return store, sent


async def test_set_get_restore_schedule_on_companion_store(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, sent = _companion_store(hass, monkeypatch)
    target = {"type": "room", "id": GROUP_ID}
    days = {"mon": [{"start": "08:30", "end": "22:30"}]}

    # set_schedule must not raise AttributeError/500; it fans a weekly_schedule out to both heads.
    job = await ops.set_schedule(hass, store, target, days)
    assert job["kind"] == "set_schedule"
    assert sorted(h.device_id for h in store["jobs"].get(job["job_id"]).heads) == ["0x01", "0x02"]
    fanned = [p for topic, p in sent if topic.endswith("/set") and "weekly_schedule" in p]
    assert len(fanned) == 2
    week = fanned[0]["weekly_schedule"]
    assert week["dayofweek"] == 0x02 and week["num_of_transitions"] == 3

    # get_schedule (SupportsResponse.ONLY) reads back what was fanned out, in the cloud shape.
    schedule = await ops.get_schedule(store, target)
    assert schedule["source"] == "companion"
    assert schedule["days"]["mon"] == days["mon"]

    # restore_schedule re-pushes the recorded schedule to the heads.
    sent.clear()
    restore = await ops.restore_schedule(hass, store, target)
    assert restore["kind"] == "restore"
    assert len([p for topic, p in sent if "weekly_schedule" in p]) == 2


async def test_restore_without_recorded_schedule_is_clean_error(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _companion_store(hass, monkeypatch)
    with pytest.raises(OperationError) as err:
        await ops.restore_schedule(hass, store, {"type": "room", "id": GROUP_ID})
    assert err.value.code == "no_schedule_recorded"


async def test_vacation_on_companion_refused_cleanly_not_500(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _companion_store(hass, monkeypatch)
    # Previously an AttributeError on ``coordinator.client`` -> 500; now a clean contract error.
    with pytest.raises(OperationError) as err:
        await ops.set_vacation(
            hass, store, "home-1", "20270101", "08:00", "20270105", "18:00", 17.0
        )
    assert err.value.code == "vacation_companion_unsupported"

    with pytest.raises(OperationError) as err:
        await ops.cancel_vacation(hass, store, "home-1")
    assert err.value.code == "vacation_companion_unsupported"
