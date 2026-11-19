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
    # Boiler relay: rooms driving it (read only, contract §4.6): one per relay device.
    entities.extend(
        DanfossRelayRooms(coordinator, dev.id) for dev in coordinator.data.values() if dev.is_relay
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

    Temperature of the holiday on record, in progress **or planned** (the holiday binary_sensor
    tells which, its ``scheduled`` attribute flags a planned one). ``None`` when no holiday is on
    record or the record carries no recognised temperature field.
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
        if not holiday or not holiday.get("detail"):
            return None
        return holiday_temperature(holiday["detail"])


class DanfossRelayRooms(DanfossEntity, SensorEntity):
    """Number of rooms currently driving a boiler relay (read only — contract §4.6).

    Available even offline (the linkage is a cloud configuration, not a live reading). The linked
    rooms are exposed as the ``rooms`` attribute.
    """

    _require_online = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "relay_rooms"
    _attr_icon = "mdi:home-thermometer"

    def __init__(self, coordinator: DanfossCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_relay_rooms"

    def _linked(self) -> list[dict]:
        rooms = self.coordinator.relay_rooms.get(self._device_id) or []
        return [r for r in rooms if r.get("linked")]

    @property
    def native_value(self) -> int:
        return len(self._linked())

    @property
    def extra_state_attributes(self) -> dict:
        return {"rooms": [r.get("name") for r in self._linked()]}
