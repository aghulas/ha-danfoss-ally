"""Nombres : température de vacances, bornes haute/basse.

Une borne ne doit pas laisser une consigne de mode hors bornes : valider avant
d'écrire (règle reprise du connecteur).
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([])
