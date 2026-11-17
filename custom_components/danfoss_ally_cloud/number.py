"""Nombres : consignes de pièce (confort et réduit).

Par PIÈCE (groupe Danfoss), deux entités ``number`` règlent la consigne DURABLE **confort** (DP 118)
ou **réduit** (DP 109 + 119) via ``client.async_set_group_setpoint`` : publication groupe puis
réécriture d'un jour du programme (R3), exactement le chemin du thermostat de pièce, validé en réel
le 17/11/2026. À la différence du thermostat (qui écrit la consigne du mode courant), ces nombres
visent directement confort ou réduit, quel que soit le mode.

Exposées seulement pour les produits vérifiés (``WRITE_VERIFIED_PRODUCTS``) : ailleurs, aucune
méthode d'écriture voie-1a n'est prouvée, donc pas d'entité (plutôt que mensongère). Vacances
et bornes restent hors contrat tant que leur écriture n'est pas prouvée (contrat §7).
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
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
    SETPOINT_MAX,
    SETPOINT_MIN,
    SETPOINT_STEP,
    WRITE_VERIFIED_PRODUCTS,
)
from .coordinator import DanfossCoordinator


@dataclass(frozen=True, kw_only=True)
class RoomSetpointDescription(NumberEntityDescription):
    """Décrit une consigne de pièce : clé de lecture + DP(s) d'écriture."""

    consigne: str  # clé dans RoomState.consignes : "confort" | "reduit"
    mode: str  # clé dans MODE_GROUP_SETPOINT_DP : "at_home" (confort) | "leaving_home" (réduit)


SETPOINTS: tuple[RoomSetpointDescription, ...] = (
    RoomSetpointDescription(
        key="consigne_confort",
        translation_key="consigne_confort",
        consigne="confort",
        mode="at_home",
    ),
    RoomSetpointDescription(
        key="consigne_reduit",
        translation_key="consigne_reduit",
        consigne="reduit",
        mode="leaving_home",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DanfossCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    entities: list[NumberEntity] = []
    for group_id, room in coordinator.rooms.items():
        if room.pid in WRITE_VERIFIED_PRODUCTS:
            entities += [DanfossRoomSetpoint(coordinator, group_id, desc) for desc in SETPOINTS]
    async_add_entities(entities)


class DanfossRoomSetpoint(CoordinatorEntity[DanfossCoordinator], NumberEntity):
    """Consigne confort ou réduit d'une PIÈCE (écriture durable voie-1a, R3)."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = SETPOINT_STEP
    _attr_mode = NumberMode.BOX
    entity_description: RoomSetpointDescription

    def __init__(
        self, coordinator: DanfossCoordinator, group_id: str, description: RoomSetpointDescription
    ) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self.entity_description = description
        self._attr_unique_id = f"{group_id}_{description.key}"

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
    def native_min_value(self) -> float:
        room = self.room
        return room.borne_basse if room and room.borne_basse is not None else SETPOINT_MIN

    @property
    def native_max_value(self) -> float:
        room = self.room
        return room.borne_haute if room and room.borne_haute is not None else SETPOINT_MAX

    @property
    def native_value(self) -> float | None:
        room = self.room
        if room is None:
            return None
        return room.consignes.get(self.entity_description.consigne)

    async def async_set_native_value(self, value: float) -> None:
        """Publie la consigne confort/réduit sur le groupe puis réécrit le programme (R3)."""
        room = self.room
        if room is None or room.pid not in WRITE_VERIFIED_PRODUCTS:
            raise HomeAssistantError("écriture de consigne indisponible pour cette pièce")
        dps_nums = MODE_GROUP_SETPOINT_DP[self.entity_description.mode]
        valeur = encode_consigne(value, self.native_min_value, self.native_max_value, SETPOINT_STEP)
        dps = {str(dp): valeur for dp in dps_nums}
        try:
            await self.coordinator.client.async_set_group_setpoint(self._group_id, room.pid, dps)
        except CloudError as err:
            raise HomeAssistantError(f"écriture de consigne refusée : {err}") from err
        await self.coordinator.async_request_refresh()
