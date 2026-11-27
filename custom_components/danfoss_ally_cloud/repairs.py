"""Home Assistant Repairs issues for offline gateways and active head hardware faults.

Issues are non-fixable warnings that are created automatically when a problem is observed in the
coordinator fleet state and deleted automatically as soon as the device recovers (or the entry is
unloaded). No secret is ever included in issue placeholders.
"""

from __future__ import annotations

from collections.abc import Mapping

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .api import DanfossDevice
from .const import CONF_CONNECTION_MODE, CONNECTION_MODE_MQTT_COMPANION, DOMAIN

# Tracks issue_ids currently raised per config entry so cleared/removed devices are deleted cleanly.
_ACTIVE_ISSUES: dict[str, set[str]] = {}

# Provider-conflict issues are tracked apart from the fleet issues above: they are keyed on the
# Companion entry, not on a device, and are recomputed from the set of loaded config entries rather
# than from the coordinator fleet, so ``sync_repairs`` (fleet) and ``sync_provider_conflict`` never
# clobber each other's ``_ACTIVE_*`` accounting.
_ACTIVE_PROVIDER_ISSUES: dict[str, set[str]] = {}


def _gateway_issue_id(entry_id: str, dev_id: str) -> str:
    return f"gateway_offline_{entry_id}_{dev_id}"


def _fault_issue_id(entry_id: str, dev_id: str) -> str:
    return f"head_fault_{entry_id}_{dev_id}"


def _format_faults(faults: list[dict[str, object]]) -> str:
    parts: list[str] = []
    for f in faults:
        code = str(f.get("code") or "?")
        label = str(f.get("label") or "").strip()
        parts.append(f"{code} ({label})" if label else code)
    return ", ".join(parts)


@callback
def sync_repairs(
    hass: HomeAssistant,
    entry_id: str,
    devices: Mapping[str, DanfossDevice],
) -> None:
    """Create/update Repairs issues for current anomalies and delete resolved ones."""
    current: set[str] = set()

    for dev in devices.values():
        label = dev.name or dev.id
        if dev.category == "gateway" and dev.online is False:
            issue_id = _gateway_issue_id(entry_id, dev.id)
            current.add(issue_id)
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="gateway_offline",
                translation_placeholders={"name": label},
            )
        if dev.is_head and dev.faults:
            issue_id = _fault_issue_id(entry_id, dev.id)
            current.add(issue_id)
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="head_fault",
                translation_placeholders={
                    "name": label,
                    "faults": _format_faults(dev.faults),
                },
            )
        elif dev.is_head and dev.online is True:
            # Head read online with no active fault: delete its fault issue directly rather than
            # relying only on the ``previous - current`` diff below. ``_ACTIVE_ISSUES`` is in
            # memory, so after a Home Assistant restart an issue persisted in the issue registry is
            # not in ``previous`` and the diff would never clear it; this explicit delete reaps such
            # stale fault issues on the next cycle the head reports ``fault == 0``. Deleting an
            # absent issue is a no-op. A head that is offline (fault unknown) is left untouched so a
            # genuine fault is not falsely resolved while we cannot read it.
            ir.async_delete_issue(hass, DOMAIN, _fault_issue_id(entry_id, dev.id))

    previous = _ACTIVE_ISSUES.get(entry_id, set())
    for stale_id in previous - current:
        ir.async_delete_issue(hass, DOMAIN, stale_id)

    if current:
        _ACTIVE_ISSUES[entry_id] = current
    else:
        _ACTIVE_ISSUES.pop(entry_id, None)


def _duplicate_provider_issue_id(entry_id: str) -> str:
    return f"duplicate_cloud_provider_{entry_id}"


@callback
def sync_provider_conflict(hass: HomeAssistant, companion_entry: ConfigEntry) -> None:
    """Raise a Repairs issue while a v1.x direct-cloud entry runs alongside this Companion entry.

    In v2 the Companion (``zigbee2mqtt`` + ``danfoss2mqtt``) is meant to be the SOLE provider of the
    Danfoss head entities. A left-over v1.x direct-cloud ``danfoss_ally_cloud`` entry provides every
    head a second time, so each head ends up with duplicate entities (the ``_2`` / ``_3`` entity-id
    suffixes). This raises a non-fixable warning pointing at ``docs/v2-cutover.md`` so the user
    disables or removes the old entry; it clears automatically once the old entry is gone.

    The old entry's title is the account e-mail, so it is NEVER put in a placeholder (contract:
    no personal data in issues/diagnostics/logs); only a count is shown. Called both at Companion
    setup and on every Companion update, so removing the old entry clears the issue within seconds.
    """
    others = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.entry_id != companion_entry.entry_id
        and entry.data.get(CONF_CONNECTION_MODE) != CONNECTION_MODE_MQTT_COMPANION
        and entry.state is ConfigEntryState.LOADED
    ]
    issue_id = _duplicate_provider_issue_id(companion_entry.entry_id)
    current: set[str] = set()
    if others:
        current.add(issue_id)
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="duplicate_cloud_provider",
            translation_placeholders={"count": str(len(others))},
        )

    previous = _ACTIVE_PROVIDER_ISSUES.get(companion_entry.entry_id, set())
    for stale_id in previous - current:
        ir.async_delete_issue(hass, DOMAIN, stale_id)
    if current:
        _ACTIVE_PROVIDER_ISSUES[companion_entry.entry_id] = current
    else:
        _ACTIVE_PROVIDER_ISSUES.pop(companion_entry.entry_id, None)


@callback
def clear_repairs(hass: HomeAssistant, entry_id: str) -> None:
    """Remove all Repairs issues owned by ``entry_id`` (called on unload)."""
    for issue_id in _ACTIVE_ISSUES.pop(entry_id, ()):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    for issue_id in _ACTIVE_PROVIDER_ISSUES.pop(entry_id, ()):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
