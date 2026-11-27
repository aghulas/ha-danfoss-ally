"""Companion write-safety & ops_rooms guard regressions.

Verifies two invariants on a v2 MQTT Companion entry:
1. ``ops_rooms`` operations (room management, relay binding, unbind) refuse cleanly with a contract
   ``OperationError`` instead of crashing with ``AttributeError`` on ``coordinator.client``.
2. Controls whose Z2M ``/set`` key is ignored by ``danfoss2mqtt`` (switches, setpoint bounds,
   isolated-head climate) are unavailable / refused on ``danfoss2mqtt`` heads while remaining
   writable on ``zigbee2mqtt`` heads in the same Companion entry.
Synthetic data only.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from homeassistant.components import mqtt as mqtt_mod
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud.climate import DanfossHeadClimate
from custom_components.danfoss_ally_cloud.companion_adapter import build_companion_store
from custom_components.danfoss_ally_cloud.companion_rooms import CompanionRoomManager
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR, DATA_HEAD_UNBIND
from custom_components.danfoss_ally_cloud.mqtt_companion import MqttCompanionCoordinator
from custom_components.danfoss_ally_cloud.number import HEAD_BOUNDS, DanfossHeadBound
from custom_components.danfoss_ally_cloud.ops_common import OperationError
from custom_components.danfoss_ally_cloud.switch import SWITCHES, DanfossSwitch

Z2M_HEAD = "0x842712fffe86dfbd"
D2M_HEAD = "bf_d2m_iso"


def _mixed_companion_store(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict, AsyncMock]:
    pub = AsyncMock()
    monkeypatch.setattr(mqtt_mod, "async_publish", pub)
    comp = MqttCompanionCoordinator(hass, ("zigbee2mqtt", "danfoss2mqtt"))
    comp.process_mqtt_message(
        "zigbee2mqtt/bridge/devices",
        json.dumps(
            [
                {
                    "ieee_address": Z2M_HEAD,
                    "friendly_name": "Z2M Head",
                    "definition": {"vendor": "Danfoss", "model": "014G2461"},
                }
            ]
        ),
    )
    comp.process_mqtt_message(
        "zigbee2mqtt/Z2M Head",
        json.dumps({"local_temperature": 19.0, "occupied_heating_setpoint": 20.0}),
    )
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/devices",
        json.dumps(
            [
                {
                    "ieee_address": D2M_HEAD,
                    "friendly_name": "D2M Head",
                    "definition": {"vendor": "Danfoss", "model": "014G2461"},
                    "danfoss": {"dev_id": D2M_HEAD, "product_id": "03wvrwpv", "category": "head"},
                }
            ]
        ),
    )
    comp.process_mqtt_message(
        "danfoss2mqtt/D2M Head",
        json.dumps({"local_temperature": 19.0, "occupied_heating_setpoint": 20.0}),
    )
    store = build_companion_store(comp, CompanionRoomManager(comp))
    store[DATA_HEAD_UNBIND] = True  # exercise the Companion guard, not the disabled gate
    return store, pub


async def test_ops_rooms_refused_cleanly_on_companion_not_500(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _mixed_companion_store(hass, monkeypatch)
    room_target = {"type": "room", "id": "grp-1"}

    with pytest.raises(OperationError) as err:
        await ops.create_room(hass, store, "Test", [Z2M_HEAD])
    assert err.value.code == "room_management_companion_unsupported"

    with pytest.raises(OperationError) as err:
        await ops.rename_room(hass, store, room_target, "New")
    assert err.value.code == "room_management_companion_unsupported"

    with pytest.raises(OperationError) as err:
        await ops.delete_room(hass, store, room_target)
    assert err.value.code == "room_management_companion_unsupported"

    with pytest.raises(OperationError) as err:
        await ops.attach_heads(hass, store, room_target, [Z2M_HEAD])
    assert err.value.code == "room_management_companion_unsupported"

    with pytest.raises(OperationError) as err:
        await ops.detach_heads(hass, store, room_target, [Z2M_HEAD])
    assert err.value.code == "room_management_companion_unsupported"

    with pytest.raises(OperationError) as err:
        await ops.set_relay_room(hass, store, "relay-1", room_target, True)
    assert err.value.code == "relay_companion_unsupported"

    with pytest.raises(OperationError) as err:
        await ops.disconnect_head(hass, store, {"type": "device", "id": Z2M_HEAD}, confirm=True)
    assert err.value.code == "unbind_companion_unsupported"


async def test_danfoss2mqtt_unsupported_writes_are_unavailable_and_refused(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, pub = _mixed_companion_store(hass, monkeypatch)
    coord = store[DATA_COORDINATOR]

    # Switches: available on Z2M, unavailable on danfoss2mqtt
    for desc in SWITCHES:
        sw_z2m = DanfossSwitch(coord, Z2M_HEAD, desc, None, None, False)
        sw_d2m = DanfossSwitch(coord, D2M_HEAD, desc, None, None, False)
        assert sw_z2m.available is True
        assert sw_z2m.extra_state_attributes["write_path"] == "mqtt_companion"
        assert sw_d2m.available is False
        assert sw_d2m.extra_state_attributes["write_path"] == "none"
        await sw_d2m.async_turn_on()
    pub.assert_not_awaited()

    # Bounds numbers: available on Z2M, unavailable + refused on danfoss2mqtt
    for desc in HEAD_BOUNDS:
        num_z2m = DanfossHeadBound(coord, Z2M_HEAD, desc, None)
        num_d2m = DanfossHeadBound(coord, D2M_HEAD, desc, None)
        assert num_z2m.available is True
        assert num_z2m.extra_state_attributes["write_path"] == "mqtt_companion"
        assert num_d2m.available is False
        assert num_d2m.extra_state_attributes["write_path"] == "none"
        with pytest.raises(HomeAssistantError):
            await num_d2m.async_set_native_value(22.0)
    pub.assert_not_awaited()

    # Isolated head climate: writable on Z2M, read-only + refused on danfoss2mqtt
    clim_z2m = DanfossHeadClimate(coord, Z2M_HEAD)
    clim_d2m = DanfossHeadClimate(coord, D2M_HEAD)
    assert clim_z2m.extra_state_attributes["write_path"] == "mqtt_companion"
    assert clim_d2m.extra_state_attributes["write_path"] == "none"
    assert clim_d2m.extra_state_attributes["mqtt_bridge"] == "danfoss2mqtt"
    with pytest.raises(HomeAssistantError, match="Read-only"):
        await clim_d2m.async_set_temperature(temperature=21.0)
    pub.assert_not_awaited()


async def test_companion_capabilities_update_on_migration_and_stale_removal(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _ = _mixed_companion_store(hass, monkeypatch)
    comp: MqttCompanionCoordinator = store["companion"]

    assert comp.is_cloud_bridge_device(D2M_HEAD) is True
    assert comp.supports_device_set(D2M_HEAD, "occupied_heating_setpoint") is True
    assert comp.supports_device_set(D2M_HEAD, "keypad_lockout") is False
    assert comp.supports_device_set("unknown_id", "occupied_heating_setpoint") is False

    # Same device migrated to zigbee2mqtt (no danfoss extension): full Z2M /set opens up.
    comp.process_mqtt_message(
        "zigbee2mqtt/bridge/devices",
        json.dumps(
            [
                {
                    "ieee_address": D2M_HEAD,
                    "friendly_name": "D2M Head Migrated",
                    "definition": {"vendor": "Danfoss", "model": "014G2461"},
                }
            ]
        ),
    )
    assert comp.is_cloud_bridge_device(D2M_HEAD) is False
    assert comp.supports_device_set(D2M_HEAD, "keypad_lockout") is True


async def test_cloud_bridge_head_settings_follow_the_keys_the_bridge_advertises(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A danfoss2mqtt head opens a setting only when its bridge advertises it in
    ``danfoss.set_keys`` (proven channel open right now); without the list, only the setpoint."""
    pub = AsyncMock()
    monkeypatch.setattr(mqtt_mod, "async_publish", pub)
    comp = MqttCompanionCoordinator(hass, prefixes=("danfoss2mqtt",))

    def bridge_devices(keys: list[str] | None) -> None:
        ext: dict = {"dev_id": D2M_HEAD}
        if keys is not None:
            ext["set_keys"] = keys
        comp.process_mqtt_message(
            "danfoss2mqtt/bridge/devices",
            json.dumps(
                [
                    {
                        "ieee_address": D2M_HEAD,
                        "friendly_name": "Salle Iso",
                        "definition": {"vendor": "Danfoss", "model": "03wvrwpv"},
                        "danfoss": ext,
                    }
                ]
            ),
        )

    bridge_devices(None)  # older bridge: no list
    assert comp.supports_device_set(D2M_HEAD, "occupied_heating_setpoint") is True
    assert comp.supports_device_set(D2M_HEAD, "keypad_lockout") is False

    bridge_devices(["keypad_lockout", "occupied_heating_setpoint", "window_open_feature"])
    assert comp.supports_device_set(D2M_HEAD, "keypad_lockout") is True
    assert comp.supports_device_set(D2M_HEAD, "window_open_feature") is True
    assert comp.supports_device_set(D2M_HEAD, "min_heat_setpoint_limit") is False

    # The bridge closes it again (gate closed, link down): the key is refused at once.
    bridge_devices(["occupied_heating_setpoint"])
    assert comp.supports_device_set(D2M_HEAD, "keypad_lockout") is False
    # The device disappears from the bridge: nothing is left.
    comp.process_mqtt_message("danfoss2mqtt/bridge/devices", "[]")
    assert comp.supports_device_set(D2M_HEAD, "keypad_lockout") is False
    pub.assert_not_awaited()


async def test_grouped_cloud_bridge_head_settings_say_room_scope(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cloud bridge writes a grouped head's setting on its room: the switch AND the bound
    numbers must say so (``write_scope: room``, ``room_head_count``); an isolated head's say
    head."""
    monkeypatch.setattr(mqtt_mod, "async_publish", AsyncMock())
    comp = MqttCompanionCoordinator(hass, prefixes=("danfoss2mqtt",))
    keys = [
        "keypad_lockout",
        "max_heat_setpoint_limit",
        "min_heat_setpoint_limit",
        "occupied_heating_setpoint",
        "window_open_feature",
    ]
    heads = [("bf_g1", "Salle #1"), ("bf_g2", "Salle #2"), ("bf_iso", "Bureau")]
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/devices",
        json.dumps(
            [
                {
                    "ieee_address": dev_id,
                    "friendly_name": name,
                    "definition": {"vendor": "Danfoss", "model": "03wvrwpv"},
                    "danfoss": {"dev_id": dev_id, "set_keys": keys},
                }
                for dev_id, name in heads
            ]
        ),
    )
    for _dev_id, name in heads:
        comp.process_mqtt_message(
            f"danfoss2mqtt/{name}",
            json.dumps({"local_temperature": 19.0, "max_heat_setpoint_limit": 28.0}),
        )
        comp.process_mqtt_message(f"danfoss2mqtt/{name}/availability", "online")
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/rooms",
        json.dumps(
            [{"group_id": "g1", "name": "Salle", "home_id": "h1", "members": ["bf_g1", "bf_g2"]}]
        ),
    )
    store = build_companion_store(comp, CompanionRoomManager(comp))
    coord = store[DATA_COORDINATOR]
    upper = next(d for d in HEAD_BOUNDS if d.bound == "upper")
    lock = next(d for d in SWITCHES if d.key == "child_lock")

    grouped_bound = DanfossHeadBound(coord, "bf_g1", upper, None).extra_state_attributes
    assert grouped_bound["write_path"] == "mqtt_companion"
    assert grouped_bound["write_scope"] == "room" and grouped_bound["room_head_count"] == 2
    grouped_switch = DanfossSwitch(coord, "bf_g1", lock).extra_state_attributes
    assert grouped_switch["write_scope"] == "room" and grouped_switch["room_head_count"] == 2

    isolated_bound = DanfossHeadBound(coord, "bf_iso", upper, None).extra_state_attributes
    assert isolated_bound["write_scope"] == "head" and "room_head_count" not in isolated_bound
    assert isolated_bound["mqtt_bridge"] == "danfoss2mqtt"
