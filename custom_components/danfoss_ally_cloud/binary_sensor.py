"""Capteurs binaires : en ligne, fenêtre ouverte.

`online` fait foi pour la connectivité (pas `update_time`, qui est un
horodatage d'enregistrement événementiel et peut rester figé).
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([])
