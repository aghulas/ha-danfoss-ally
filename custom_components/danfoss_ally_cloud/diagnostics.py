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

from .api.messages import CATEGORIES
from .api.mqtt_client import CloudMqttLink
from .const import (
    DATA_COORDINATOR,
    DATA_LOCAL,
    DATA_MESSAGES,
    DATA_MQTT_COVERAGE,
    DATA_MQTT_LINK,
    DOMAIN,
)
from .coordinator import DanfossCoordinator, DanfossMessageCoordinator
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
    "local_supervised_head",  # option holding a real device id
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
    # Preheat availability, surfaced here so its ABSENCE on a head is explicit rather than silent
    # (docs/preheat.md). The only proven preheat lever is the Zigbee attribute 0x0025 through the
    # LOCAL TUNNEL; the cloud DP 1 route is a closed candidate. In MQTT-companion mode the
    # integration holds no local tunnel (and danfoss2mqtt heads carry no mesh_id), so the preheat
    # switch is created on no head there; a supervised DP 1 trial can only run from a direct-cloud
    # entry. No identifier is exposed.
    companion = getattr(coordinator, "companion", None)
    local = data.get(DATA_LOCAL)
    if companion is not None:
        preheat_reason = (
            "MQTT-companion mode: no local tunnel reaches these heads, so no preheat switch is "
            "created (the cloud DP 1 route is a closed candidate and danfoss2mqtt heads carry no "
            "mesh_id); a supervised DP 1 preheat trial can only be armed from a direct-cloud entry"
        )
    elif local is not None:
        preheat_reason = (
            "local tunnel enabled: a preheat switch exists for each tunnel-reachable head"
        )
    else:
        preheat_reason = "local tunnel disabled (enable_local off): no preheat switch"
    diag["preheat"] = {
        "lever": "local tunnel (Zigbee attribute 0x0025)",
        "companion_mode": companion is not None,
        "switch_exposed": local is not None,
        "reason": preheat_reason,
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
    # Message center (docs/message-center.md): counts and codes only. Neither the text (it names
    # rooms and phones) nor any identifier (message id, source devId, account uid).
    messages: DanfossMessageCoordinator | None = data.get(DATA_MESSAGES)
    if messages is not None:
        listed = messages.data or []
        diag["message_center"] = {
            "last_update_success": messages.last_update_success,
            "message_count": len(listed),
            "by_category": {c: sum(1 for m in listed if m.category == c) for c in CATEGORIES},
            "codes": sorted({m.code for m in listed if m.code}),
            "newest_time": listed[0].timestamp.isoformat() if listed else None,
        }
    return diag
