"""Nombres : consignes confort / réduit d'une PIÈCE.

Écrire une consigne publie le DP de pièce PUIS réécrit le programme (R3) — sans quoi la tête reprend
l'ancienne valeur à la transition suivante. Réservé aux produits vérifiés (CLAUDE.md : n'étendre les
écritures qu'aux modèles éprouvés en réel).
"""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import operations as ops
from .const import (
    DATA_COORDINATOR,
    DOMAIN,
    SETPOINT_MAX,
    SETPOINT_MIN,
    SETPOINT_STEP,
    WRITE_VERIFIED_PRODUCTS,
)
from .coordinator import DanfossCoordinator
from .entity import DanfossRoomEntity

# (clé, translation_key, champ Room, kind pour operations.set_setpoint)
_SETPOINTS = (
    ("consigne_confort", "consigne_confort", "comfort", "comfort"),
    ("consigne_reduit", "consigne_reduit", "setback", "setback"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    entities: list[NumberEntity] = []
    for room in coordinator.rooms:
        if room.get("product_id") not in WRITE_VERIFIED_PRODUCTS:
            continue  # écriture non vérifiée pour ce produit : pas d'entité pilotable
        for key, tkey, field, kind in _SETPOINTS:
            entities.append(
                DanfossRoomSetpoint(coordinator, store, room["id"], key, tkey, field, kind)
            )
    async_add_entities(entities)


class DanfossRoomSetpoint(DanfossRoomEntity, NumberEntity):
    """Consigne confort/réduit d'une pièce (écriture = DP de pièce + programme réécrit, R3)."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = SETPOINT_MIN
    _attr_native_max_value = SETPOINT_MAX
    _attr_native_step = SETPOINT_STEP
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: DanfossCoordinator,
        store: dict,
        group_id: str,
        key: str,
        translation_key: str,
        field: str,
        kind: str,
    ) -> None:
        super().__init__(coordinator, group_id)
        self._store = store
        self._field = field
        self._kind = kind
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"room_{group_id}_{key}"

    @property
    def native_value(self) -> float | None:
        room = self.room
        return room.get(self._field) if room else None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await ops.set_setpoint(self.hass, self._store, self._group_id, self._kind, value)
        except ops.OperationError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()
