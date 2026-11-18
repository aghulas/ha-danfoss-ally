"""Climate platform: one thermostat per ROOM (Danfoss group), aligned on the Danfoss model.

Danfoss drives a multi-head room through its GROUP (shared schedule and setpoints); the app no
longer sets heads individually. So we expose **one climate per room**:

- aggregated read of the member heads (mean temperature, active setpoint, mode, heating);
- DURABLE setpoint write per current mode (comfort = DP 118; setback = DP 109 + 119) via
  ``client.async_set_group_setpoint`` (group publish + one-day schedule rewrite), verified on real
  hardware.

Heads stay exposed as sub-devices (sensors, switches, local preheat). An **isolated** head (outside
a group) keeps a **read-only** climate: no proven path-1a write method outside a room (a
non-lying entity rather than a false one).
"""

from __future__ import annotations

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
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
    SETPOINT_STEP,
    WRITE_VERIFIED_PRODUCTS,
)
from .coordinator import DanfossCoordinator
from .entity import DanfossEntity

# Mode DP 2 -> readable label (state attribute).
_MODES = {
    "manual": "manual",
    "at_home": "comfort",
    "leaving_home": "setback",
    "pause": "pause",
    "holiday": "holiday",
    "holiday_sat": "holiday",
}

_MIN_TEMP = 5.0
_MAX_TEMP = 35.0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DanfossCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    entities: list[ClimateEntity] = [
        DanfossRoomClimate(coordinator, group_id) for group_id in coordinator.rooms
    ]
    # Isolated heads (outside a group): read-only climate.
    entities += [
        DanfossHeadClimate(coordinator, dev.id)
        for dev in coordinator.data.values()
        if dev.is_head and dev.id not in coordinator.grouped_ids
    ]
    async_add_entities(entities)


class DanfossRoomClimate(CoordinatorEntity[DanfossCoordinator], ClimateEntity):
    """Thermostat of a ROOM (group of heads): aggregated read + durable setpoint write."""

    _attr_has_entity_name = True
    _attr_name = None  # main entity of the "room" device
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_target_temperature_step = SETPOINT_STEP

    def __init__(self, coordinator: DanfossCoordinator, group_id: str) -> None:
        super().__init__(coordinator)
        self._group_id = group_id
        self._attr_unique_id = group_id

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
    def supported_features(self) -> ClimateEntityFeature:
        # Setpoint write only for verified products (otherwise read-only).
        room = self.room
        if room is not None and room.pid in WRITE_VERIFIED_PRODUCTS:
            return ClimateEntityFeature.TARGET_TEMPERATURE
        return ClimateEntityFeature(0)

    @property
    def current_temperature(self) -> float | None:
        room = self.room
        return room.temperature if room else None

    @property
    def target_temperature(self) -> float | None:
        room = self.room
        return room.setpoint if room else None

    @property
    def min_temp(self) -> float:
        room = self.room
        return room.min_setpoint if room and room.min_setpoint is not None else _MIN_TEMP

    @property
    def max_temp(self) -> float:
        room = self.room
        return room.max_setpoint if room and room.max_setpoint is not None else _MAX_TEMP

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        room = self.room
        if room is None or room.heating is None:
            return None
        return HVACAction.HEATING if room.heating else HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict:
        room = self.room
        if room is None:
            return {}
        attrs: dict = {"head_count": room.head_count}
        if room.mode is not None:
            attrs["mode"] = _MODES.get(room.mode, room.mode)
        if room.setpoints:
            attrs["setpoints"] = room.setpoints
        return attrs

    async def async_set_temperature(self, **kwargs) -> None:
        """Write the room's DURABLE setpoint per current mode (comfort/setback).

        Publishes the setpoint on the group then rewrites one schedule day (see
        ``client.async_set_group_setpoint``). Outside comfort/setback modes -> clean error (the
        other modes have no proven path-1a group method).
        """
        room = self.room
        if room is None or room.pid not in WRITE_VERIFIED_PRODUCTS:
            return
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        dps_nums = MODE_GROUP_SETPOINT_DP.get(room.mode or "")
        if not dps_nums:
            raise HomeAssistantError(
                "Setpoint editable only in comfort (at_home) or setback "
                f"(leaving_home) mode; current mode: {room.mode!r}."
            )
        encoded = encode_setpoint(temp, self.min_temp, self.max_temp, SETPOINT_STEP)
        dps = {str(dp): encoded for dp in dps_nums}
        try:
            await self.coordinator.client.async_set_group_setpoint(self._group_id, room.pid, dps)
        except CloudError as err:
            raise HomeAssistantError(f"setpoint write refused: {err}") from err
        await self.coordinator.async_request_refresh()


class DanfossHeadClimate(DanfossEntity, ClimateEntity):
    """Thermostat of an ISOLATED head (outside a group), READ-ONLY.

    No proven path-1a write method outside a room: we do not expose TARGET_TEMPERATURE (a non-lying
    entity). Grouped heads are driven through their room (see ``DanfossRoomClimate``) and have no
    climate of their own.
    """

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_target_temperature_step = SETPOINT_STEP
    _attr_supported_features = ClimateEntityFeature(0)
    _attr_min_temp = _MIN_TEMP
    _attr_max_temp = _MAX_TEMP

    @property
    def unique_id(self) -> str:
        return self._device_id

    @property
    def current_temperature(self) -> float | None:
        dev = self.device
        return dev.temperature if dev else None

    @property
    def target_temperature(self) -> float | None:
        dev = self.device
        return dev.setpoint if dev else None

    @property
    def min_temp(self) -> float:
        dev = self.device
        return dev.min_setpoint if dev and dev.min_setpoint is not None else self._attr_min_temp

    @property
    def max_temp(self) -> float:
        dev = self.device
        return dev.max_setpoint if dev and dev.max_setpoint is not None else self._attr_max_temp

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        dev = self.device
        if dev is None or not dev.online:
            return None
        heating = dev.heating  # work_state (DP 3), valve opening as fallback
        if heating is None:
            return None
        return HVACAction.HEATING if heating else HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict:
        dev = self.device
        if dev is None:
            return {}
        attrs: dict = {}
        if dev.mode is not None:
            attrs["mode"] = _MODES.get(dev.mode, dev.mode)
        if dev.setpoints:
            attrs["setpoints"] = dev.setpoints
        return attrs
