"""Capteurs binaires : en ligne (connectivité), fenêtre ouverte.

`online` fait foi pour la connectivité (pas `update_time`, horodatage d'enregistrement
événementiel qui peut rester figé — voir docs/architecture.md).
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import DanfossCoordinator
from .entity import DanfossEntity, DanfossRoomEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DanfossCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    entities: list[BinarySensorEntity] = []
    for dev in coordinator.data.values():
        if not dev.est_tete:
            continue
        entities.append(DanfossConnectivity(coordinator, dev.id))
        entities.append(DanfossWindow(coordinator, dev.id))
        entities.append(DanfossHeadSchedule(coordinator, dev.id))
    for room in coordinator.rooms:
        entities.append(DanfossRoomSchedule(coordinator, room["id"]))
    async_add_entities(entities)


class DanfossConnectivity(DanfossEntity, BinarySensorEntity):
    """En ligne / hors ligne — disponible même hors ligne (c'est son objet)."""

    _require_online = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "en_ligne"

    def __init__(self, coordinator: DanfossCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_en_ligne"

    @property
    def is_on(self) -> bool | None:
        dev = self.device
        return dev.en_ligne if dev else None


class DanfossWindow(DanfossEntity, BinarySensorEntity):
    """Fenêtre ouverte détectée par la tête (DP 25)."""

    _attr_device_class = BinarySensorDeviceClass.WINDOW
    _attr_translation_key = "fenetre"

    def __init__(self, coordinator: DanfossCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_fenetre"

    @property
    def is_on(self) -> bool | None:
        dev = self.device
        return dev.fenetre_ouverte if dev else None


class DanfossHeadSchedule(DanfossEntity, BinarySensorEntity):
    """Programme actif dans la tête (DP 172, R6) — diagnostic."""

    _require_online = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "programme_actif"

    def __init__(self, coordinator: DanfossCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_programme_actif"

    @property
    def is_on(self) -> bool | None:
        dev = self.device
        return dev.schedule_active if dev else None


class DanfossRoomSchedule(DanfossRoomEntity, BinarySensorEntity):
    """Programme actif de la pièce : vrai si TOUTES ses têtes ont le programme actif (R6)."""

    _attr_translation_key = "programme_actif"

    def __init__(self, coordinator: DanfossCoordinator, group_id: str) -> None:
        super().__init__(coordinator, group_id)
        self._attr_unique_id = f"room_{group_id}_programme_actif"

    @property
    def is_on(self) -> bool | None:
        room = self.room
        if not room or not room["heads"]:
            return None
        etats = [h["schedule_active"] for h in room["heads"]]
        if any(e is None for e in etats):
            return None
        return all(etats)
