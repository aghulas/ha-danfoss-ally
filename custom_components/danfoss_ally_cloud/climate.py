"""Plateforme climate : une tête Danfoss = un thermostat.

Lecture : température courante et consigne effective (DP 16). Écriture : consigne DURABLE au niveau
PIÈCE (groupe), UNIQUEMENT pour les produits du garde-fou (WRITE_VERIFIED_PRODUCTS) et validée avant
envoi.

⚠ Correction de PR #8 : écrire le DP du MODE sur la tête (settings.change) NE TIENT PAS (l'horaire
réécrit la consigne — vérifié en réel). La vraie voie 1a écrit la consigne du GROUPE de la pièce
puis réécrit un jour du programme (voir api/client.async_set_room_setpoint et api/const.py). On ne
pilote donc la consigne que dans les modes CONFORT (at_home) et RÉDUIT (leaving_home), les seuls
prouvés par capture ; dans les autres modes la consigne n'est pas modifiable (erreur explicite
plutôt qu'écriture mensongère). Une tête NON groupée n'a pas de méthode voie-1a prouvée : l'écriture
échoue proprement.
"""

from __future__ import annotations

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import CloudError, ecriture_autorisee, encode_consigne
from .const import (
    DATA_COORDINATOR,
    DOMAIN,
    MODE_GROUP_SETPOINT_DP,
    SETPOINT_STEP,
)
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
    _attr_target_temperature_step = SETPOINT_STEP
    _attr_min_temp = 5.0
    _attr_max_temp = 35.0

    @property
    def unique_id(self) -> str:
        return self._device_id

    @property
    def supported_features(self) -> ClimateEntityFeature:
        # Écriture de consigne seulement pour les produits du garde-fou (sinon lecture seule).
        dev = self.device
        if dev is not None and ecriture_autorisee(dev):
            return ClimateEntityFeature.TARGET_TEMPERATURE
        return ClimateEntityFeature(0)

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

    async def async_set_temperature(self, **kwargs) -> None:
        """Écrit la consigne DURABLE de la PIÈCE selon le mode courant (confort/réduit).

        Prouvé en réel : écrire le DP16 ``temp_set`` — comme le DP du mode sur la tête (PR #8) —
        ne tient pas sur une tête sur programme (l'horaire réécrit la consigne). La vraie voie 1a
        publie la consigne sur le GROUPE de la pièce (confort = DP 118 ; réduit = DP 109 + 119) puis
        réécrit un jour du programme pour que les têtes la reprennent
        (``client.async_set_room_setpoint``).

        ⚠ Effet de PIÈCE : toutes les têtes du groupe suivent la nouvelle consigne, et le ré-envoi
        du programme touche la vraie prog de chauffe. Hors modes confort/réduit, ou si la tête
        n'est pas groupée, l'écriture échoue proprement (pas de valeur mensongère).
        """
        dev = self.device
        if dev is None or not ecriture_autorisee(dev):
            return
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        dps_nums = MODE_GROUP_SETPOINT_DP.get(dev.mode or "")
        if not dps_nums:
            raise HomeAssistantError(
                "Consigne modifiable seulement en mode confort (at_home) ou réduit "
                f"(leaving_home) ; mode courant : {dev.mode!r}."
            )
        valeur = encode_consigne(temp, self.min_temp, self.max_temp, SETPOINT_STEP)
        dps = {str(dp): valeur for dp in dps_nums}
        try:
            await self.coordinator.client.async_set_room_setpoint(dev.id, dps)
        except CloudError as err:
            raise HomeAssistantError(f"écriture de consigne refusée : {err}") from err
        await self.coordinator.async_request_refresh()
