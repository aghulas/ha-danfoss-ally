"""Numbers: room setpoints (comfort and setback).

Per ROOM (Danfoss group), two ``number`` entities set the DURABLE **comfort** (DP 118) or
**setback** (DP 109 + 119) setpoint via ``client.async_set_group_setpoint``: group publish then a
one-day schedule rewrite (R3), exactly the room thermostat's path, verified on real hardware on
2026-11-17. Unlike the thermostat (which writes the current mode's setpoint), these numbers target
comfort or setback directly, whatever the mode.

Exposed only for verified products (``WRITE_VERIFIED_PRODUCTS``): elsewhere no path-1a write method
is proven, so no entity (rather than a lying one). Holiday and bounds stay out of contract until
their write is proven (contract §7).
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

from .api import CloudError, encode_setpoint
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
    """Describes a room setpoint: read key + write DP(s)."""

    setpoint: str  # key in RoomState.setpoints: "comfort" | "setback"
    mode_key: str  # key in MODE_GROUP_SETPOINT_DP: "at_home" (comfort) | "leaving_home" (setback)


SETPOINTS: tuple[RoomSetpointDescription, ...] = (
    RoomSetpointDescription(
        key="comfort_setpoint",
        translation_key="comfort_setpoint",
        setpoint="comfort",
        mode_key="at_home",
    ),
    RoomSetpointDescription(
        key="setback_setpoint",
        translation_key="setback_setpoint",
        setpoint="setback",
        mode_key="leaving_home",
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
    """Comfort or setback setpoint of a ROOM (durable path-1a write, R3)."""

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
        return bool(super().available and room is not None and room.online)

    @property
    def device_info(self) -> DeviceInfo:
        room = self.room
        return DeviceInfo(
            identifiers={(DOMAIN, f"group_{self._group_id}")},
            name=(room.name if room and room.name else self._group_id),
            manufacturer="Danfoss",
            model="Danfoss Ally room (group)",
        )

    @property
    def native_min_value(self) -> float:
        room = self.room
        return room.min_setpoint if room and room.min_setpoint is not None else SETPOINT_MIN

    @property
    def native_max_value(self) -> float:
        room = self.room
        return room.max_setpoint if room and room.max_setpoint is not None else SETPOINT_MAX

    @property
    def native_value(self) -> float | None:
        room = self.room
        if room is None:
            return None
        return room.setpoints.get(self.entity_description.setpoint)

    async def async_set_native_value(self, value: float) -> None:
        """Publish the comfort/setback setpoint on the group then rewrite the schedule (R3)."""
        room = self.room
        if room is None or room.pid not in WRITE_VERIFIED_PRODUCTS:
            raise HomeAssistantError("setpoint write unavailable for this room")
        dps_nums = MODE_GROUP_SETPOINT_DP[self.entity_description.mode_key]
        encoded = encode_setpoint(
            value, self.native_min_value, self.native_max_value, SETPOINT_STEP
        )
        dps = {str(dp): encoded for dp in dps_nums}
        try:
            await self.coordinator.client.async_set_group_setpoint(self._group_id, room.pid, dps)
        except CloudError as err:
            raise HomeAssistantError(f"setpoint write refused: {err}") from err
        # R-3: same write as the room climate's set_temperature, so same post-command freshening of
        # the room's heads (missing here until the 2026-11-19 real-hardware run, where this path
        # was the only room-setpoint write left to the bulk-route lag).
        self.coordinator.note_commanded(self.coordinator.room_members(self._group_id))
        await self.coordinator.async_request_refresh()
