"""Home Assistant Repairs issues for offline gateways and active head hardware faults.

Issues are non-fixable warnings that are created automatically when a problem is observed in the
coordinator fleet state and deleted automatically as soon as the device recovers (or the entry is
unloaded). No secret is ever included in issue placeholders.
"""

from __future__ import annotations

from collections.abc import Mapping

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .api import DanfossDevice
from .const import DOMAIN

# Tracks issue_ids currently raised per config entry so cleared/removed devices are deleted cleanly.
_ACTIVE_ISSUES: dict[str, set[str]] = {}


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

    previous = _ACTIVE_ISSUES.get(entry_id, set())
    for stale_id in previous - current:
        ir.async_delete_issue(hass, DOMAIN, stale_id)

    if current:
        _ACTIVE_ISSUES[entry_id] = current
    else:
        _ACTIVE_ISSUES.pop(entry_id, None)


@callback
def clear_repairs(hass: HomeAssistant, entry_id: str) -> None:
    """Remove all Repairs issues owned by ``entry_id`` (called on unload)."""
    for issue_id in _ACTIVE_ISSUES.pop(entry_id, ()):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
