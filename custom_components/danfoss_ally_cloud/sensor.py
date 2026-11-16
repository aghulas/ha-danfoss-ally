"""Capteurs : batterie, ouverture de vanne (%), code défaut (décodé E1..E15).

Le code `fault` est un champ de bits (SW error code) décodé par api.decode.decoder_defaut.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DanfossDevice
from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import DanfossCoordinator
from .entity import DanfossEntity, DanfossRoomEntity


@dataclass(frozen=True, kw_only=True)
class DanfossSensorDescription(SensorEntityDescription):
    """Description d'un capteur, avec l'accès à la valeur décodée."""

    value: Callable[[DanfossDevice], object]


def _defaut(dev: DanfossDevice) -> str:
    if not dev.defauts:
        return "aucun"
    return ", ".join(e.get("code", "?") for e in dev.defauts)


SENSORS: tuple[DanfossSensorDescription, ...] = (
    DanfossSensorDescription(
        key="batterie",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value=lambda d: d.batterie,
    ),
    DanfossSensorDescription(
        key="ouverture_vanne",
        translation_key="ouverture_vanne",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:radiator",
        value=lambda d: d.ouverture_vanne,
    ),
    DanfossSensorDescription(
        key="defaut",
        translation_key="defaut",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_defaut,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DanfossCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    entities: list[SensorEntity] = [
        DanfossSensor(coordinator, dev.id, desc)
        for dev in coordinator.data.values()
        if dev.est_tete
        for desc in SENSORS
    ]
    entities.extend(DanfossRoomInconsistent(coordinator, room["id"]) for room in coordinator.rooms)
    async_add_entities(entities)


class DanfossSensor(DanfossEntity, SensorEntity):
    """Capteur d'une tête Danfoss."""

    entity_description: DanfossSensorDescription

    def __init__(
        self, coordinator: DanfossCoordinator, device_id: str, description: DanfossSensorDescription
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"
        # Le code défaut reste lisible même hors ligne (dernier état connu).
        if description.key == "defaut":
            self._require_online = False

    @property
    def native_value(self):
        dev = self.device
        return self.entity_description.value(dev) if dev else None


class DanfossRoomInconsistent(DanfossRoomEntity, SensorEntity):
    """Nombre de têtes incohérentes de la pièce (confort/réduit affiché, programme inactif : R6)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "incoherentes"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator: DanfossCoordinator, group_id: str) -> None:
        super().__init__(coordinator, group_id)
        self._attr_unique_id = f"room_{group_id}_incoherentes"

    @property
    def native_value(self) -> int | None:
        room = self.room
        if room is None:
            return None
        return sum(1 for h in room["heads"] if h["inconsistent"])
