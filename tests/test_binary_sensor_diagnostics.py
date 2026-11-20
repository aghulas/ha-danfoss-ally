"""Diagnostic entities aligned on Zigbee2MQTT (docs/zigbee2mqtt-alignment.md, batch A)."""

from unittest.mock import patch

from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud.const import DOMAIN

from .common import ENTRY_DATA, FakeCloudClient, head, relay


async def _setup(hass: HomeAssistant, devices) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr")
    entry.add_to_hass(hass)
    fake = FakeCloudClient(devices=devices)
    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_heat_required_and_mounting_mode_follow_the_dps(hass: HomeAssistant):
    await _setup(hass, [head(heat_request=True, mounting=False)])
    assert hass.states.get("binary_sensor.salon_heat_required").state == STATE_ON
    assert hass.states.get("binary_sensor.salon_mounting_mode").state == STATE_OFF
    registry = er.async_get(hass)
    for entity_id, unique_id in (
        ("binary_sensor.salon_heat_required", "dev-1_heat_required"),
        ("binary_sensor.salon_mounting_mode", "dev-1_mounting_mode"),
    ):
        reg = registry.async_get(entity_id)
        assert reg is not None
        assert reg.unique_id == unique_id
        assert reg.entity_category is EntityCategory.DIAGNOSTIC


async def test_unknown_when_the_cloud_does_not_carry_the_dp(hass: HomeAssistant):
    await _setup(hass, [head()])
    assert hass.states.get("binary_sensor.salon_heat_required").state == STATE_UNKNOWN
    assert hass.states.get("binary_sensor.salon_mounting_mode").state == STATE_UNKNOWN


async def test_unavailable_while_the_head_is_offline(hass: HomeAssistant):
    await _setup(hass, [head(online=False, heat_request=True, mounting=True)])
    assert hass.states.get("binary_sensor.salon_heat_required").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.salon_mounting_mode").state == STATE_UNAVAILABLE


async def test_not_created_for_a_relay(hass: HomeAssistant):
    await _setup(hass, [relay()])
    assert hass.states.get("binary_sensor.boiler_relay_heat_required") is None
    assert hass.states.get("binary_sensor.boiler_relay_mounting_mode") is None


async def test_battery_is_a_diagnostic_entity_with_its_id_unchanged(hass: HomeAssistant):
    await _setup(hass, [head()])
    reg = er.async_get(hass).async_get("sensor.salon_battery")
    assert reg is not None
    assert reg.unique_id == "dev-1_battery"
    assert reg.entity_category is EntityCategory.DIAGNOSTIC
