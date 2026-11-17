"""Diagnostics avec rédaction stricte.

Ne JAMAIS exposer : mot de passe, matériel de session (sid/ecode), clé de signature, chKey,
identifiants d'appareil réels (devId/nodeId/meshId). Responsabilité critique pour une intégration
publique. Les valeurs décodées (températures, batterie…) sont conservées, mais pas les ids.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import DanfossCoordinator

# Clés de l'entrée à rédiger (secrets de compte, session et installation).
TO_REDACT = {
    "username",
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
# Champs d'appareil qui identifient le matériel réel (à rédiger).
DEVICE_REDACT = {"id", "node_id", "mesh_id", "dps"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: DanfossCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    devices = [async_redact_data(asdict(dev), DEVICE_REDACT) for dev in coordinator.data.values()]
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "nombre_appareils": len(coordinator.data),
        "appareils": devices,
    }
