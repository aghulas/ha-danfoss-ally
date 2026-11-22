"""Provider-conflict Repairs issue: Companion + a left-over v1.x direct-cloud entry.

The v2 Companion is meant to be the sole provider of the Danfoss head entities. A left-over
direct-cloud ``danfoss_ally_cloud`` entry running alongside it duplicates every head's entities,
so ``repairs.sync_provider_conflict`` raises a non-fixable warning that clears on its own once the
old entry is gone. See ``docs/v2-cutover.md``.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud.const import (
    CONF_CONNECTION_MODE,
    CONF_MQTT_PREFIXES,
    CONF_USERNAME,
    CONNECTION_MODE_MQTT_COMPANION,
    DOMAIN,
)
from custom_components.danfoss_ally_cloud.repairs import (
    clear_repairs,
    sync_provider_conflict,
)

_ISSUE_PREFIX = "duplicate_cloud_provider_"


def _companion_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONNECTION_MODE: CONNECTION_MODE_MQTT_COMPANION,
            CONF_MQTT_PREFIXES: ["zigbee2mqtt", "danfoss2mqtt"],
        },
        unique_id="mqtt_companion:zigbee2mqtt,danfoss2mqtt",
    )
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    return entry


def _cloud_entry(hass: HomeAssistant, unique_id: str = "user@example.test") -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: unique_id},
        unique_id=unique_id,
    )
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    return entry


def test_issue_raised_when_cloud_entry_coexists(hass: HomeAssistant) -> None:
    reg = ir.async_get(hass)
    companion = _companion_entry(hass)
    _cloud_entry(hass)

    sync_provider_conflict(hass, companion)

    issue = reg.async_get_issue(DOMAIN, _ISSUE_PREFIX + companion.entry_id)
    assert issue is not None
    assert issue.translation_key == "duplicate_cloud_provider"
    # The account e-mail (the cloud entry's title/unique_id) must never leak into placeholders.
    placeholders = issue.translation_placeholders or {}
    assert placeholders == {"count": "1"}


def test_no_issue_for_companion_alone(hass: HomeAssistant) -> None:
    reg = ir.async_get(hass)
    companion = _companion_entry(hass)

    sync_provider_conflict(hass, companion)

    assert reg.async_get_issue(DOMAIN, _ISSUE_PREFIX + companion.entry_id) is None


def test_two_companions_do_not_conflict(hass: HomeAssistant) -> None:
    reg = ir.async_get(hass)
    first = _companion_entry(hass)
    second = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CONNECTION_MODE: CONNECTION_MODE_MQTT_COMPANION,
            CONF_MQTT_PREFIXES: ["zigbee2mqtt"],
        },
        unique_id="mqtt_companion:zigbee2mqtt",
    )
    second.add_to_hass(hass)
    second.mock_state(hass, ConfigEntryState.LOADED)

    sync_provider_conflict(hass, first)

    assert reg.async_get_issue(DOMAIN, _ISSUE_PREFIX + first.entry_id) is None


def test_not_loaded_cloud_entry_is_ignored(hass: HomeAssistant) -> None:
    reg = ir.async_get(hass)
    companion = _companion_entry(hass)
    cloud = _cloud_entry(hass)
    cloud.mock_state(hass, ConfigEntryState.NOT_LOADED)

    sync_provider_conflict(hass, companion)

    assert reg.async_get_issue(DOMAIN, _ISSUE_PREFIX + companion.entry_id) is None


def test_issue_clears_when_cloud_entry_removed(hass: HomeAssistant) -> None:
    reg = ir.async_get(hass)
    companion = _companion_entry(hass)
    cloud = _cloud_entry(hass)

    sync_provider_conflict(hass, companion)
    assert reg.async_get_issue(DOMAIN, _ISSUE_PREFIX + companion.entry_id) is not None

    # The user disables the old entry: the next Companion update recomputes and clears the issue.
    cloud.mock_state(hass, ConfigEntryState.NOT_LOADED)
    sync_provider_conflict(hass, companion)
    assert reg.async_get_issue(DOMAIN, _ISSUE_PREFIX + companion.entry_id) is None


def test_clear_repairs_removes_provider_issue_on_unload(hass: HomeAssistant) -> None:
    reg = ir.async_get(hass)
    companion = _companion_entry(hass)
    _cloud_entry(hass)

    sync_provider_conflict(hass, companion)
    assert reg.async_get_issue(DOMAIN, _ISSUE_PREFIX + companion.entry_id) is not None

    clear_repairs(hass, companion.entry_id)
    assert reg.async_get_issue(DOMAIN, _ISSUE_PREFIX + companion.entry_id) is None
