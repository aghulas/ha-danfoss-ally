"""Numbers: room setpoints (comfort and setback), and an isolated head's setpoint bounds.

Per ROOM (Danfoss group), two ``number`` entities set the DURABLE **comfort** (DP 118) or
**setback** (DP 109 + 119) setpoint via ``client.async_set_group_setpoint``: group publish then a
one-day schedule rewrite (R3), exactly the room thermostat's path, verified on real hardware on
2026-11-17. Unlike the thermostat (which writes the current mode's setpoint), these numbers target
comfort or setback directly, whatever the mode.

Exposed only for verified products (``WRITE_VERIFIED_PRODUCTS``): elsewhere no path-1a write method
is proven, so no entity (rather than a lying one).

Per ISOLATED head, ``number`` entities set the **upper bound** (DP 18) and the **lower bound**
(DP 27) of its setpoint, and its **comfort** (DP 118 + 16), **setback** (DP 119) and **pause**
(DP 120) setpoints, over the Tuya cloud MQTT channel — the only path the app itself uses for them
(contract §4.2). They exist only when the cloud-MQTT write option is on and their DPs are open on
that channel (proven, or candidates listed for their supervised trial): with no proven path there
is no entity rather than a lying one.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import (
    MQTT_CANDIDATE_DPS,
    MQTT_TENTHS_RANGE,
    CloudError,
    DanfossDevice,
    encode_setpoint,
    mqtt_dp_open,
    write_allowed,
)
from .api.mqtt_client import CloudMqttLink
from .api.rooms import RoomState
from .const import (
    DATA_CLOUD_MQTT,
    DATA_COORDINATOR,
    DATA_MQTT_LINK,
    DOMAIN,
    DP_AT_HOME_SETPOINT,
    DP_HOLIDAY_SETPOINT,
    DP_LEAVING_HOME_SETPOINT,
    DP_LOWER_TEMP,
    DP_PAUSE_SETPOINT,
    DP_PREHEAT,
    DP_TEMP_SET,
    DP_UPPER_TEMP,
    MODE_GROUP_SETPOINT_DP,
    SETPOINT_MAX,
    SETPOINT_MIN,
    SETPOINT_STEP,
    WRITE_VERIFIED_PRODUCTS,
)
from .coordinator import DanfossCoordinator
from .entity import DanfossEntity
from .mqtt_write import async_mqtt_write, supervised_for


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
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanfossCoordinator = data[DATA_COORDINATOR]
    entities: list[NumberEntity] = []
    for group_id, room in coordinator.rooms.items():
        if room.pid in WRITE_VERIFIED_PRODUCTS:
            entities += [DanfossRoomSetpoint(coordinator, group_id, desc) for desc in SETPOINTS]
    # Isolated-head settings over cloud MQTT: only with the write option on, a link, and the DP
    # open on that channel FOR THAT HEAD (proven, or under supervised trial on the designated
    # trial head). An entity whose DP is closed by configuration is not provided, and its registry
    # entry is removed so it does not linger "restored, unavailable" after a trial is disarmed.
    link: CloudMqttLink | None = data.get(DATA_MQTT_LINK)
    cloud_mqtt_on = bool(data.get(DATA_CLOUD_MQTT))
    closed: list[str] = []
    for dev in coordinator.data.values():
        if not (dev.is_head and write_allowed(dev)):
            continue
        isolated = coordinator.group_of(dev.id) is None
        supervised = supervised_for(data, dev.id)
        for desc in HEAD_BOUNDS:
            if not (cloud_mqtt_on and isolated and mqtt_dp_open(desc.dp, supervised)):
                closed.append(f"{dev.id}_{desc.key}")
            elif link is not None:
                entities.append(DanfossHeadBound(coordinator, dev.id, desc, link, supervised))
            # Open but no link (it failed to start): transient, the registry entry is kept.
        for sp in HEAD_SETPOINTS:
            # A setpoint needs ALL its DPs open (comfort: 118 and 16).
            if not (
                cloud_mqtt_on and isolated and all(mqtt_dp_open(dp, supervised) for dp in sp.dps)
            ):
                closed.append(f"{dev.id}_{sp.key}")
            elif link is not None:
                entities.append(DanfossHeadSetpoint(coordinator, dev.id, sp, link, supervised))
    remove_closed_head_numbers(hass, entry, closed)
    async_add_entities(entities)


def remove_closed_head_numbers(
    hass: HomeAssistant, entry: ConfigEntry, unique_ids: list[str]
) -> None:
    """Remove the registry entries of isolated-head numbers that the configuration no longer
    provides: the cloud-MQTT option is off, their DP is not open for that head (a supervised trial
    was disarmed, or moved to another head), or the head joined a room.

    Exact unique ids of heads of the current fleet only, and only entries of this config entry: a
    room's numbers (``<group id>_comfort_setpoint``) are never touched. An entity that is merely
    not created because the link failed to start is not in the list, so a transient failure costs
    no customisation."""
    if not unique_ids:
        return
    registry = er.async_get(hass)
    for unique_id in unique_ids:
        entity_id = registry.async_get_entity_id("number", DOMAIN, unique_id)
        if entity_id is None:
            continue
        registered = registry.async_get(entity_id)
        if registered is not None and registered.config_entry_id == entry.entry_id:
            registry.async_remove(entity_id)


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


# --- isolated head: setpoint bounds over Tuya cloud MQTT ------------------------------------------

PATH_MQTT = "cloud_mqtt"
PATH_NONE = "none"


@dataclass(frozen=True, kw_only=True)
class HeadBoundDescription(NumberEntityDescription):
    """A setpoint bound of a head: its DP and the read of the decoded value."""

    dp: int
    bound: str  # "upper" | "lower"


HEAD_BOUNDS: tuple[HeadBoundDescription, ...] = (
    HeadBoundDescription(
        key="upper_bound",
        translation_key="upper_bound",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:thermometer-chevron-up",
        dp=DP_UPPER_TEMP,
        bound="upper",
    ),
    HeadBoundDescription(
        key="lower_bound",
        translation_key="lower_bound",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:thermometer-chevron-down",
        dp=DP_LOWER_TEMP,
        bound="lower",
    ),
)


def bound_write_dps(
    desc: HeadBoundDescription, dev: DanfossDevice, celsius: float
) -> dict[int, int]:
    """The DPs to publish to set a bound of ``dev`` to ``celsius``, after checking the value against
    the head's own state. Raises ``HomeAssistantError`` with the reason when it must not be sent.

    Checks, beyond the schema range and step of the DP:

    - the bounds stay ordered (lower <= upper);
    - the new bound does not exclude the head's comfort or setback setpoint. What a head does with
      a setpoint left outside its bounds is not established, so it is refused: change the setpoint
      first.

    Lower bound and pause setpoint: the app publishes DP 120 together with DP 27 "when the pause
    setpoint must follow" (contract §4.2). Reading retained here, to confirm in the supervised
    trial: when the new lower bound is above the head's pause setpoint, the pause setpoint is
    raised to it in the same frame.
    """
    low, high = (x / 10 for x in MQTT_TENTHS_RANGE[desc.dp])
    try:
        raw = encode_setpoint(celsius, low, high, SETPOINT_STEP)
    except CloudError as err:
        raise HomeAssistantError(f"bound refused: {err}") from err
    value = raw / 10
    if desc.bound == "upper" and dev.min_setpoint is not None and value < dev.min_setpoint:
        raise HomeAssistantError(
            f"bound refused: under the head's lower bound ({dev.min_setpoint} °C)"
        )
    if desc.bound == "lower" and dev.max_setpoint is not None and value > dev.max_setpoint:
        raise HomeAssistantError(
            f"bound refused: above the head's upper bound ({dev.max_setpoint} °C)"
        )
    for name in ("comfort", "setback"):
        setpoint = dev.setpoints.get(name)
        if setpoint is None:
            continue
        if (desc.bound == "upper" and setpoint > value) or (
            desc.bound == "lower" and setpoint < value
        ):
            raise HomeAssistantError(
                f"bound refused: it would exclude the {name} setpoint ({setpoint} °C); change "
                "that setpoint first"
            )
    dps = {desc.dp: raw}
    if desc.bound == "lower":
        pause = dev.setpoints.get("pause")
        if pause is not None and pause < value:
            dps[DP_PAUSE_SETPOINT] = raw
    return dps


class _HeadMqttNumber(DanfossEntity, NumberEntity):
    """A numeric setting of an ISOLATED head written over Tuya cloud MQTT.

    Unavailable when the head is no longer isolated, or the link cannot publish: there is no other
    proven path for these settings. Never optimistic: the value shown is the one the cloud returns.
    """

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = SETPOINT_STEP
    _attr_mode = NumberMode.BOX
    _dps: tuple[int, ...] = ()  # every DP the write sends

    def __init__(
        self,
        coordinator: DanfossCoordinator,
        device_id: str,
        link: CloudMqttLink,
        supervised_dps: frozenset[int] = frozenset(),
    ) -> None:
        super().__init__(coordinator, device_id)
        self._link = link
        self._supervised_dps = supervised_dps

    def _write_path(self, dev: DanfossDevice | None) -> str:
        if dev is None or not write_allowed(dev) or not dev.node_id or not dev.mesh_id:
            return PATH_NONE
        if self.coordinator.group_of(dev.id) is not None:
            return PATH_NONE  # a grouped head is written through its room, not here
        if not all(mqtt_dp_open(dp, self._supervised_dps) for dp in self._dps):
            return PATH_NONE
        return PATH_MQTT if self._link.can_publish(dev.mesh_id) else PATH_NONE

    @property
    def available(self) -> bool:
        return super().available and self._write_path(self.device) != PATH_NONE

    @property
    def extra_state_attributes(self) -> dict[str, str | bool]:
        path = self._write_path(self.device)
        attrs: dict[str, str | bool] = {"write_path": path}
        if path == PATH_MQTT:
            attrs["write_scope"] = "head"
            if any(dp in MQTT_CANDIDATE_DPS for dp in self._dps):
                attrs["write_trial"] = True
        return attrs


class DanfossHeadBound(_HeadMqttNumber):
    """Upper or lower setpoint bound of an ISOLATED head, written over Tuya cloud MQTT."""

    entity_description: HeadBoundDescription

    def __init__(
        self,
        coordinator: DanfossCoordinator,
        device_id: str,
        description: HeadBoundDescription,
        link: CloudMqttLink,
        supervised_dps: frozenset[int] = frozenset(),
    ) -> None:
        super().__init__(coordinator, device_id, link, supervised_dps)
        self.entity_description = description
        self._dps = (description.dp,)
        self._attr_unique_id = f"{device_id}_{description.key}"
        low, high = MQTT_TENTHS_RANGE[description.dp]
        self._attr_native_min_value = low / 10
        self._attr_native_max_value = high / 10

    @property
    def native_value(self) -> float | None:
        dev = self.device
        if dev is None:
            return None
        return dev.max_setpoint if self.entity_description.bound == "upper" else dev.min_setpoint

    async def async_set_native_value(self, value: float) -> None:
        dev = self.device
        if dev is None or self._write_path(dev) != PATH_MQTT:
            raise HomeAssistantError("bound write unavailable for this head")
        dps = bound_write_dps(self.entity_description, dev, value)
        await async_mqtt_write(
            self.coordinator, self._link, dev, dps, supervised=self._supervised_dps
        )


# --- isolated head: comfort / setback / pause setpoints over Tuya cloud MQTT ----------------------

# The app's "Settings" block: after publishing a setpoint of this block over MQTT, the app also
# posts the WHOLE block through ``settings.change`` (the cloud-side store of the workflow, contract
# §4.2). Keys in the order the app sends them.
SETTINGS_BLOCK_DPS: tuple[int, ...] = (
    DP_PREHEAT,
    DP_AT_HOME_SETPOINT,
    DP_LEAVING_HOME_SETPOINT,
    DP_HOLIDAY_SETPOINT,
)


@dataclass(frozen=True, kw_only=True)
class HeadSetpointDescription(NumberEntityDescription):
    """A per-mode setpoint of a head: what is read, and what the app publishes to set it."""

    setpoint: str  # key in DanfossDevice.setpoints
    dp: int  # the setting DP: its confirmation is required
    companions: tuple[int, ...] = ()  # DPs the app publishes along, with the same value
    in_settings_block: bool = False  # the app also posts the settings block over HTTP

    @property
    def dps(self) -> tuple[int, ...]:
        return (self.dp, *self.companions)


HEAD_SETPOINTS: tuple[HeadSetpointDescription, ...] = (
    HeadSetpointDescription(
        key="comfort_setpoint",
        translation_key="comfort_setpoint",
        setpoint="comfort",
        dp=DP_AT_HOME_SETPOINT,
        companions=(DP_TEMP_SET,),  # the app publishes {"118": v, "16": v}
        in_settings_block=True,
    ),
    HeadSetpointDescription(
        key="setback_setpoint",
        translation_key="setback_setpoint",
        setpoint="setback",
        dp=DP_LEAVING_HOME_SETPOINT,  # {"119": v} alone: no DP 109 on an isolated head
        in_settings_block=True,
    ),
    HeadSetpointDescription(
        key="pause_setpoint",
        translation_key="pause_setpoint",
        entity_category=EntityCategory.CONFIG,
        setpoint="pause",
        dp=DP_PAUSE_SETPOINT,
    ),
)


def settings_block(dev: DanfossDevice, changed: dict[int, int]) -> dict[str, object]:
    """The whole settings block to post after a setpoint write: the head's current values, as the
    cloud holds them, with ``changed`` applied. Raises ``HomeAssistantError`` when a value of the
    block is unknown: the block is sent whole or not at all, never with a guessed value."""
    block: dict[str, object] = {}
    for dp in SETTINGS_BLOCK_DPS:
        value = changed.get(dp, dev.dps.get(str(dp)))
        if value is None or value == "":
            raise HomeAssistantError(
                f"setpoint write refused: DP {dp} of the head's settings block is unknown, so the "
                "block the app posts with a setpoint change cannot be built"
            )
        block[str(dp)] = value
    return block


class DanfossHeadSetpoint(_HeadMqttNumber):
    """Comfort, setback or pause setpoint of an ISOLATED head, written the way the app does.

    1. The setpoint DP(s) are published over Tuya cloud MQTT and the setting DP's confirmation is
       awaited (``async_mqtt_write``).
    2. For the settings of the app's "Settings" block (comfort, setback), the whole block is then
       posted through ``settings.change``, as the app does: it keeps the cloud-side store of the
       workflow in step with the head. That HTTP call alone never reaches an isolated head (W-3);
       it is not the write.

    The value is checked against the head's own bounds before anything is sent.
    """

    entity_description: HeadSetpointDescription

    def __init__(
        self,
        coordinator: DanfossCoordinator,
        device_id: str,
        description: HeadSetpointDescription,
        link: CloudMqttLink,
        supervised_dps: frozenset[int] = frozenset(),
    ) -> None:
        super().__init__(coordinator, device_id, link, supervised_dps)
        self.entity_description = description
        self._dps = description.dps
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_min_value(self) -> float:
        dev = self.device
        return dev.min_setpoint if dev and dev.min_setpoint is not None else SETPOINT_MIN

    @property
    def native_max_value(self) -> float:
        dev = self.device
        return dev.max_setpoint if dev and dev.max_setpoint is not None else SETPOINT_MAX

    @property
    def native_value(self) -> float | None:
        dev = self.device
        return dev.setpoints.get(self.entity_description.setpoint) if dev else None

    async def async_set_native_value(self, value: float) -> None:
        desc = self.entity_description
        dev = self.device
        if dev is None or self._write_path(dev) != PATH_MQTT:
            raise HomeAssistantError("setpoint write unavailable for this head")
        try:
            raw = encode_setpoint(
                value, self.native_min_value, self.native_max_value, SETPOINT_STEP
            )
        except CloudError as err:
            raise HomeAssistantError(f"setpoint refused: {err}") from err
        # Build the HTTP block BEFORE publishing: if it cannot be built, nothing is sent at all.
        block = settings_block(dev, {desc.dp: raw}) if desc.in_settings_block else None
        await async_mqtt_write(
            self.coordinator,
            self._link,
            dev,
            dict.fromkeys(desc.dps, raw),
            supervised=self._supervised_dps,
            confirm_dps=(desc.dp,),
        )
        if block is None:
            return
        try:
            # ``gwId`` = the head's own devId for this block, as the app sends it.
            await self.coordinator.client.async_write_setting(dev.id, dev.product_id or "", block)
        except CloudError as err:
            raise HomeAssistantError(
                "setpoint written on the head and confirmed, but the cloud-side settings block "
                f"was refused ({err}): the cloud may hold the previous value"
            ) from err
