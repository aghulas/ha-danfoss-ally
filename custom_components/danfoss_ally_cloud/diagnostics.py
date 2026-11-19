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

from .api.mqtt_client import CloudMqttLink
from .const import DATA_COORDINATOR, DATA_MQTT_COVERAGE, DATA_MQTT_LINK, DOMAIN
from .coordinator import DanfossCoordinator
from .mqtt_coverage import CoverageStats

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
    "cloud_mqtt_supervised_head",  # option holding a real device id
}
# Device fields that identify the real hardware (to redact).
DEVICE_REDACT = {"id", "node_id", "mesh_id", "dps"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanfossCoordinator = data[DATA_COORDINATOR]
    devices = [async_redact_data(asdict(dev), DEVICE_REDACT) for dev in coordinator.data.values()]
    diag: dict[str, Any] = {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        # Options hold no secret today (intervals, toggles, MQTT topic); redact defensively anyway
        # so a future secret-bearing option can never leak through diagnostics.
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "device_count": len(coordinator.data),
        "devices": devices,
    }
    # Cloud-MQTT link (only when enable_cloud_mqtt or cloud_mqtt_probe opened one): state and
    # counters, no credential and no identifier.
    link: CloudMqttLink | None = data.get(DATA_MQTT_LINK)
    if link is not None:
        diag["cloud_mqtt_link"] = link.diagnostics()
    # Coverage measure of the cloud-MQTT push (only with cloud_mqtt_probe on). Aggregates only; a
    # head is named by its index in ``devices`` above, never by an identifier.
    coverage: CoverageStats | None = data.get(DATA_MQTT_COVERAGE)
    if coverage is not None:
        diag["cloud_mqtt_coverage"] = coverage.summary(
            coordinator.data.values(), coordinator.grouped_ids
        )
    return diag
