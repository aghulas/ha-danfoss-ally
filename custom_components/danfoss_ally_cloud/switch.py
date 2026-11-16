"""Interrupteurs : verrouillage enfant (DP 30), détection de fenêtre (DP 116),
pré-chauffage.

Pré-chauffage : écrire le DP 1 côté cloud ne change que le cache de la
passerelle. Le vrai levier est l'attribut Zigbee 0x0025, accessible seulement
par le tunnel local. Si le tunnel local est désactivé, l'interrupteur
pré-chauffage doit être indisponible plutôt que mentir.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([])
