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

from .api import DanfossDevice, holiday_temperature
from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import DanfossCoordinator
from .entity import DanfossEntity, DanfossHomeEntity


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
    entities: list[SensorEntity] = [
        DanfossSensor(coordinator, dev.id, desc)
        for dev in coordinator.data.values()
        if dev.is_head
        for desc in SENSORS
    ]
    # Holiday setpoint (read only, contract §4.5): one per home.
    entities.extend(
        DanfossHolidaySetpoint(coordinator, gid, holiday.get("name"))
        for gid, holiday in coordinator.holidays.items()
    )
    async_add_entities(entities)


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


class DanfossHolidaySetpoint(DanfossHomeEntity, SensorEntity):
    """Holiday setpoint of a home (read only, contract §4.5).

    Value from the cloud's holiday record (``None`` while no holiday is active or when the record
    carries no recognised temperature field; the raw record is on the holiday binary_sensor).
    """

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_translation_key = "holiday_setpoint"
    _attr_icon = "mdi:bag-suitcase"

    def __init__(self, coordinator: DanfossCoordinator, gid: str, name: str | None) -> None:
        super().__init__(coordinator, gid, name)
        self._attr_unique_id = f"home_{gid}_holiday_setpoint"

    @property
    def native_value(self) -> float | None:
        holiday = self.holiday
        if not holiday or not holiday.get("active"):
            return None
        return holiday_temperature(holiday.get("detail"))
