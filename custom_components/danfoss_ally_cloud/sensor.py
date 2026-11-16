"""Capteurs : batterie, ouverture de vanne (%), demande de chaleur, code défaut.

Le code `fault` est un champ de bits (SW error code). Le décodage E1..E15
existe déjà côté pilote (modeles.decoder_defaut) et sera repris dans la
bibliothèque partagée.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([])
