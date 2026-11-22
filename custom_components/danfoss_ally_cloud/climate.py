"""Climate platform: one thermostat per ROOM (Danfoss group), aligned on the Danfoss model.

Danfoss drives a multi-head room through its GROUP (shared schedule and setpoints); the app no
longer sets heads individually. So we expose **one climate per room**:

- aggregated read of the member heads (mean temperature, active setpoint, mode, heating);
- DURABLE setpoint write per current mode (comfort = DP 118; setback = DP 109 + 119) via
  ``client.async_set_group_setpoint`` (group publish + one-day schedule rewrite), verified on real
  hardware.

Heads stay exposed as sub-devices (sensors, switches, local preheat). An **isolated** head (outside
a group) keeps its own ``DanfossHeadClimate``:

- with ``enable_cloud_mqtt`` off (the default), it is **read-only**: no proven path-1a HTTP write
  method outside a room (a non-lying entity rather than a false one). It still shows its ACTIVE
  setpoint as ``target_temperature`` (Home Assistant only publishes it when TARGET_TEMPERATURE is
  declared), and refuses a setpoint change with a clear error;
- with ``enable_cloud_mqtt`` on and connected, in schedule modes (``at_home`` / ``leaving_home``),
  ``async_set_temperature`` writes the current mode's setpoint over Tuya cloud MQTT (DP 118 + 16
  for comfort, DP 119 for setback) followed by the settings block over HTTP, the exact path proven
  on real hardware for ``DanfossHeadSetpoint``.

State attributes: ``active_setpoint`` is the setpoint in force (DP 171 OccupiedSetpoint, the value
the Danfoss app shows); ``setpoints`` holds the per-mode settings (``comfort`` = DP 118,
``setback`` = DP 119, ``manual``, ``pause``, ``holiday``) plus ``temp_set`` (DP 16, which reports
the comfort setpoint whatever the slot). ``setpoints.setpoint`` is a DEPRECATED alias of
``temp_set`` kept for existing automations; it is NOT the active setpoint.

An isolated head's climate also says what a setpoint write would do right now: ``write_path``
(``cloud_mqtt`` or ``none``) and, when a write is possible, ``write_setting`` (``comfort`` or
``setback``): the setting the write changes. That choice follows the mode the cloud reports
(DP 2), which is a **label** (R5): it does not tell whether the head is in a comfort slot of its
schedule. A comfort write also publishes DP 16, as the app does, which sets the head's current
setpoint at once; outside a comfort slot the head goes back to its schedule's value by itself
within 1 to 5 minutes (real hardware, 2026-11-19), so such a write causes a few minutes of heat
demand. ``target_temperature`` stays the ACTIVE setpoint (DP 171): after a write it is not
necessarily the value just written.
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
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import CloudError, DanfossDevice, encode_setpoint, mqtt_dp_open, write_allowed
from .api.mqtt_client import CloudMqttLink
from .api.rooms import RoomState
from .const import (
    DATA_CLOUD_MQTT,
    DATA_COORDINATOR,
    DATA_MQTT_LINK,
    DOMAIN,
    DP_AT_HOME_SETPOINT,
    DP_LEAVING_HOME_SETPOINT,
    DP_TEMP_SET,
    MODE_GROUP_SETPOINT_DP,
    SETPOINT_STEP,
    WRITE_VERIFIED_PRODUCTS,
)
from .coordinator import DanfossCoordinator
from .entity import DanfossEntity
from .mqtt_write import async_mqtt_write, settings_block, supervised_for

# Mode DP 2 -> readable label (state attribute).
_MODES = {
    "manual": "manual",
    "at_home": "comfort",
    "leaving_home": "setback",
    "pause": "pause",
    "holiday": "holiday",
    "holiday_sat": "holiday",
}

# Mode DP 2 -> (setting DP, companion DPs) for an isolated head written over Tuya cloud MQTT.
_HEAD_MQTT_MODE_DPS: dict[str, tuple[int, tuple[int, ...]]] = {
    "at_home": (DP_AT_HOME_SETPOINT, (DP_TEMP_SET,)),
    "leaving_home": (DP_LEAVING_HOME_SETPOINT, ()),
}

_MIN_TEMP = 5.0
_MAX_TEMP = 35.0

# ``write_path`` state attribute of an isolated head's climate (same values as the numbers').
_PATH_COMPANION = "mqtt_companion"
_PATH_MQTT = "cloud_mqtt"
_PATH_NONE = "none"

# Deprecated ``setpoints`` key: up to 1.0.1 DP 16 (temp_set) was published as ``setpoint``, a
# misleading name since it is the comfort setpoint, not the active one. Kept as an alias of
# ``temp_set`` so existing automations keep working; to be removed in a future release.
_DEPRECATED_SETPOINT_ALIAS = "setpoint"


def _setpoint_attributes(active: float | None, setpoints: dict[str, float]) -> dict:
    """``active_setpoint`` + per-mode ``setpoints`` (with the deprecated ``setpoint`` alias)."""
    attrs: dict = {}
    if active is not None:
        attrs["active_setpoint"] = active
    if setpoints:
        out = dict(setpoints)
        if "temp_set" in out:
            out[_DEPRECATED_SETPOINT_ALIAS] = out["temp_set"]
        attrs["setpoints"] = out
    return attrs


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanfossCoordinator = data[DATA_COORDINATOR]
    link: CloudMqttLink | None = data.get(DATA_MQTT_LINK)
    cloud_mqtt_on = bool(data.get(DATA_CLOUD_MQTT))

    known_rooms: set[str] = set()
    known_heads: set[str] = set()

    def _collect_new_entities() -> list[ClimateEntity]:
        new_entities: list[ClimateEntity] = []
        for group_id in coordinator.rooms:
            if group_id not in known_rooms:
                known_rooms.add(group_id)
                new_entities.append(DanfossRoomClimate(coordinator, group_id))
        for dev in coordinator.data.values():
            if dev.is_head and dev.id not in coordinator.grouped_ids and dev.id not in known_heads:
                known_heads.add(dev.id)
                new_entities.append(
                    DanfossHeadClimate(
                        coordinator,
                        dev.id,
                        link=link,
                        cloud_mqtt_enabled=cloud_mqtt_on,
                        supervised_dps=supervised_for(data, dev.id),
                    )
                )
        return new_entities

    async_add_entities(_collect_new_entities())

    @callback
    def _async_sync_topology() -> None:
        """Create or retire climate entities when rooms or group memberships change at runtime."""
        registry = er.async_get(hass)
        for group_id in list(known_rooms):
            # Never on a mere absence from ``rooms`` (a partial device list empties it).
            if coordinator.room_retired(group_id):
                known_rooms.discard(group_id)
                ent_id = registry.async_get_entity_id("climate", DOMAIN, group_id)
                if ent_id is not None:
                    ent = registry.async_get(ent_id)
                    if ent is not None and ent.config_entry_id == entry.entry_id:
                        registry.async_remove(ent_id)
        for head_id in list(known_heads):
            if head_id in coordinator.grouped_ids:
                known_heads.discard(head_id)
                ent_id = registry.async_get_entity_id("climate", DOMAIN, head_id)
                if ent_id is not None:
                    ent = registry.async_get(ent_id)
                    if ent is not None and ent.config_entry_id == entry.entry_id:
                        registry.async_remove(ent_id)
        added = _collect_new_entities()
        if added:
            async_add_entities(added)

    entry.async_on_unload(coordinator.async_add_listener(_async_sync_topology))


class DanfossRoomClimate(CoordinatorEntity[DanfossCoordinator], ClimateEntity):
    """Thermostat of a ROOM (group of heads): aggregated read + durable setpoint write."""

    _attr_has_entity_name = True
    _attr_name = None  # main entity of the "room" device
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
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
    def native_current_temperature(self) -> float | None:
        room = self.room
        return room.temperature if room else None

    @property
    def native_target_temperature(self) -> float | None:
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
        attrs.update(_setpoint_attributes(room.setpoint, room.setpoints))
        return attrs

    async def async_set_temperature(self, **kwargs) -> None:
        """Write the room's DURABLE setpoint per current mode (comfort/setback).

        Publishes the setpoint on the group then rewrites one schedule day (see
        ``client.async_set_group_setpoint``). Outside comfort/setback modes -> clean error (the
        other modes have no proven path-1a group method).
        """
        room = self.room
        if room is None:
            return
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        room_manager = getattr(self.coordinator, "room_manager", None)
        if room_manager is not None:
            try:
                encoded = encode_setpoint(temp, self.min_temp, self.max_temp, SETPOINT_STEP)
            except CloudError as err:
                raise HomeAssistantError(f"setpoint refused: {err}") from err
            await room_manager.async_set_room_setpoint(self._group_id, encoded / 10)
            return
        if room.pid not in WRITE_VERIFIED_PRODUCTS:
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
        # R-3: the room's heads just changed; read them via the per-device route on the next polls
        # (incl. the refresh below) so the write round-trip is reflected without the bulk-route lag.
        self.coordinator.note_commanded(
            [
                dev.id
                for dev in self.coordinator.data.values()
                if dev.is_head and self.coordinator.group_of(dev.id) == self._group_id
            ]
        )
        await self.coordinator.async_request_refresh()


class DanfossHeadClimate(DanfossEntity, ClimateEntity):
    """Thermostat of an ISOLATED head (outside a group).

    With ``enable_cloud_mqtt`` off (default), no setpoint write is proven outside a room:
    TARGET_TEMPERATURE is declared so that Home Assistant publishes the ACTIVE setpoint (DP 171,
    the one the Danfoss app shows) as the target temperature, and ``async_set_temperature`` refuses
    with a clear error rather than pretending to write.

    With ``enable_cloud_mqtt`` on and connected, in schedule modes (``at_home`` / ``leaving_home``),
    ``async_set_temperature`` writes the active mode's setpoint over Tuya cloud MQTT (DP 118 + 16
    for comfort, DP 119 for setback) and posts the settings block over HTTP, matching
    ``DanfossHeadSetpoint``.
    """

    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_target_temperature_step = SETPOINT_STEP
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_min_temp = _MIN_TEMP
    _attr_max_temp = _MAX_TEMP

    def __init__(
        self,
        coordinator: DanfossCoordinator,
        device_id: str,
        *,
        link: CloudMqttLink | None = None,
        cloud_mqtt_enabled: bool = False,
        supervised_dps: frozenset[int] = frozenset(),
    ) -> None:
        super().__init__(coordinator, device_id)
        self._link = link
        self._cloud_mqtt_enabled = cloud_mqtt_enabled
        self._supervised_dps = supervised_dps

    @property
    def unique_id(self) -> str:
        return self._device_id

    @property
    def native_current_temperature(self) -> float | None:
        dev = self.device
        return dev.temperature if dev else None

    @property
    def native_target_temperature(self) -> float | None:
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

    def _mqtt_ready(self, dev: DanfossDevice | None) -> bool:
        """True if this isolated head can be written over the Tuya cloud-MQTT link right now."""
        if not (self._cloud_mqtt_enabled and self._link is not None):
            return False
        if dev is None or not write_allowed(dev) or not dev.node_id or not dev.mesh_id:
            return False
        if self.coordinator.group_of(dev.id) is not None:
            return False
        return self._link.can_publish(dev.mesh_id)

    def _write_setting(self, dev: DanfossDevice | None) -> str | None:
        """The setting a setpoint write would change right now, or None when it would be refused.

        ``comfort`` (DP 118 + 16) or ``setback`` (DP 119), picked from the mode the cloud reports
        (DP 2). That mode is a label (R5), not the head's position in its schedule: the answer says
        which setting is written, not that the head is in a slot of that kind.
        """
        if dev is None or not self._mqtt_ready(dev):
            return None
        mode_spec = _HEAD_MQTT_MODE_DPS.get(dev.mode or "")
        if mode_spec is None:
            return None
        setting_dp, companions = mode_spec
        if not all(mqtt_dp_open(dp, self._supervised_dps) for dp in (setting_dp, *companions)):
            return None
        return _MODES[dev.mode or ""]

    @property
    def extra_state_attributes(self) -> dict:
        dev = self.device
        if dev is None:
            return {}
        attrs: dict = {}
        if dev.mode is not None:
            attrs["mode"] = _MODES.get(dev.mode, dev.mode)
        attrs.update(_setpoint_attributes(dev.setpoint, dev.setpoints))
        companion = getattr(self.coordinator, "companion", None)
        if companion is not None:
            attrs["write_path"] = _PATH_COMPANION
            route = companion.device_route.get(dev.id)
            if route is not None:
                attrs["mqtt_bridge"] = route[0]
            return attrs
        # What a setpoint write would do now, so that nobody has to guess it from ``mode``.
        setting = self._write_setting(dev)
        attrs["write_path"] = _PATH_NONE if setting is None else _PATH_MQTT
        if setting is not None:
            attrs["write_setting"] = setting
        return attrs

    async def async_set_temperature(self, **kwargs) -> None:
        """Write an isolated head's setpoint over MQTT Companion or Cloud MQTT, else refuse."""
        dev = self.device
        companion = getattr(self.coordinator, "companion", None)
        if companion is not None and dev is not None:
            temp = kwargs.get(ATTR_TEMPERATURE)
            if temp is None:
                return
            low = dev.min_setpoint if dev.min_setpoint is not None else self.min_temp
            high = dev.max_setpoint if dev.max_setpoint is not None else self.max_temp
            try:
                raw = encode_setpoint(temp, low, high, SETPOINT_STEP)
            except CloudError as err:
                raise HomeAssistantError(f"setpoint refused: {err}") from err
            try:
                await companion.async_send_device_set(dev.id, setpoint=raw / 10)
            except (KeyError, ValueError) as err:
                raise HomeAssistantError(f"setpoint write failed: {err}") from err
            return
        if not self._mqtt_ready(dev) or dev is None or self._link is None:
            raise HomeAssistantError(
                "Read-only: this head is not in a Danfoss room, and no HTTP setpoint write is "
                "proven for a head outside a room. Add it to a room in the Danfoss app, or enable "
                "the cloud-MQTT write path for isolated heads in the integration options."
            )
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        mode_spec = _HEAD_MQTT_MODE_DPS.get(dev.mode or "")
        if mode_spec is None:
            raise HomeAssistantError(
                "Setpoint editable only in comfort (at_home) or setback "
                f"(leaving_home) mode; current mode: {dev.mode!r}."
            )
        setting_dp, companions = mode_spec
        all_dps = (setting_dp, *companions)
        if not all(mqtt_dp_open(dp, self._supervised_dps) for dp in all_dps):
            raise HomeAssistantError("setpoint write unavailable for this head")
        # Against the head's OWN bounds, as ``DanfossHeadSetpoint`` does: what a head does with a
        # setpoint left outside its bounds is not established, so it is refused before sending.
        low = dev.min_setpoint if dev.min_setpoint is not None else self.min_temp
        high = dev.max_setpoint if dev.max_setpoint is not None else self.max_temp
        try:
            raw = encode_setpoint(temp, low, high, SETPOINT_STEP)
        except CloudError as err:
            raise HomeAssistantError(f"setpoint refused: {err}") from err
        block = settings_block(dev, {setting_dp: raw})
        await async_mqtt_write(
            self.coordinator,
            self._link,
            dev,
            dict.fromkeys(all_dps, raw),
            supervised=self._supervised_dps,
            confirm_dps=(setting_dp,),
        )
        try:
            await self.coordinator.client.async_write_setting(dev.id, dev.product_id or "", block)
        except CloudError as err:
            raise HomeAssistantError(
                "setpoint written on the head and confirmed, but the cloud-side settings block "
                f"was refused ({err}): the cloud may hold the previous value"
            ) from err


# Climate temperature API. HA 2026.11 reads `native_*` (unit-converted) and deprecates the legacy
# `temperature_unit` / `current_temperature` / `target_temperature` (removed in 2027.11); older HA
# only knows the legacy names. Our classes implement `native_*`; on an HA without them, the legacy
# names are served from `native_*` here. Set dynamically (not in the class body) so a class never
# provides both on HA 2026.11+, which would mask the native API and fail type-checking there.
if not hasattr(ClimateEntity, "native_current_temperature"):
    # setattr on purpose (B010): a plain assignment would be type-checked against the HA stubs.
    _LEGACY = {
        "temperature_unit": property(lambda self: self._attr_native_temperature_unit),
        "current_temperature": property(lambda self: self.native_current_temperature),
        "target_temperature": property(lambda self: self.native_target_temperature),
    }
    for _cls in (DanfossRoomClimate, DanfossHeadClimate):
        for _name, _prop in _LEGACY.items():
            setattr(_cls, _name, _prop)
