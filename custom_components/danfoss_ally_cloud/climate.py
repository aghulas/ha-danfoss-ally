"""Plateforme climate : un thermostat par PIÈCE (groupe Danfoss), aligné sur le modèle Danfoss.

Danfoss pilote une pièce multi-têtes par son GROUPE (programme et consignes communs) ; l'app ne
règle plus les têtes individuellement. On expose donc **un climate par pièce** :

- lecture agrégée des têtes membres (température moyenne, consigne active, mode, chauffe) ;
- écriture DURABLE de la consigne selon le mode courant (confort = DP 118 ; réduit = DP 109 + 119)
  via ``client.async_set_group_setpoint`` (publish groupe + ré-écriture d'un jour du programme),
  validée en réel.

Les têtes restent exposées comme sous-appareils (capteurs, switches, pré-chauffage local). Une tête
**isolée** (hors groupe) garde un climate en **lecture seule** : pas de méthode d'écriture voie-1a
prouvée hors pièce (entité non mensongère plutôt que fausse).
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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import CloudError, encode_consigne
from .api.rooms import RoomState
from .const import (
    DATA_COORDINATOR,
    DOMAIN,
    MODE_GROUP_SETPOINT_DP,
    SETPOINT_STEP,
    WRITE_VERIFIED_PRODUCTS,
)
from .coordinator import DanfossCoordinator
from .entity import DanfossEntity

# Mode DP 2 -> libellé lisible (attribut d'état).
_MODES = {
    "manual": "manuel",
    "at_home": "confort",
    "leaving_home": "réduit",
    "pause": "pause",
    "holiday": "vacances",
    "holiday_sat": "vacances",
}

_MIN_TEMP = 5.0
_MAX_TEMP = 35.0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DanfossCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    entities: list[ClimateEntity] = [
        DanfossRoomClimate(coordinator, group_id) for group_id in coordinator.rooms
    ]
    # Têtes isolées (hors groupe) : climate en lecture seule.
    entities += [
        DanfossHeadClimate(coordinator, dev.id)
        for dev in coordinator.data.values()
        if dev.est_tete and dev.id not in coordinator.grouped_ids
    ]
    async_add_entities(entities)


class DanfossRoomClimate(CoordinatorEntity[DanfossCoordinator], ClimateEntity):
    """Thermostat d'une PIÈCE (groupe de têtes) : lecture agrégée + écriture de consigne durable."""

    _attr_has_entity_name = True
    _attr_name = None  # entité principale de l'appareil « pièce »
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_target_temperature_step = SETPOINT_STEP

    def __init__(self, coordinator: DanfossCoordinator, group_id: str) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self._attr_unique_id = group_id

    @property
    def room(self) -> RoomState | None:
        return self.coordinator.rooms.get(self._group_id)

    @property
    def available(self) -> bool:
        room = self.room
        return bool(super().available and room is not None and room.en_ligne)

    @property
    def device_info(self) -> DeviceInfo:
        room = self.room
        return DeviceInfo(
            identifiers={(DOMAIN, f"group_{self._group_id}")},
            name=(room.nom if room and room.nom else self._group_id),
            manufacturer="Danfoss",
            model="Pièce Danfoss Ally (groupe)",
        )

    @property
    def supported_features(self) -> ClimateEntityFeature:
        # Écriture de consigne seulement pour les produits vérifiés (sinon lecture seule).
        room = self.room
        if room is not None and room.pid in WRITE_VERIFIED_PRODUCTS:
            return ClimateEntityFeature.TARGET_TEMPERATURE
        return ClimateEntityFeature(0)

    @property
    def current_temperature(self) -> float | None:
        room = self.room
        return room.temperature if room else None

    @property
    def target_temperature(self) -> float | None:
        room = self.room
        return room.consigne if room else None

    @property
    def min_temp(self) -> float:
        room = self.room
        return room.borne_basse if room and room.borne_basse is not None else _MIN_TEMP

    @property
    def max_temp(self) -> float:
        room = self.room
        return room.borne_haute if room and room.borne_haute is not None else _MAX_TEMP

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        room = self.room
        if room is None or room.chauffe is None:
            return None
        return HVACAction.HEATING if room.chauffe else HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict:
        room = self.room
        if room is None:
            return {}
        attrs: dict = {"nb_tetes": room.nb_tetes}
        if room.mode is not None:
            attrs["mode"] = _MODES.get(room.mode, room.mode)
        if room.consignes:
            attrs["consignes"] = room.consignes
        return attrs

    async def async_set_temperature(self, **kwargs) -> None:
        """Écrit la consigne DURABLE de la pièce selon le mode courant (confort/réduit).

        Publie la consigne sur le groupe puis réécrit un jour du programme (voir
        ``client.async_set_group_setpoint``). Hors modes confort/réduit → erreur propre (les autres
        modes n'ont pas de méthode groupe voie-1a prouvée).
        """
        room = self.room
        if room is None or room.pid not in WRITE_VERIFIED_PRODUCTS:
            return
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        dps_nums = MODE_GROUP_SETPOINT_DP.get(room.mode or "")
        if not dps_nums:
            raise HomeAssistantError(
                "Consigne modifiable seulement en mode confort (at_home) ou réduit "
                f"(leaving_home) ; mode courant : {room.mode!r}."
            )
        valeur = encode_consigne(temp, self.min_temp, self.max_temp, SETPOINT_STEP)
        dps = {str(dp): valeur for dp in dps_nums}
        try:
            await self.coordinator.client.async_set_group_setpoint(self._group_id, room.pid, dps)
        except CloudError as err:
            raise HomeAssistantError(f"écriture de consigne refusée : {err}") from err
        await self.coordinator.async_request_refresh()


class DanfossHeadClimate(DanfossEntity, ClimateEntity):
    """Thermostat d'une tête ISOLÉE (hors groupe), en LECTURE SEULE.

    Pas de méthode d'écriture voie-1a prouvée hors pièce : on n'expose pas TARGET_TEMPERATURE
    (entité non mensongère). Les têtes groupées, elles, se pilotent par leur pièce (voir
    ``DanfossRoomClimate``) et n'ont pas de climate propre.
    """

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_target_temperature_step = SETPOINT_STEP
    _attr_supported_features = ClimateEntityFeature(0)
    _attr_min_temp = _MIN_TEMP
    _attr_max_temp = _MAX_TEMP

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
        if dev is None or not dev.en_ligne or dev.ouverture_vanne is None:
            return None
        return HVACAction.HEATING if dev.ouverture_vanne > 0 else HVACAction.IDLE

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
