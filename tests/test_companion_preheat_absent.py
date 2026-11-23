"""Preheat is deliberately not exposed on MQTT-companion heads (zigbee2mqtt / danfoss2mqtt).

The only proven preheat lever is the local tunnel (attribute 0x0025), which a Companion entry does
not own; the cloud DP 1 route is a closed candidate and danfoss2mqtt heads carry no ``mesh_id``.
These tests pin that behaviour (no ``DanfossPreheat`` entity) and the explicit diagnostics signal
that makes the absence non-silent. Synthetic data only. See docs/preheat.md, docs/companion-
contract.md §2.4.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from homeassistant.components import mqtt as mqtt_mod
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud import switch as switch_mod
from custom_components.danfoss_ally_cloud.companion_adapter import build_companion_store
from custom_components.danfoss_ally_cloud.companion_rooms import CompanionRoomManager
from custom_components.danfoss_ally_cloud.const import (
    DATA_COORDINATOR,
    DOMAIN,
)
from custom_components.danfoss_ally_cloud.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.danfoss_ally_cloud.mqtt_companion import MqttCompanionCoordinator
from custom_components.danfoss_ally_cloud.switch import DanfossPreheat


async def _companion_store_with_two_heads(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> dict:
    """A Companion store holding a zigbee2mqtt head and a danfoss2mqtt head (no mesh_id)."""
    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    monkeypatch.setattr(mqtt_mod, "async_subscribe", AsyncMock(return_value=lambda: None))
    monkeypatch.setattr(mqtt_mod, "async_publish", AsyncMock())

    comp = MqttCompanionCoordinator(hass, prefixes=("zigbee2mqtt", "danfoss2mqtt"))
    await comp.async_start()
    # A native zigbee2mqtt head (dev_id falls back to the IEEE address).
    comp.process_mqtt_message(
        "zigbee2mqtt/bridge/devices",
        json.dumps(
            [
                {
                    "ieee_address": "0x842712fffe86dfbd",
                    "friendly_name": "Z-1",
                    "definition": {"vendor": "Danfoss", "model": "014G2461"},
                }
            ]
        ),
    )
    # A danfoss2mqtt (cloud path 1a) head: has a Tuya dev_id but NO mesh_id.
    comp.process_mqtt_message(
        "danfoss2mqtt/bridge/devices",
        json.dumps(
            [
                {
                    "ieee_address": "0xc1c1c1c1c1c1c1c1",
                    "friendly_name": "C-1",
                    "definition": {"vendor": "Danfoss", "model": "014G2461"},
                    "danfoss": {
                        "dev_id": "tuya-c1",
                        "product_id": "03wvrwpv",
                        "category": "head",
                    },
                }
            ]
        ),
    )
    mgr = CompanionRoomManager(comp)
    return build_companion_store(comp, mgr)


async def test_no_preheat_switch_on_any_companion_head(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = await _companion_store_with_two_heads(hass, monkeypatch)
    # The danfoss2mqtt head must indeed have no mesh_id (the symptom's root cause).
    c1 = store[DATA_COORDINATOR].data["tuya-c1"]
    assert c1.mesh_id is None

    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id="companion-preheat")
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = store

    added: list = []
    await switch_mod.async_setup_entry(hass, entry, lambda ents: added.extend(ents))

    # No preheat entity for any head: the Companion owns no local tunnel.
    assert not any(isinstance(e, DanfossPreheat) for e in added)
    # The companion setting switches (child lock, window detection) ARE created, both heads.
    unique_ids = {getattr(e, "unique_id", None) for e in added}
    assert "tuya-c1_child_lock" in unique_ids
    assert "tuya-c1_window_detection" in unique_ids
    assert "0x842712fffe86dfbd_child_lock" in unique_ids


async def test_diagnostics_preheat_block_is_explicit_in_companion_mode(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = await _companion_store_with_two_heads(hass, monkeypatch)
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id="companion-diag")
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = store

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["preheat"]["companion_mode"] is True
    assert diag["preheat"]["switch_exposed"] is False
    assert "companion" in diag["preheat"]["reason"].lower()
