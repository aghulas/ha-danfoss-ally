"""Tests for icons.json, device_action.py and coordinator adaptive backoff."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol
import yaml
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_ENTITY_ID,
    CONF_TYPE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud import device_action
from custom_components.danfoss_ally_cloud.api import CloudError
from custom_components.danfoss_ally_cloud.const import DOMAIN
from custom_components.danfoss_ally_cloud.coordinator import (
    _MAX_BACKOFF_SECONDS,
    DanfossCoordinator,
)

_COMP_DIR = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "danfoss_ally_cloud"
)


def test_icons_json_covers_all_entities_and_services() -> None:
    """Every entity translation key and every service has an entry in icons.json."""
    icons = json.loads((_COMP_DIR / "icons.json").read_text(encoding="utf-8"))
    strings = json.loads((_COMP_DIR / "strings.json").read_text(encoding="utf-8"))
    services = yaml.safe_load((_COMP_DIR / "services.yaml").read_text(encoding="utf-8"))

    for platform, keys in strings["entity"].items():
        assert platform in icons["entity"], f"Missing platform {platform} in icons.json"
        for key in keys:
            assert key in icons["entity"][platform], (
                f"Missing icon for {platform}.{key} in icons.json"
            )

    for service_name in services:
        assert service_name in icons["services"], (
            f"Missing icon for service {service_name} in icons.json"
        )


def test_device_automation_translations_in_sync() -> None:
    """Device action translation keys exist in strings.json, en.json and fr.json."""
    for rel in ("strings.json", "translations/en.json", "translations/fr.json"):
        data = json.loads((_COMP_DIR / rel).read_text(encoding="utf-8"))
        action_types = data["device_automation"]["action_type"]
        assert device_action.ACTION_SET_TEMPERATURE in action_types
        assert device_action.ACTION_RESTORE_SCHEDULE in action_types


async def test_device_actions_room_and_isolated_head(hass: HomeAssistant) -> None:
    """Rooms expose set_temperature + restore_schedule; isolated heads only set_temperature."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)

    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    room_dev = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "group_12345")},
        name="Living room",
    )
    room_ent = ent_reg.async_get_or_create(
        "climate", DOMAIN, "12345", config_entry=entry, device_id=room_dev.id
    )

    head_dev = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "head_abc")},
        name="Isolated head",
    )
    head_ent = ent_reg.async_get_or_create(
        "climate", DOMAIN, "head_abc", config_entry=entry, device_id=head_dev.id
    )

    room_actions = await device_action.async_get_actions(hass, room_dev.id)
    assert [a[CONF_TYPE] for a in room_actions] == [
        device_action.ACTION_SET_TEMPERATURE,
        device_action.ACTION_RESTORE_SCHEDULE,
    ]
    assert room_actions[0][CONF_ENTITY_ID] == room_ent.entity_id

    head_actions = await device_action.async_get_actions(hass, head_dev.id)
    assert [a[CONF_TYPE] for a in head_actions] == [
        device_action.ACTION_SET_TEMPERATURE
    ]
    assert head_actions[0][CONF_ENTITY_ID] == head_ent.entity_id

    # Capabilities
    cap_temp = await device_action.async_get_action_capabilities(hass, room_actions[0])
    assert "extra_fields" in cap_temp
    cap_restore = await device_action.async_get_action_capabilities(
        hass, room_actions[1]
    )
    assert cap_restore == {}

    # Schema validation
    validated = device_action.ACTION_SCHEMA(
        {**room_actions[0], ATTR_TEMPERATURE: 20.5}
    )
    assert validated[ATTR_TEMPERATURE] == 20.5
    with pytest.raises(vol.Invalid):
        device_action.ACTION_SCHEMA({**room_actions[0], ATTR_TEMPERATURE: 50.0})

    # Execution
    temp_calls: list[dict] = []
    restore_calls: list[dict] = []
    hass.services.async_register(
        "climate", "set_temperature", lambda call: temp_calls.append(dict(call.data))
    )
    hass.services.async_register(
        DOMAIN, "restore_schedule", lambda call: restore_calls.append(dict(call.data))
    )

    await device_action.async_call_action_from_config(
        hass, {**room_actions[0], ATTR_TEMPERATURE: 21.0}, {}, None
    )
    await device_action.async_call_action_from_config(hass, room_actions[1], {}, None)
    # Non-room device calling restore_schedule is a safe no-op
    await device_action.async_call_action_from_config(
        hass,
        {
            CONF_DEVICE_ID: head_dev.id,
            CONF_DOMAIN: DOMAIN,
            CONF_TYPE: device_action.ACTION_RESTORE_SCHEDULE,
        },
        {},
        None,
    )

    assert temp_calls == [{ATTR_ENTITY_ID: room_ent.entity_id, ATTR_TEMPERATURE: 21.0}]
    assert restore_calls == [{"target": {"type": "room", "id": "12345"}}]


async def test_coordinator_exponential_backoff_and_reset(hass: HomeAssistant) -> None:
    """Transient CloudError triggers escalating polling backoff, reset on success."""
    client = MagicMock()
    client.async_list_devices = AsyncMock(side_effect=CloudError("transient"))
    client.device_home = {}

    coordinator = DanfossCoordinator(hass, client, scan_interval=60)
    assert coordinator.update_interval == timedelta(seconds=60)

    # 1st failure: 60s -> 2nd: 120s -> 3rd: 240s -> 4th: 480s -> 5th: 480s (capped at 2**3 * 60)
    expected = [60, 120, 240, 480, 480]
    for secs in expected:
        await coordinator.async_refresh()
        assert coordinator.update_interval == timedelta(seconds=min(secs, _MAX_BACKOFF_SECONDS))

    # Recovery resets interval to base
    client.async_list_devices = AsyncMock(return_value=[])
    client.async_list_rooms = AsyncMock(return_value=[])
    client.async_list_home_rooms = AsyncMock(return_value=[])
    client.async_list_homes = AsyncMock(return_value=[])
    await coordinator.async_refresh()
    assert coordinator.update_interval == timedelta(seconds=60)
