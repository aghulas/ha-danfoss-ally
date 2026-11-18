"""Binary sensors: online (connectivity), window open.

`online` is authoritative for connectivity (not `update_time`, an event-driven registration
timestamp that can stay frozen - see docs/architecture.md).
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
from .entity import DanfossEntity, DanfossHomeEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DanfossCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    entities: list[BinarySensorEntity] = []
    for dev in coordinator.data.values():
        if not dev.is_head:
            continue
        entities.append(DanfossConnectivity(coordinator, dev.id))
        entities.append(DanfossWindow(coordinator, dev.id))
    # Holiday (read only, contract §4.5): one per home.
    for gid, holiday in coordinator.holidays.items():
        entities.append(DanfossHoliday(coordinator, gid, holiday.get("name")))
    async_add_entities(entities)


class DanfossConnectivity(DanfossEntity, BinarySensorEntity):
    """Online / offline - available even offline (that is its purpose)."""

    _require_online = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "online"

    def __init__(self, coordinator: DanfossCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_online"

    @property
    def is_on(self) -> bool | None:
        dev = self.device
        return dev.online if dev else None


class DanfossWindow(DanfossEntity, BinarySensorEntity):
    """Open window detected by the head (DP 25)."""

    _attr_device_class = BinarySensorDeviceClass.WINDOW
    _attr_translation_key = "window"

    def __init__(self, coordinator: DanfossCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_window"

    @property
    def is_on(self) -> bool | None:
        dev = self.device
        return dev.window_open if dev else None


class DanfossHoliday(DanfossHomeEntity, BinarySensorEntity):
    """Holiday active on a home (read only, contract §4.5).

    The holiday *set/exit* routes are uncaptured, so there is no write counterpart. The full holiday
    record is exposed as an attribute (``detail``).
    """

    _attr_translation_key = "holiday"
    _attr_icon = "mdi:bag-suitcase"

    def __init__(self, coordinator: DanfossCoordinator, gid: str, name: str | None) -> None:
        super().__init__(coordinator, gid, name)
        self._attr_unique_id = f"home_{gid}_holiday"

    @property
    def is_on(self) -> bool | None:
        holiday = self.holiday
        return bool(holiday["active"]) if holiday else None

    @property
    def extra_state_attributes(self) -> dict | None:
        holiday = self.holiday
        detail = holiday.get("detail") if holiday else None
        return {"detail": detail} if detail else None
