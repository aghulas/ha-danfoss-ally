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

from .api.mqtt_client import CloudMqttListener
from .const import DATA_COORDINATOR, DATA_MQTT_PROBE, DOMAIN
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
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanfossCoordinator = entry_data[DATA_COORDINATOR]
    devices = [async_redact_data(asdict(dev), DEVICE_REDACT) for dev in coordinator.data.values()]
    # Cloud-MQTT listen-only probe result (R&D), when the probe ran. Already redacted at the source
    # (no secret/raw payload); redact ``cid`` here too to honour the device-id policy above.
    probe: CloudMqttListener | None = entry_data.get(DATA_MQTT_PROBE)
    probe_diag = (
        async_redact_data(probe.stats.as_diagnostics(), {"cid"}) if probe is not None else None
    )
    return {
        "cloud_mqtt_probe": probe_diag,
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        # Options hold no secret today (intervals, toggles, MQTT topic); redact defensively anyway
        # so a future secret-bearing option can never leak through diagnostics.
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "device_count": len(coordinator.data),
        "devices": devices,
    }
