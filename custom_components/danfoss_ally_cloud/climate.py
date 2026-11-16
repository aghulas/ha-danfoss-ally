"""Plateforme climate : une tête Danfoss = un thermostat.

v0.1 : LECTURE SEULE. Expose température courante et consigne effective (DP 16). L'écriture
(consignes, préréglages) viendra en v0.2, par le canal qui respecte le programme : les modes
at_home / leaving_home écrits par le cloud passent la tête en MANUEL au lieu du programme
(voir docs/architecture.md). Aucune écriture tant que ce n'est pas validé en réel.
"""

from __future__ import annotations

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import DanfossCoordinator
from .entity import DanfossEntity

# Modes DP 2 -> libellé lisible (attribut d'état, pas encore pilotable en v0.1).
_MODES = {
    "manual": "manuel",
    "at_home": "confort",
    "leaving_home": "réduit",
    "pause": "pause",
    "holiday": "vacances",
    "holiday_sat": "vacances",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DanfossCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        DanfossClimate(coordinator, dev.id) for dev in coordinator.data.values() if dev.est_tete
    )


class DanfossClimate(DanfossEntity, ClimateEntity):
    """Tête thermostatique (lecture seule en v0.1)."""

    _attr_name = None  # entité principale de l'appareil
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature(0)  # lecture seule
    _attr_min_temp = 5.0
    _attr_max_temp = 35.0

    @property
    def unique_id(self) -> str:
        return self._device_id

    @property
    def current_temperature(self) -> float | None:
        dev = self.device
        return dev.temperature if dev else None

    @property
    def target_temperature(self) -> float | None:
        dev = self.device
        return dev.consigne if dev else None

    @property
    def min_temp(self) -> float:
        dev = self.device
        return dev.borne_basse if dev and dev.borne_basse is not None else self._attr_min_temp

    @property
    def max_temp(self) -> float:
        dev = self.device
        return dev.borne_haute if dev and dev.borne_haute is not None else self._attr_max_temp

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        dev = self.device
        if dev is None or not dev.en_ligne:
            return None
        if dev.ouverture_vanne is not None:
            return HVACAction.HEATING if dev.ouverture_vanne > 0 else HVACAction.IDLE
        return None

    @property
    def extra_state_attributes(self) -> dict:
        dev = self.device
        if dev is None:
            return {}
        attrs: dict = {}
        if dev.mode is not None:
            attrs["mode"] = _MODES.get(dev.mode, dev.mode)
        if dev.consignes:
            attrs["consignes"] = dev.consignes
        return attrs
