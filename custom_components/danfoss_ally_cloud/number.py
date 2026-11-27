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
that channel: all five are proven (bounds and pause on 2026-11-19, comfort and setback on
2026-11-19/20) and exist for every isolated head. With no proven path there is no entity rather
than a lying one.

An isolated head carries the new comfort or setback value into its own weekly schedule (read back
through the local tunnel about a minute after the write): no schedule rewrite is needed, unlike a
room (R3). The comfort write also publishes DP 16, as the app does, which sets the head's current
setpoint at once; the head goes back to its schedule's value by itself within five minutes, so
outside a comfort slot a comfort write causes a few minutes of heat demand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
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
from .api.local import tunnel
from .api.mqtt_client import CloudMqttLink
from .api.rooms import RoomState
from .const import (
    DATA_CLOUD_MQTT,
    DATA_COORDINATOR,
    DATA_LOCAL,
    DATA_MQTT_LINK,
    DOMAIN,
    DP_AT_HOME_SETPOINT,
    DP_LEAVING_HOME_SETPOINT,
    DP_LOWER_TEMP,
    DP_PAUSE_SETPOINT,
    DP_TEMP_SET,
    DP_UPPER_TEMP,
    MODE_GROUP_SETPOINT_DP,
    SETPOINT_MAX,
    SETPOINT_MIN,
    SETPOINT_STEP,
    WRITE_VERIFIED_PRODUCTS,
)
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator
from .entity import (
    DanfossEntity,
    DanfossLocalTrialEntity,
    companion_write_attrs,
    remove_registry_entries,
)
from .local_write import async_local_write_setting, local_trial_split
from .mqtt_companion import CompanionBridgeError
from .mqtt_write import (  # noqa: F401 - block helpers re-exported
    SETTINGS_BLOCK_DPS,
    async_mqtt_write,
    settings_block,
    supervised_for,
)


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
    link: CloudMqttLink | None = data.get(DATA_MQTT_LINK)
    cloud_mqtt_on = bool(data.get(DATA_CLOUD_MQTT))

    known_rooms: set[str] = set()
    known_head_uids: set[str] = set()

    def _collect_new_entities() -> list[NumberEntity]:
        entities: list[NumberEntity] = []
        companion = getattr(coordinator, "companion", None)
        for group_id, room in coordinator.rooms.items():
            is_coord = companion is not None and companion.is_coordinator_room(group_id)
            if group_id not in known_rooms and (room.pid in WRITE_VERIFIED_PRODUCTS or is_coord):
                known_rooms.add(group_id)
                entities += [DanfossRoomSetpoint(coordinator, group_id, desc) for desc in SETPOINTS]
        # Isolated-head settings over cloud MQTT: only with the write option on, a link, and the DP
        # open on that channel FOR THAT HEAD (proven, or under supervised trial on the designated
        # trial head). An entity whose DP is closed by configuration is not provided, and its
        # registry entry is removed so it does not linger "restored, unavailable".
        closed: list[str] = []
        for dev in coordinator.data.values():
            if not dev.is_head:
                continue
            if companion is not None:
                for desc in HEAD_BOUNDS:
                    uid = f"{dev.id}_{desc.key}"
                    if uid not in known_head_uids:
                        known_head_uids.add(uid)
                        entities.append(DanfossHeadBound(coordinator, dev.id, desc, None))
                continue
            if not write_allowed(dev):
                continue
            isolated = coordinator.group_of(dev.id) is None
            supervised = supervised_for(data, dev.id)
            for desc in HEAD_BOUNDS:
                uid = f"{dev.id}_{desc.key}"
                if not (cloud_mqtt_on and isolated and mqtt_dp_open(desc.dp, supervised)):
                    closed.append(uid)
                    known_head_uids.discard(uid)
                elif link is not None and uid not in known_head_uids:
                    known_head_uids.add(uid)
                    entities.append(DanfossHeadBound(coordinator, dev.id, desc, link, supervised))
                # Open but no link (it failed to start): transient, the registry entry is kept.
            for sp in HEAD_SETPOINTS:
                uid = f"{dev.id}_{sp.key}"
                # A setpoint needs ALL its DPs open (comfort: 118 and 16).
                if not (
                    cloud_mqtt_on
                    and isolated
                    and all(mqtt_dp_open(dp, supervised) for dp in sp.dps)
                ):
                    closed.append(uid)
                    known_head_uids.discard(uid)
                elif link is not None and uid not in known_head_uids:
                    known_head_uids.add(uid)
                    entities.append(DanfossHeadSetpoint(coordinator, dev.id, sp, link, supervised))
        remove_closed_head_numbers(hass, entry, closed)
        return entities

    async_add_entities(_collect_new_entities())

    # Local-tunnel settings under supervised trial (setpoint offset, regulation speed): only on the
    # designated head while armed; the registry entries of the others are removed.
    local: DanfossLocalCoordinator | None = data.get(DATA_LOCAL)
    trial_numbers: list[NumberEntity] = []
    closed_local: list[str] = []
    for tdesc in LOCAL_TRIAL_NUMBERS:
        armed, closed = local_trial_split(
            data, coordinator.data.values(), local, tdesc.setting, tdesc.key
        )
        closed_local += closed
        if local is not None:
            trial_numbers += [
                DanfossLocalSettingNumber(local, coordinator, dev_id, tdesc) for dev_id in armed
            ]
    remove_registry_entries(hass, entry, "number", closed_local)
    async_add_entities(trial_numbers)

    @callback
    def _async_sync_topology() -> None:
        """Create or retire number entities when rooms or group memberships change at runtime."""
        registry = er.async_get(hass)
        for group_id in list(known_rooms):
            # Never on a mere absence from ``rooms`` (a partial device list empties it).
            if coordinator.room_retired(group_id):
                known_rooms.discard(group_id)
                for desc in SETPOINTS:
                    uid = f"{group_id}_{desc.key}"
                    ent_id = registry.async_get_entity_id("number", DOMAIN, uid)
                    if ent_id is not None:
                        ent = registry.async_get(ent_id)
                        if ent is not None and ent.config_entry_id == entry.entry_id:
                            registry.async_remove(ent_id)
        added = _collect_new_entities()
        if added:
            async_add_entities(added)

    entry.async_on_unload(coordinator.async_add_listener(_async_sync_topology))


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
    remove_registry_entries(hass, entry, "number", unique_ids)


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
        if not (super().available and room is not None and room.online):
            return False
        companion = getattr(self.coordinator, "companion", None)
        if companion is not None and companion.is_coordinator_room(self._group_id):
            prefix = companion.prefix_of_room(self._group_id)
            if prefix is not None and not companion.bridge_online.get(prefix, False):
                return False
        return True

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
        """Publish comfort/setback setpoint on the group or coordinator room (R3)."""
        room = self.room
        companion = getattr(self.coordinator, "companion", None)
        is_coord = companion is not None and companion.is_coordinator_room(self._group_id)
        if room is None or (room.pid not in WRITE_VERIFIED_PRODUCTS and not is_coord):
            raise HomeAssistantError("setpoint write unavailable for this room")
        encoded = encode_setpoint(
            value, self.native_min_value, self.native_max_value, SETPOINT_STEP
        )
        if is_coord and companion is not None:
            prefix = companion.prefix_of_room(self._group_id)
            if prefix is None:
                raise HomeAssistantError("setpoint write unavailable for this room")
            try:
                await companion.async_bridge_request(
                    prefix,
                    "room/set-comfort-setback",
                    {"room_id": self._group_id, self.entity_description.setpoint: encoded / 10},
                )
            except CompanionBridgeError as err:
                raise HomeAssistantError(f"setpoint write refused: {err}") from err
            return
        dps_nums = MODE_GROUP_SETPOINT_DP[self.entity_description.mode_key]
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
        dp=DP_UPPER_TEMP,
        bound="upper",
    ),
    HeadBoundDescription(
        key="lower_bound",
        translation_key="lower_bound",
        entity_category=EntityCategory.CONFIG,
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
    setpoint must follow" (contract §4.2). Reading retained here: when the new lower bound is above
    the head's pause setpoint, the pause setpoint is raised to it in the same frame. That frame was
    applied on real hardware (2026-11-19: the bound moved and the pause setpoint followed);
    whether the app itself sends DP 120 in that situation has not been observed.
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
        link: CloudMqttLink | None,
        supervised_dps: frozenset[int] = frozenset(),
    ) -> None:
        super().__init__(coordinator, device_id)
        self._link = link
        self._supervised_dps = supervised_dps

    _companion_z2m_key: str | None = None

    def _write_path(self, dev: DanfossDevice | None) -> str:
        if dev is None:
            return PATH_NONE
        companion = getattr(self.coordinator, "companion", None)
        if companion is not None:
            if self._companion_z2m_key and companion.supports_device_set(
                dev.id, self._companion_z2m_key
            ):
                return "mqtt_companion"
            return PATH_NONE
        if self._link is None or not write_allowed(dev) or not dev.node_id or not dev.mesh_id:
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
    def extra_state_attributes(self) -> dict[str, Any]:
        dev = self.device
        path = self._write_path(dev)
        attrs: dict[str, Any] = {"write_path": path}
        if path == "mqtt_companion" and dev is not None:
            # A grouped cloud-bridge head's bound is written on its room: every head takes it.
            attrs.update(companion_write_attrs(self.coordinator, dev))
        elif path == PATH_MQTT:
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
        link: CloudMqttLink | None,
        supervised_dps: frozenset[int] = frozenset(),
    ) -> None:
        super().__init__(coordinator, device_id, link, supervised_dps)
        self.entity_description = description
        self._dps = (description.dp,)
        self._companion_z2m_key = (
            "max_heat_setpoint_limit" if description.bound == "upper" else "min_heat_setpoint_limit"
        )
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
        if dev is None:
            raise HomeAssistantError("bound write unavailable for this head")
        path = self._write_path(dev)
        if path == "mqtt_companion":
            companion = getattr(self.coordinator, "companion", None)
            if companion is None:
                raise HomeAssistantError("bound write unavailable for this head")
            try:
                raw = encode_setpoint(
                    value, self._attr_native_min_value, self._attr_native_max_value, SETPOINT_STEP
                )
            except CloudError as err:
                raise HomeAssistantError(f"bound refused: {err}") from err
            kw = "max_setpoint" if self.entity_description.bound == "upper" else "min_setpoint"
            try:
                await companion.async_send_device_set(dev.id, **{kw: raw / 10})
            except (KeyError, ValueError) as err:
                raise HomeAssistantError(f"bound write failed: {err}") from err
            return
        if path != PATH_MQTT or self._link is None:
            raise HomeAssistantError("bound write unavailable for this head")
        dps = bound_write_dps(self.entity_description, dev, value)
        await async_mqtt_write(
            self.coordinator, self._link, dev, dps, supervised=self._supervised_dps
        )


# --- isolated head: comfort / setback / pause setpoints over Tuya cloud MQTT ----------------------

# Modes (cloud DP 2) in which a head follows its weekly schedule. A write that carries DP 16
# (``temp_set``, the head's effective setpoint) is proven in these only: the head goes back to its
# schedule's value by itself. In manual, pause or holiday mode nothing observed says the current
# setpoint would come back, so the write is refused (contract §4.2).
SCHEDULE_MODES = frozenset({"at_home", "leaving_home"})


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

    @property
    def sets_current_setpoint(self) -> bool:
        """The write carries DP 16, which changes the head's current setpoint at once."""
        return DP_TEMP_SET in self.companions


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


class DanfossHeadSetpoint(_HeadMqttNumber):
    """Comfort, setback or pause setpoint of an ISOLATED head, written the way the app does.

    1. The setpoint DP(s) are published over Tuya cloud MQTT and the setting DP's confirmation is
       awaited (``async_mqtt_write``).
    2. For the settings of the app's "Settings" block (comfort, setback), the whole block is then
       posted through ``settings.change``, as the app does: it keeps the cloud-side store of the
       workflow in step with the head. That HTTP call alone never reaches an isolated head (W-3);
       it is not the write.

    The value is checked against the head's own bounds before anything is sent. A write that
    carries DP 16 (comfort) is refused unless the head follows its schedule (``SCHEDULE_MODES``,
    as the cloud reports its mode): elsewhere DP 16 would change the current setpoint with nothing
    known to bring it back.
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
        if desc.sets_current_setpoint and dev.mode not in SCHEDULE_MODES:
            raise HomeAssistantError(
                f"setpoint refused: this write also sets the head's current setpoint (DP 16), "
                f"which is validated only for a head following its schedule; current mode: "
                f"{dev.mode!r}"
            )
        # Build the HTTP block BEFORE publishing: if it cannot be built, nothing is sent at all.
        if self._link is None:
            raise HomeAssistantError("setpoint write unavailable for this head")
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


@dataclass(frozen=True, kw_only=True)
class LocalTrialNumberDescription(NumberEntityDescription):
    """A head setting written through the local tunnel under supervised trial."""

    setting: str  # key of ``local_write.LOCAL_TRIAL_SETTINGS``
    attribute: str  # name given by ``tunnel.name_attributes``
    scale: float = 1.0  # raw value read * scale = value shown


LOCAL_TRIAL_NUMBERS: tuple[LocalTrialNumberDescription, ...] = (
    LocalTrialNumberDescription(
        key="setpoint_offset_setting",
        translation_key="setpoint_offset_setting",
        setting="setpoint_offset",
        attribute="setpoint_offset",
        scale=0.1,  # Zigbee2MQTT's tenths of °C, NOT confirmed on real hardware
        native_min_value=tunnel.SETPOINT_OFFSET_MIN,
        native_max_value=tunnel.SETPOINT_OFFSET_MAX,
        native_step=0.1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
    ),
    LocalTrialNumberDescription(
        key="regulation_speed_setting",
        translation_key="regulation_speed_setting",
        setting="regulation_speed",
        attribute="control_speed",
        native_min_value=tunnel.CONTROL_SPEED_MIN,
        native_max_value=tunnel.CONTROL_SPEED_MAX,
        native_step=1,
        mode=NumberMode.BOX,
    ),
    LocalTrialNumberDescription(
        key="external_room_sensor_setting",
        translation_key="external_room_sensor_setting",
        setting="external_room_sensor",
        attribute="external_room_sensor",
        scale=0.01,  # the head carries it in hundredths of °C (Zigbee2MQTT scale)
        # -80 °C (raw -8000) is Danfoss' DISABLE sentinel; the head regulates on its own sensor.
        native_min_value=tunnel.EXTERNAL_ROOM_SENSOR_MIN,
        native_max_value=tunnel.EXTERNAL_ROOM_SENSOR_MAX,
        native_step=0.1,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
    ),
)


class DanfossLocalSettingNumber(DanfossLocalTrialEntity, NumberEntity):
    """Setpoint offset (0x404B) or regulation speed (0x4020), written through the local tunnel
    under supervised trial (``local_write``). Value: the head's own, read through the tunnel."""

    entity_description: LocalTrialNumberDescription

    def __init__(
        self,
        local: DanfossLocalCoordinator,
        cloud: DanfossCoordinator,
        device_id: str,
        description: LocalTrialNumberDescription,
    ) -> None:
        super().__init__(local, cloud, device_id, description.key)
        self.entity_description = description
        self._attribute = description.attribute

    @property
    def native_value(self) -> float | None:
        raw = self._value(self._attribute)
        if isinstance(raw, bool) or not isinstance(raw, int):
            return None
        return round(raw * self.entity_description.scale, 2)

    async def async_set_native_value(self, value: float) -> None:
        head = self._head
        if head is None:
            raise HomeAssistantError("the local tunnel cannot reach this head")
        desc = self.entity_description
        # HA hands a float: the regulation speed is written as the integer it stands for (a
        # fractional value is refused by the validation, never rounded silently).
        sent: float | int = int(value) if desc.native_step == 1 and value == int(value) else value
        await self._async_run_trial(
            async_local_write_setting(self.hass, self.coordinator, head, desc.setting, sent)
        )
