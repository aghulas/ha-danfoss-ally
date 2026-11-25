"""Sensors: battery, valve opening (%), fault code (decoded E1..E15), and the sensors read
through the local tunnel (programming mode, setpoint change source, and the daily settings).

The `fault` code is a bit field (SW error code) decoded by api.decode.decode_fault.

The app's message center (low battery, device added/removed, firmware update, new login) is one
account-level sensor, ``DanfossMessagesSensor``; see its docstring for the representation chosen.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DanfossDevice, holiday_temperature
from .api.local.tunnel import DESCALE_DAYS
from .const import DATA_COORDINATOR, DATA_LOCAL, DATA_MESSAGES, DOMAIN, MESSAGES_RECENT
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator, DanfossMessageCoordinator
from .entity import DanfossEntity, DanfossHomeEntity, DanfossLocalEntity

if TYPE_CHECKING:
    from .mqtt_companion import MqttCompanionCoordinator


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
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        value=lambda d: d.battery,
    ),
    DanfossSensorDescription(
        key="valve_opening",
        translation_key="valve_opening",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: d.valve_opening,
    ),
    DanfossSensorDescription(
        key="fault",
        translation_key="fault",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=_fault,
    ),
)

# Danfoss Ally room sensor (014G2480, Tuya category ``wsdcg``): temperature, humidity, battery,
# all read only (cloud device list, DP 1 / 2 / 4). A device of its own, not a head.
ROOM_SENSORS: tuple[DanfossSensorDescription, ...] = (
    DanfossSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value=lambda d: d.temperature,
    ),
    DanfossSensorDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value=lambda d: d.humidity,
    ),
    DanfossSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        value=lambda d: d.battery,
    ),
)


@dataclass(frozen=True, kw_only=True)
class DanfossLocalSensorDescription(SensorEntityDescription):
    """A sensor decoded from a Zigbee attribute read through the local tunnel."""

    attribute: str  # name given by tunnel.name_attributes
    daily: bool = False  # read by the settings pass (once a day), not by each survey
    states: dict[Any, str] | None = None  # enum sensor: raw value -> state
    scale: float | None = None  # numeric sensor: raw value * scale


_DAYS = {d: d for d in DESCALE_DAYS}

# Value names follow Zigbee2MQTT (docs/zigbee2mqtt-alignment.md). Established on real hardware
# here: 0x0025 values 1 and 3 (bit 0 schedule, bit 1 preheat), the valve exercise day and time
# encodings (written by the descale service), and bit 1 of the adaptation state. The other value
# tables are Zigbee2MQTT's reading of the same attributes (0x0030 being the ZCL
# SetpointChangeSource enumeration). An unlisted raw value reads unknown, the raw value being kept
# as the ``raw`` attribute.
LOCAL_SENSORS: tuple[DanfossLocalSensorDescription, ...] = (
    DanfossLocalSensorDescription(
        key="programming_mode",
        translation_key="programming_mode",
        attribute="programming_mode",
        states={0: "setpoint", 1: "schedule", 3: "schedule_with_preheat", 4: "eco"},
    ),
    DanfossLocalSensorDescription(
        key="setpoint_source",
        translation_key="setpoint_source",
        attribute="setpoint_source",
        states={0: "manual", 1: "schedule", 2: "externally"},
    ),
    DanfossLocalSensorDescription(
        key="window_state",
        translation_key="window_state",
        attribute="window_state",
        daily=True,
        states={0: "quarantine", 1: "closed", 2: "hold", 3: "open", 4: "external_open"},
    ),
    DanfossLocalSensorDescription(
        key="adaptation_status",
        translation_key="adaptation_status",
        attribute="adaptation_state",
        daily=True,
        states={0: "none", 1: "in_progress", 2: "found", 4: "lost"},
    ),
    DanfossLocalSensorDescription(
        key="orientation",
        translation_key="orientation",
        attribute="orientation",
        daily=True,
        states={False: "horizontal", True: "vertical"},
        entity_registry_enabled_default=False,
    ),
    DanfossLocalSensorDescription(
        key="regulation_speed",
        translation_key="regulation_speed",
        attribute="control_speed",
        daily=True,
        entity_registry_enabled_default=False,
    ),
    DanfossLocalSensorDescription(
        key="setpoint_offset",
        translation_key="setpoint_offset",
        attribute="setpoint_offset",
        daily=True,
        scale=0.1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_registry_enabled_default=False,
    ),
    DanfossLocalSensorDescription(
        key="descale_day",
        translation_key="descale_day",
        attribute="descale_day",
        daily=True,
        states=_DAYS,
        entity_registry_enabled_default=False,
    ),
    DanfossLocalSensorDescription(
        key="descale_time",
        translation_key="descale_time",
        attribute="descale_time",
        daily=True,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanfossCoordinator = data[DATA_COORDINATOR]
    local: DanfossLocalCoordinator | None = data.get(DATA_LOCAL)
    entities: list[SensorEntity] = [
        DanfossSensor(coordinator, dev.id, desc)
        for dev in coordinator.data.values()
        if dev.is_head
        for desc in SENSORS
    ]
    # Danfoss Ally room sensor (category ``wsdcg``): temperature / humidity / battery, read only.
    entities.extend(
        DanfossSensor(coordinator, dev.id, desc)
        for dev in coordinator.data.values()
        if dev.is_sensor
        for desc in ROOM_SENSORS
    )
    # Holiday setpoint (read only, contract §4.5): one per home.
    entities.extend(
        DanfossHolidaySetpoint(coordinator, gid, holiday.get("name"))
        for gid, holiday in coordinator.holidays.items()
    )
    # Boiler relay: rooms driving it (read only, contract §4.6): one per relay device.
    entities.extend(
        DanfossRelayRooms(coordinator, dev.id) for dev in coordinator.data.values() if dev.is_relay
    )
    # Read through the local tunnel: the same heads as the preheat switch (addressable ones).
    if local is not None:
        gws = local.manager.gateway_ids
        entities.extend(
            DanfossLocalSensor(local, coordinator, dev.id, desc)
            for dev in coordinator.data.values()
            if dev.is_head and dev.node_id and dev.mesh_id in gws
            for desc in LOCAL_SENSORS
        )
    # The app's message center: one sensor for the account.
    messages: DanfossMessageCoordinator | None = data.get(DATA_MESSAGES)
    if messages is not None:
        entities.append(DanfossMessagesSensor(messages))

    companion: MqttCompanionCoordinator | None = data.get("companion")
    known_heat_demand: set[str] = set()
    if companion is not None:
        for prefix in companion.heat_demand_by_prefix:
            known_heat_demand.add(prefix)
            entities.append(DanfossBridgeHeatDemandSensor(entry.entry_id, companion, prefix))

    async_add_entities(entities)

    if companion is not None:

        @callback
        def _sync_heat_demand() -> None:
            added: list[SensorEntity] = []
            for prefix in companion.heat_demand_by_prefix:
                if prefix not in known_heat_demand:
                    known_heat_demand.add(prefix)
                    added.append(DanfossBridgeHeatDemandSensor(entry.entry_id, companion, prefix))
            if added:
                async_add_entities(added)

        entry.async_on_unload(companion.async_add_listener(_sync_heat_demand))


class DanfossLocalSensor(DanfossLocalEntity, SensorEntity):
    """What the head itself reports, read through the local tunnel (read only).

    Availability and freshness: see ``DanfossLocalEntity``. The per-survey sensors cost no extra
    traffic (their value is in the frame the survey sends for the preheat switch).
    """

    entity_description: DanfossLocalSensorDescription

    def __init__(
        self,
        local: DanfossLocalCoordinator,
        cloud: DanfossCoordinator,
        device_id: str,
        description: DanfossLocalSensorDescription,
    ) -> None:
        super().__init__(local, cloud, device_id)
        self.entity_description = description
        self._attribute = description.attribute
        self._daily = description.daily
        self._attr_unique_id = f"{device_id}_{description.key}"
        if description.states is not None:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = list(description.states.values())

    @property
    def native_value(self) -> str | float | int | None:
        raw = self._raw
        desc = self.entity_description
        if desc.states is not None:
            return desc.states.get(raw) if isinstance(raw, (bool, int, str)) else None
        if desc.scale is not None:
            return round(raw * desc.scale, 2) if isinstance(raw, (int, float)) else None
        return raw if isinstance(raw, (int, float, str)) else None


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

    Stays available while the relay is offline, unlike the relay's on/off: the linkage is a cloud
    configuration read from the account, not a reading of the relay, so it is still true then. The
    linked rooms are exposed as the ``rooms`` attribute.
    """

    _require_online = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "relay_rooms"

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


class DanfossMessagesSensor(CoordinatorEntity[DanfossMessageCoordinator], SensorEntity):
    """The app's message center, for the account (read only, docs/message-center.md).

    Representation: the state is the TIME of the latest device alert (low battery, offline…), a
    timestamp sensor, so "a new alert arrived" is a state change an automation can trigger on and
    the history shows when alerts happened. An unread count was considered and rejected: the
    cloud's ``readStatus`` is 0 on every message and does not follow what the app shows as new, so
    a count would lie. Only device alerts count (``bigMsgType == 1`` or ``msgType > 0``): new
    logins (msgType 0, which include this integration's own) and home messages (msgType -1: device
    added/removed, firmware update) are noise for HA and appear nowhere in this sensor.

    Attributes, newest first, with NO identifier (message id, devId, account uid, home id): the
    head is named by its HA device name. Each new message also fires ``danfoss_ally_cloud_message``
    (``DanfossMessageCoordinator``). No persistent notification is created: the user decides what
    deserves one, from the event or this sensor.

    One device of its own ("Danfoss Ally account"), the message center being account-wide.
    Unavailable when the last read failed, rather than showing a list that may be stale.
    """

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_alert"

    def __init__(self, coordinator: DanfossMessageCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry_id}_last_alert"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"account_{self.coordinator.entry_id}")},
            name="Danfoss Ally account",
            manufacturer="Danfoss",
        )

    @property
    def native_value(self) -> datetime | None:
        for msg in self.coordinator.data or []:
            if msg.is_alert:
                return msg.timestamp
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        alerts = [m for m in self.coordinator.data or [] if m.is_alert]
        name = self.coordinator.device_name
        last = alerts[0] if alerts else None
        return {
            "alert_count": len(alerts),
            "last_alert": last.public_dict(name(last.source_id)) if last is not None else None,
            "alerts": [m.public_dict(name(m.source_id)) for m in alerts[:MESSAGES_RECENT]],
        }


class DanfossBridgeHeatDemandSensor(SensorEntity):
    """Heat demand published by a room coordinator on ``<prefix>/bridge/heat_demand`` (§5.7)."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = False

    def __init__(
        self,
        entry_id: str,
        companion: MqttCompanionCoordinator,
        prefix: str,
    ) -> None:
        self._companion = companion
        self._prefix = prefix
        self._attr_unique_id = f"{entry_id}_heat_demand_{prefix}"
        self._attr_name = f"{prefix} heat demand"

    async def async_added_to_hass(self) -> None:
        @callback
        def _on_update() -> None:
            self.async_write_ha_state()

        self.async_on_remove(self._companion.async_add_listener(_on_update))

    @property
    def available(self) -> bool:
        if not self._companion.bridge_online.get(self._prefix, False):
            return False
        raw = self._companion.heat_demand_by_prefix.get(self._prefix)
        if not raw:
            return False
        ts = raw.get("ts")
        valid_for = raw.get("valid_for_s")
        if isinstance(ts, (int, float)) and isinstance(valid_for, (int, float)):
            return (time.time() - float(ts)) <= float(valid_for)
        return True

    @property
    def native_value(self) -> float | None:
        raw = self._companion.heat_demand_by_prefix.get(self._prefix)
        if not raw:
            return None
        val = raw.get("max_valve")
        return float(val) if isinstance(val, (int, float)) else 0.0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        raw = self._companion.heat_demand_by_prefix.get(self._prefix) or {}
        return {
            "prefix": self._prefix,
            "calling": bool(raw.get("calling", False)),
            "rooms_calling": list(raw.get("rooms_calling") or []),
            "ts": raw.get("ts"),
            "valid_for_s": raw.get("valid_for_s"),
        }
