"""Plateforme climate : une tête Danfoss = un thermostat.

Expose température courante, consigne, et les préréglages confort / réduit /
vacances / pause / manuel. Point d'attention repris du pilote Sainte-Marie :
les modes at_home / leaving_home écrits par le cloud passent la tête en MANUEL
au lieu du programme. Le passage confort/réduit doit donc se faire par le
canal qui respecte le programme (voir docs/architecture.md), pas par un simple
write cloud.
"""

from __future__ import annotations

from homeassistant.components.climate import ClimateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    # TODO: pour chaque tête du coordinateur, créer une DanfossClimate.
    async_add_entities([])


class DanfossClimate(ClimateEntity):
    """Tête thermostatique."""

    # TODO: current_temperature, target_temperature (DP 171), preset_modes,
    # set_preset_mode (confort/réduit via le bon canal), set_temperature.
