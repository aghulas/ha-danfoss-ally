"""Diagnostics with strict redaction.

NEVER expose: password, session material (sid/ecode), signing key, chKey, real device identifiers
(devId/nodeId/meshId). A critical responsibility for a public integration. Decoded values
(temperatures, battery...) are kept, but not the ids.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import DanfossCoordinator

# Entry keys to redact (account, session and installation secrets).
TO_REDACT = {
    "username",  # account email (personal data)
    "password",
    "sign_key",
    "ch_key",
    "chKey",
    "device_id",
    "deviceId",
    "sid",
    "ecode",
    "token",
    "access_token",
    "session",
    "local_key",
    "localKey",
    "uid",
}
# Device fields that identify the real hardware (to redact).
DEVICE_REDACT = {"id", "node_id", "mesh_id", "dps"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: DanfossCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    devices = [async_redact_data(asdict(dev), DEVICE_REDACT) for dev in coordinator.data.values()]
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "device_count": len(coordinator.data),
        "devices": devices,
    }
