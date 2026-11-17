"""Sensors: battery, valve opening (%), fault code (decoded E1..E15).

The `fault` code is a bit field (SW error code) decoded by api.decode.decode_fault.
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
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DanfossDevice
from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import DanfossCoordinator
from .entity import DanfossEntity


@dataclass(frozen=True, kw_only=True)
class DanfossSensorDescription(SensorEntityDescription):
    """Describes a sensor, with access to the decoded value."""

    value: Callable[[DanfossDevice], object]


def _fault(dev: DanfossDevice) -> str:
    if not dev.faults:
        return "none"
    return ", ".join(e.get("code", "?") for e in dev.faults)


SENSORS: tuple[DanfossSensorDescription, ...] = (
    DanfossSensorDescription(
        # Temperature measured by the head: a sensor specific to EACH head (the climate is now at
        # room level, the per-head temperature must stay visible per head).
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value=lambda d: d.temperature,
    ),
    DanfossSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value=lambda d: d.battery,
    ),
    DanfossSensorDescription(
        key="valve_opening",
        translation_key="valve_opening",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:radiator",
        value=lambda d: d.valve_opening,
    ),
    DanfossSensorDescription(
        key="fault",
        translation_key="fault",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_fault,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DanfossCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        DanfossSensor(coordinator, dev.id, desc)
        for dev in coordinator.data.values()
        if dev.is_head
        for desc in SENSORS
    )


class DanfossSensor(DanfossEntity, SensorEntity):
    """Sensor of a Danfoss head."""

    entity_description: DanfossSensorDescription

    def __init__(
        self, coordinator: DanfossCoordinator, device_id: str, description: DanfossSensorDescription
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"
        # The fault code stays readable even offline (last known state).
        if description.key == "fault":
            self._require_online = False

    @property
    def native_value(self):
        dev = self.device
        return self.entity_description.value(dev) if dev else None
