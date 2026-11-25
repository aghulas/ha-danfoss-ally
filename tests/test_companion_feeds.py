"""Stage 0 of ``docs/z2m-cloud-parity.md``: the Companion's two virtual-room feeds are closed
unless opened, the room-sensor keep-alive stays under the head's 30-min deadline, the load mean is
only written to rooms whose heads all have load balancing on, and a weekly schedule over six
transitions is refused instead of truncated. Synthetic data only."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.components import mqtt as mqtt_mod
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud.api import DanfossDevice
from custom_components.danfoss_ally_cloud.api.z2m_contract import decode_z2m_state
from custom_components.danfoss_ally_cloud.companion_rooms import (
    EXTERNAL_SENSOR_DEADLINE_SECONDS,
    EXTERNAL_SENSOR_MIN_INTERVAL_SECONDS,
    EXTERNAL_SENSOR_REFRESH_SECONDS,
    CompanionRoomConfig,
    CompanionRoomManager,
)
from custom_components.danfoss_ally_cloud.const import (
    COMPANION_TELEMETRY_INTERVAL,
    CONF_COMPANION_FEED_EXTERNAL_SENSOR,
    CONF_COMPANION_FEED_LOAD_MEAN,
    CONF_CONNECTION_MODE,
    CONF_MQTT_PREFIXES,
    CONNECTION_MODE_MQTT_COMPANION,
    DOMAIN,
)
from custom_components.danfoss_ally_cloud.mqtt_companion import MqttCompanionCoordinator

HEADS = {"0x01": "Head-1", "0x02": "Head-2"}
SENSOR_ID, SENSOR_NAME = "0x0a", "Sensor-1"
SENSOR_KEY = "external_measured_room_sensor"
Sent = list[tuple[str, dict[str, Any]]]


def _companion(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Sent]:
    """A Companion with two heads and one room sensor on ``zigbee2mqtt``, publishes captured."""
    sent: Sent = []

    async def _publish(_hass: Any, topic: str, payload: str, **_kw: Any) -> None:
        sent.append((topic, json.loads(payload)))

    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    monkeypatch.setattr(mqtt_mod, "async_subscribe", AsyncMock(return_value=lambda: None))
    monkeypatch.setattr(mqtt_mod, "async_publish", _publish)

    comp = MqttCompanionCoordinator(hass, ("zigbee2mqtt",))
    comp.process_mqtt_message("zigbee2mqtt/bridge/state", '{"state": "online"}')
    devices = [
        {
            "ieee_address": ieee,
            "friendly_name": name,
            "definition": {"vendor": "Danfoss", "model": "014G2461"},
        }
        for ieee, name in HEADS.items()
    ]
    devices.append(
        {
            "ieee_address": SENSOR_ID,
            "friendly_name": SENSOR_NAME,
            "definition": {"vendor": "Danfoss", "model": "014G2480"},
        }
    )
    comp.process_mqtt_message("zigbee2mqtt/bridge/devices", json.dumps(devices))
    for name in HEADS.values():
        comp.process_mqtt_message(f"zigbee2mqtt/{name}", json.dumps({"load_estimate": 500}))
    comp.process_mqtt_message(f"zigbee2mqtt/{SENSOR_NAME}", json.dumps({"temperature": 20.0}))
    return comp, sent


def _room(sensor: bool = True) -> CompanionRoomConfig:
    return CompanionRoomConfig(
        room_id="room-1",
        name="Room 1",
        head_ids=list(HEADS),
        sensor_id=SENSOR_ID if sensor else None,
    )


def _sensor_writes(sent: Sent, head: str) -> list[int]:
    return [p[SENSOR_KEY] for t, p in sent if t == f"zigbee2mqtt/{head}/set" and SENSOR_KEY in p]


# --- options: both feeds closed by default ---------------------------------------------------


async def test_feeds_closed_by_default(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch):
    comp, sent = _companion(hass, monkeypatch)
    for name in HEADS.values():
        comp.process_mqtt_message(f"zigbee2mqtt/{name}", '{"load_balancing_enable": true}')
    mgr = CompanionRoomManager(comp)
    mgr.add_virtual_room(_room())
    assert await mgr.async_sync_telemetry(now=0.0) == {
        "external_sensor_writes": 0,
        "load_mean_writes": 0,
    }
    assert sent == []

    # Each feed opens alone
    mgr.feed_external_sensor = True
    assert await mgr.async_sync_telemetry(now=10.0) == {
        "external_sensor_writes": 2,
        "load_mean_writes": 0,
    }
    mgr.feed_external_sensor, mgr.feed_load_mean = False, True
    assert await mgr.async_sync_telemetry(now=5000.0) == {
        "external_sensor_writes": 0,
        "load_mean_writes": 2,
    }


# --- room-sensor feed timing -----------------------------------------------------------------


def test_keep_alive_constants_stay_under_the_head_deadline():
    """A keep-alive lands at most one tick after its threshold; that worst case must stay under
    the 30 min the head asks for (and well under its 35-min reset), and two consecutive ticks must
    clear the per-head floor."""
    assert EXTERNAL_SENSOR_REFRESH_SECONDS + COMPANION_TELEMETRY_INTERVAL < (
        EXTERNAL_SENSOR_DEADLINE_SECONDS - 120
    )
    assert COMPANION_TELEMETRY_INTERVAL >= EXTERNAL_SENSOR_MIN_INTERVAL_SECONDS


@pytest.mark.parametrize("jitter", [0.0, -0.5, 0.5])
async def test_keep_alive_on_the_timer_never_reaches_30_min(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, jitter: float
):
    """Steady sensor, the real tick, four hours: every head is rewritten before 30 min, never
    sooner than 5 min. (Before: 1800 s threshold on a 900 s tick, so 30 or 45 min.)"""
    comp, sent = _companion(hass, monkeypatch)
    mgr = CompanionRoomManager(comp, feed_external_sensor=True)
    mgr.add_virtual_room(_room())

    times: dict[str, list[float]] = {name: [] for name in HEADS.values()}
    ts, tick = 0.0, 0
    while ts < 4 * 3600:
        before = len(sent)
        await mgr.async_sync_telemetry(now=ts)
        for topic, _payload in sent[before:]:
            times[topic.split("/")[1]].append(ts)
        tick += 1
        ts = tick * COMPANION_TELEMETRY_INTERVAL + (jitter if tick % 2 else 0.0)

    for name in HEADS.values():
        gaps = [b - a for a, b in zip(times[name], times[name][1:], strict=False)]
        assert len(gaps) >= 8
        assert max(gaps) < EXTERNAL_SENSOR_DEADLINE_SECONDS - 120
        assert min(gaps) >= EXTERNAL_SENSOR_MIN_INTERVAL_SECONDS
        assert set(_sensor_writes(sent, name)) == {2000}


async def test_sensor_feed_per_head_floor_of_5_min(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
):
    """A change, or a service-triggered sync, never writes a head twice within 5 min."""
    comp, sent = _companion(hass, monkeypatch)
    mgr = CompanionRoomManager(comp, feed_external_sensor=True)
    mgr.add_virtual_room(_room())
    assert (await mgr.async_sync_telemetry(now=0.0))["external_sensor_writes"] == 2

    # Below the 0.2 °C delta: nothing, however long (short of the keep-alive)
    comp.process_mqtt_message(f"zigbee2mqtt/{SENSOR_NAME}", '{"temperature": 20.1}')
    assert (await mgr.async_sync_telemetry(now=600.0))["external_sensor_writes"] == 0

    # A real change inside the floor waits for it
    comp.process_mqtt_message(f"zigbee2mqtt/{SENSOR_NAME}", '{"temperature": 20.2}')
    sent.clear()
    assert (await mgr.async_sync_telemetry(now=60.0))["external_sensor_writes"] == 0
    assert (await mgr.async_sync_telemetry(now=299.0))["external_sensor_writes"] == 0
    assert (await mgr.async_sync_telemetry(now=300.0))["external_sensor_writes"] == 2
    assert _sensor_writes(sent, "Head-1") == [2020]
    # ... and the same value is not written again right after
    assert (await mgr.async_sync_telemetry(now=700.0))["external_sensor_writes"] == 0


async def test_sensor_feed_is_tracked_per_head(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
):
    """A head offline during a round is fed when it comes back, without rewriting the other."""
    comp, sent = _companion(hass, monkeypatch)
    mgr = CompanionRoomManager(comp, feed_external_sensor=True)
    mgr.add_virtual_room(_room())
    comp.process_mqtt_message("zigbee2mqtt/Head-2/availability", "offline")
    assert (await mgr.async_sync_telemetry(now=0.0))["external_sensor_writes"] == 1
    assert _sensor_writes(sent, "Head-2") == []

    comp.process_mqtt_message("zigbee2mqtt/Head-2/availability", "online")
    sent.clear()
    assert (await mgr.async_sync_telemetry(now=360.0))["external_sensor_writes"] == 1
    assert _sensor_writes(sent, "Head-2") == [2000]
    assert _sensor_writes(sent, "Head-1") == []


async def test_sensor_offline_disables_once_then_resumes(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
):
    comp, sent = _companion(hass, monkeypatch)
    mgr = CompanionRoomManager(comp, feed_external_sensor=True)
    mgr.add_virtual_room(_room())
    await mgr.async_sync_telemetry(now=0.0)

    comp.process_mqtt_message(f"zigbee2mqtt/{SENSOR_NAME}/availability", "offline")
    sent.clear()
    assert (await mgr.async_sync_telemetry(now=360.0))["external_sensor_writes"] == 2
    assert _sensor_writes(sent, "Head-1") == [-8000]
    # Not repeated while the sensor stays away, keep-alive included
    assert (await mgr.async_sync_telemetry(now=720.0))["external_sensor_writes"] == 0
    assert (await mgr.async_sync_telemetry(now=4000.0))["external_sensor_writes"] == 0

    comp.process_mqtt_message(f"zigbee2mqtt/{SENSOR_NAME}/availability", "online")
    sent.clear()
    assert (await mgr.async_sync_telemetry(now=4360.0))["external_sensor_writes"] == 2
    assert _sensor_writes(sent, "Head-2") == [2000]


async def test_never_fed_head_gets_no_disable_write_and_delete_forgets(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
):
    comp, sent = _companion(hass, monkeypatch)
    comp.process_mqtt_message(f"zigbee2mqtt/{SENSOR_NAME}/availability", "offline")
    mgr = CompanionRoomManager(comp, feed_external_sensor=True)
    mgr.add_virtual_room(_room())
    assert (await mgr.async_sync_telemetry(now=0.0))["external_sensor_writes"] == 0
    assert sent == []

    comp.process_mqtt_message(f"zigbee2mqtt/{SENSOR_NAME}/availability", "online")
    await mgr.async_sync_telemetry(now=10.0)
    mgr.remove_virtual_room("room-1")
    mgr.remove_virtual_room("room-1")  # unknown room: no error
    mgr.add_virtual_room(_room())
    # A re-created room starts from scratch: first write is immediate
    assert (await mgr.async_sync_telemetry(now=20.0))["external_sensor_writes"] == 2


# --- load mean: only when every member has load balancing on -----------------------------------


def test_decode_load_balancing_enable_is_strict():
    dev = DanfossDevice(id="0x01", name="Head-1", category="head")
    assert dev.load_balancing_enable is None
    assert decode_z2m_state(dev, {"load_balancing_enable": True}).load_balancing_enable is True
    assert decode_z2m_state(dev, {"load_estimate": 1}).load_balancing_enable is True  # kept
    assert decode_z2m_state(dev, {"load_balancing_enable": False}).load_balancing_enable is False
    for odd in ("true", 1, None):
        dev.load_balancing_enable = True
        assert decode_z2m_state(dev, {"load_balancing_enable": odd}).load_balancing_enable is None


async def test_load_mean_requires_load_balancing_on_every_member(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
):
    comp, sent = _companion(hass, monkeypatch)
    mgr = CompanionRoomManager(comp, feed_load_mean=True)
    mgr.add_virtual_room(_room(sensor=False))

    # Nobody reported the attribute: unknown counts as off
    assert (await mgr.async_sync_telemetry(now=0.0))["load_mean_writes"] == 0
    # One of two on
    comp.process_mqtt_message("zigbee2mqtt/Head-1", '{"load_balancing_enable": true}')
    assert (await mgr.async_sync_telemetry(now=10.0))["load_mean_writes"] == 0
    # The other explicitly off
    comp.process_mqtt_message("zigbee2mqtt/Head-2", '{"load_balancing_enable": false}')
    assert (await mgr.async_sync_telemetry(now=20.0))["load_mean_writes"] == 0
    assert sent == []

    comp.process_mqtt_message("zigbee2mqtt/Head-2", '{"load_balancing_enable": true}')
    assert (await mgr.async_sync_telemetry(now=30.0))["load_mean_writes"] == 2
    assert ("zigbee2mqtt/Head-2/set", {"load_room_mean": 500}) in sent

    # A head turned off later closes the feed again, keep-alive included
    comp.process_mqtt_message("zigbee2mqtt/Head-1", '{"load_balancing_enable": false}')
    assert (await mgr.async_sync_telemetry(now=5000.0))["load_mean_writes"] == 0


async def test_load_mean_not_written_when_a_configured_member_is_unknown(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
):
    comp, sent = _companion(hass, monkeypatch)
    for name in HEADS.values():
        comp.process_mqtt_message(f"zigbee2mqtt/{name}", '{"load_balancing_enable": true}')
    mgr = CompanionRoomManager(comp, feed_load_mean=True)
    mgr.add_virtual_room(
        CompanionRoomConfig(room_id="room-1", name="Room 1", head_ids=[*HEADS, "0xff"])
    )
    assert (await mgr.async_sync_telemetry(now=0.0))["load_mean_writes"] == 0
    assert sent == []


# --- weekly schedule: refuse past six transitions (R1), never truncate -------------------------


async def test_room_schedule_refuses_more_than_six_transitions(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
):
    comp, sent = _companion(hass, monkeypatch)
    mgr = CompanionRoomManager(comp)
    cfg = _room()
    mgr.add_virtual_room(cfg)

    # Three windows away from midnight = 00:00 + 6 transitions = 7 entries
    too_many = [
        {"start": "06:00", "end": "08:00"},
        {"start": "10:00", "end": "12:00"},
        {"start": "14:00", "end": "16:00"},
    ]
    fine = [{"start": "07:00", "end": "17:00"}]
    with pytest.raises(ValueError, match=r"Too many transitions on tuesday: 7 > 6 \(R1\)"):
        # The valid day comes first: it must not be sent, nor stored
        await mgr.async_set_room_schedule(
            "room-1", {"monday": fine, "tuesday": too_many}, comfort_c=22.0
        )
    assert sent == []
    assert cfg.schedule == {} and cfg.comfort_setpoint == 21.0

    # An invalid day name after a valid day sends nothing either
    with pytest.raises(ValueError, match="Invalid day"):
        await mgr.async_set_room_schedule("room-1", {"monday": fine, "funday": fine})
    assert sent == []

    # Exactly six entries pass whole (a window starting at 00:00 reuses the first entry)
    six = [
        {"start": "00:00", "end": "08:00"},
        {"start": "10:00", "end": "12:00"},
        {"start": "14:00", "end": "16:00"},
    ]
    assert await mgr.async_set_room_schedule("room-1", {"monday": six}) == 2
    week = sent[0][1]["weekly_schedule"]
    assert "mode" not in week
    assert week["num_of_transitions"] == 6 and len(week["transitions"]) == 6
    assert cfg.schedule == {"monday": six}


# --- config entry: options flow, carry-over at setup, live option changes ----------------------


def _entry(options: dict[str, Any] | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONNECTION_MODE: CONNECTION_MODE_MQTT_COMPANION,
            CONF_MQTT_PREFIXES: ["zigbee2mqtt"],
        },
        options=options or {},
        unique_id="mqtt_companion:zigbee2mqtt",
    )


def _patch_ha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    monkeypatch.setattr(mqtt_mod, "async_subscribe", AsyncMock(return_value=lambda: None))
    monkeypatch.setattr(mqtt_mod, "async_publish", AsyncMock())
    monkeypatch.setattr("custom_components.danfoss_ally_cloud.async_register_frontend", AsyncMock())


async def test_new_companion_entry_starts_with_both_feeds_closed(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
):
    _patch_ha(monkeypatch)
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    mgr = hass.data[DOMAIN][entry.entry_id]["room_manager"]
    assert (mgr.feed_external_sensor, mgr.feed_load_mean) == (False, False)
    # The decision is stored, so a room with a sensor created later does not open the feed
    assert entry.options == {CONF_COMPANION_FEED_EXTERNAL_SENSOR: False}

    # Options flow of a Companion entry: its own two-field step, applied without a reload
    form = await hass.config_entries.options.async_init(entry.entry_id)
    assert form["type"] is FlowResultType.FORM and form["step_id"] == "companion"
    assert {str(k) for k in form["data_schema"].schema} == {
        CONF_MQTT_PREFIXES,
        CONF_COMPANION_FEED_EXTERNAL_SENSOR,
        CONF_COMPANION_FEED_LOAD_MEAN,
    }
    done = await hass.config_entries.options.async_configure(
        form["flow_id"],
        user_input={CONF_COMPANION_FEED_EXTERNAL_SENSOR: True, CONF_COMPANION_FEED_LOAD_MEAN: True},
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][entry.entry_id]["room_manager"] is mgr
    assert (mgr.feed_external_sensor, mgr.feed_load_mean) == (True, True)

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_editing_bridge_prefixes_reloads_the_companion(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
):
    """Editing the subscribed prefixes reloads the entry (subscriptions are set at start), unlike a
    feed-only change which applies live."""
    _patch_ha(monkeypatch)
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    comp_before = hass.data[DOMAIN][entry.entry_id]["companion"]
    assert comp_before.prefixes == ("zigbee2mqtt",)

    form = await hass.config_entries.options.async_init(entry.entry_id)
    done = await hass.config_entries.options.async_configure(
        form["flow_id"], user_input={CONF_MQTT_PREFIXES: "zigbee2mqtt,danfoss2mqtt"}
    )
    assert done["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    # A reload rebuilt the store with a fresh companion subscribing to both prefixes.
    comp_after = hass.data[DOMAIN][entry.entry_id]["companion"]
    assert comp_after is not comp_before
    assert comp_after.prefixes == ("zigbee2mqtt", "danfoss2mqtt")
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_existing_sensor_room_keeps_its_feed_on_upgrade(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """An entry that already fed its heads from a room sensor is not cut silently: the sensor
    option is stored on. The load mean, never validated, stays closed."""
    _patch_ha(monkeypatch)
    entry = _entry()
    entry.add_to_hass(hass)
    seed = CompanionRoomManager(MqttCompanionCoordinator(hass))
    seed.add_virtual_room(_room())
    await seed.async_save(hass, entry.entry_id)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mgr = hass.data[DOMAIN][entry.entry_id]["room_manager"]
    assert (mgr.feed_external_sensor, mgr.feed_load_mean) == (True, False)
    assert entry.options == {CONF_COMPANION_FEED_EXTERNAL_SENSOR: True}
    assert "room-sensor feed" in caplog.text
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_stored_choice_is_never_overridden_by_the_carry_over(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
):
    _patch_ha(monkeypatch)
    entry = _entry({CONF_COMPANION_FEED_EXTERNAL_SENSOR: False})
    entry.add_to_hass(hass)
    seed = CompanionRoomManager(MqttCompanionCoordinator(hass))
    seed.add_virtual_room(_room())
    await seed.async_save(hass, entry.entry_id)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mgr = hass.data[DOMAIN][entry.entry_id]["room_manager"]
    assert mgr.feed_external_sensor is False
    assert entry.options == {CONF_COMPANION_FEED_EXTERNAL_SENSOR: False}
    assert await hass.config_entries.async_unload(entry.entry_id)
