"""Diagnostics avec rédaction stricte.

Ne JAMAIS exposer : jeton de session, mot de passe, clés locales
(localKey) des passerelles, identifiants d'appareil réels. Responsabilité
critique pour une intégration publique.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

TO_REDACT = {"password", "token", "access_token", "session", "local_key", "localKey", "uid"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
    }
