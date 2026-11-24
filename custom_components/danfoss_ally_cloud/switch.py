"""Switches: child lock (DP 30), window detection (DP 116), preheat (local).

Child lock / window detection, for guard-rail products (WRITE_VERIFIED_PRODUCTS), unavailable while
offline. Each write goes to the channel proven for it (docs/architecture.md), never to one that
merely accepts the call:

- head GROUPED into a room: the setting is published on the ROOM (``s.m.dev.group.dp.publish``,
  contract §4.2), the proven path. ⚠ It applies to EVERY head of that room (exposed in the
  ``write_scope`` / ``room_head_count`` attributes);
- ISOLATED head: ``tuya.m.custom.wkf.settings.change`` is accepted but NEVER applied for DP 30/116
  (W-3, whatever the ``gwId``); the app publishes the DP over Tuya cloud MQTT instead. Routing, in
  this order (``DanfossSwitch._write_path``):

  1. on the ONE head designated for it (``cloud_mqtt_supervised_head``), a DP under SUPERVISED
     TRIAL on cloud MQTT (``cloud_mqtt_supervised_dps``) goes through cloud
     MQTT, so the trial exercises the channel it is meant to prove, the local tunnel staying free
     to read the result back;
  2. the LOCAL TUNNEL when the setting has a proven tunnel write and the head answers locally
     (window detection, W-4 ✅): a write that reaches the head directly, with no cloud involved;
  3. cloud MQTT for a DP PROVEN on it (child lock; window detection when the tunnel of step 2 is
     not available), when the option is on and the link connected;
  4. otherwise the switch is UNAVAILABLE rather than lying.

Preheat: writing DP 1 over cloud HTTP only changes the gateway cache; the real lever is the Zigbee
attribute 0x0025, via the LOCAL TUNNEL. The preheat switch therefore exists only if the
`enable_local` option is on and the gateway reachable; otherwise it is absent (rather than lying).
Its state always comes from the tunnel. DP 1 over cloud MQTT is a CANDIDATE, closed: whether that
publish reaches the head at all is not established (docs/preheat.md). Armed for
a supervised trial on the designated isolated head, the write goes out over cloud MQTT and is
confirmed by the tunnel alone; everywhere else, and always by default, the tunnel writes.

Viewing direction (DP 101, Zigbee2MQTT ``viewing_direction``): a CANDIDATE on cloud MQTT, closed.
The switch exists only while its supervised trial is armed for the designated isolated head
(docs/first-write-procedure.md). Its state is the cloud's DP 101 (unavailable when the cloud
does not carry it); a write is confirmed by the per-device cloud route, never by the echo.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import (
    MQTT_CANDIDATE_DPS,
    CloudError,
    DanfossDevice,
    mqtt_dp_open,
    write_allowed,
)
from .api.local import tunnel
from .api.local.manager import Head
from .api.mqtt_client import CloudMqttLink
from .const import (
    DATA_CLOUD_MQTT,
    DATA_COORDINATOR,
    DATA_LOCAL,
    DATA_MQTT_LINK,
    DOMAIN,
)
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator
from .entity import (
    DanfossEntity,
    DanfossLocalTrialEntity,
    DanfossTrialEntity,
    remove_registry_entries,
)
from .local_write import async_local_write_setting, local_trial_split
from .mqtt_write import (  # noqa: F401 - timeout re-exported
    DP_PREHEAT,
    DP_VIEWING_DIRECTION,
    MQTT_CONFIRM_TIMEOUT,
    async_mqtt_write,
    async_mqtt_write_preheat,
    async_mqtt_write_viewing_direction,
    supervised_for,
    trial_dp_armed,
)

_LOGGER = logging.getLogger(__name__)

# Write paths of a setting switch (``write_path`` attribute).
PATH_COMPANION = "mqtt_companion"  # Companion MQTT bridge (zigbee2mqtt / danfoss2mqtt)
PATH_ROOM = "room"  # group publish on the head's room: affects every head of the room
PATH_MQTT = "cloud_mqtt"  # isolated head via dedicated-session Tuya cloud MQTT (gated, this head)
PATH_LOCAL = "local"  # local Zigbee tunnel, this head only
PATH_NONE = "none"  # no proven path: the switch is unavailable

_COMPANION_SWITCH_KWARGS: dict[str, str] = {
    "child_lock": "child_lock",
    "window_detection": "window_detection",
}

_COMPANION_SWITCH_Z2M_KEYS: dict[str, str] = {
    "child_lock": "keypad_lockout",
    "window_detection": "window_open_feature",
}


@dataclass(frozen=True, kw_only=True)
class DanfossSwitchDescription(SwitchEntityDescription):
    """Switch: target DP, read of the decoded state, local-tunnel write if any."""

    dp: int
    value: Callable[[DanfossDevice], bool | None]
    # Name of the setting in ``tunnel.SETTINGS_DP`` when an isolated head can be written through the
    # local tunnel (proven on real hardware), else None (no proven isolated-head path).
    local_setting: str | None = None


SWITCHES: tuple[DanfossSwitchDescription, ...] = (
    DanfossSwitchDescription(
        key="child_lock",
        translation_key="child_lock",
        entity_category=EntityCategory.CONFIG,
        dp=30,
        value=lambda d: d.child_lock,
    ),
    DanfossSwitchDescription(
        key="window_detection",
        translation_key="window_detection",
        entity_category=EntityCategory.CONFIG,
        dp=116,
        value=lambda d: d.window_detection,
        local_setting="window_detection",  # W-4 ✅ through the tunnel
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanfossCoordinator = data[DATA_COORDINATOR]
    local: DanfossLocalCoordinator | None = data.get(DATA_LOCAL)
    mqtt_link: CloudMqttLink | None = data.get(DATA_MQTT_LINK)
    cloud_mqtt_enabled: bool = bool(data.get(DATA_CLOUD_MQTT, False))

    companion = getattr(coordinator, "companion", None)
    known_switch_uids: set[str] = set()

    def _collect_switches() -> list[SwitchEntity]:
        new_entities: list[SwitchEntity] = []
        for dev in coordinator.data.values():
            if not (dev.is_head and (companion is not None or write_allowed(dev))):
                continue
            for desc in SWITCHES:
                uid = f"{dev.id}_{desc.key}"
                if uid in known_switch_uids:
                    continue
                known_switch_uids.add(uid)
                new_entities.append(
                    DanfossSwitch(
                        coordinator,
                        dev.id,
                        desc,
                        local,
                        mqtt_link,
                        cloud_mqtt_enabled,
                        supervised_for(data, dev.id),
                    )
                )
        return new_entities

    entities: list[SwitchEntity] = _collect_switches()
    if companion is not None:

        @callback
        def _sync_companion_switches() -> None:
            added = _collect_switches()
            if added:
                async_add_entities(added)

        entry.async_on_unload(coordinator.async_add_listener(_sync_companion_switches))
    # Preheat exists only through the LOCAL TUNNEL (attribute 0x0025). In MQTT-companion mode the
    # integration holds no local tunnel (``local`` is None), so NO preheat switch is created there,
    # for any head — zigbee2mqtt or danfoss2mqtt (the latter also carry no ``mesh_id``). This is by
    # design, not a missing feature: the cloud DP 1 route is a closed candidate and a supervised
    # DP 1 trial can only be armed from a direct-cloud entry (docs/preheat.md, docs/companion-
    # contract.md §2.4). Diagnostics report the reason so the absence is explicit.
    if local is not None:
        gws = local.manager.gateway_ids
        entities += [
            DanfossPreheat(
                local,
                coordinator,
                dev.id,
                mqtt_link,
                cloud_mqtt_enabled,
                supervised_for(data, dev.id),  # the trial is confined to its designated head
            )
            for dev in coordinator.data.values()
            if dev.is_head and dev.node_id and dev.mesh_id in gws
        ]
    # Viewing direction: only while its supervised trial is armed for this head. Otherwise its
    # registry entry is removed (trial disarmed or moved); kept when only the link is missing.
    closed: list[str] = []
    for dev in coordinator.data.values():
        if not dev.is_head:
            continue
        uid = f"{dev.id}_viewing_direction"
        if not trial_dp_armed(data, coordinator, dev, DP_VIEWING_DIRECTION):
            closed.append(uid)
        elif mqtt_link is not None:
            entities.append(
                DanfossViewingDirection(
                    coordinator, dev.id, mqtt_link, supervised_for(data, dev.id)
                )
            )
    # Boolean head settings written through the local tunnel, each only while its own trial is
    # armed for this head (radiator covered 0x4016, external window open 0x4003, load balancing
    # 0x4032). Not proven on real hardware; closed by default.
    closed_local: list[str] = []
    for tdesc in LOCAL_TRIAL_SWITCHES:
        armed, closed_setting = local_trial_split(
            data, coordinator.data.values(), local, tdesc.setting, tdesc.key
        )
        closed_local += closed_setting
        if local is not None:
            entities += [
                DanfossLocalSettingSwitch(local, coordinator, dev_id, tdesc) for dev_id in armed
            ]
    remove_registry_entries(hass, entry, "switch", [*closed, *closed_local])
    async_add_entities(entities)


@dataclass(frozen=True, kw_only=True)
class LocalTrialSwitchDescription(SwitchEntityDescription):
    """A boolean head setting written through the local tunnel under supervised trial."""

    setting: str  # key of ``local_write.LOCAL_TRIAL_SETTINGS``
    attribute: str  # name given by ``tunnel.name_attributes``


LOCAL_TRIAL_SWITCHES: tuple[LocalTrialSwitchDescription, ...] = (
    LocalTrialSwitchDescription(
        key="radiator_covered_setting",
        translation_key="radiator_covered_setting",
        setting="radiator_covered",
        attribute="radiator_covered",
    ),
    LocalTrialSwitchDescription(
        key="window_open_external_setting",
        translation_key="window_open_external_setting",
        setting="window_open_external",
        attribute="window_open_external",
    ),
    LocalTrialSwitchDescription(
        key="load_balancing_setting",
        translation_key="load_balancing_setting",
        setting="load_balancing",
        attribute="load_balancing",
    ),
    # 0x404E ``adaptation_run_settings``: enable/disable the automatic (nightly) adaptation run. A
    # boolean (Zigbee2MQTT ``m.binary``), hence a switch rather than a select. NOT the separate
    # command attribute 0x404C ``adaptation_run_control`` (enum: launch/cancel a run), out of scope.
    LocalTrialSwitchDescription(
        key="adaptation_run_settings_setting",
        translation_key="adaptation_run_settings_setting",
        setting="adaptation_run_settings",
        attribute="adaptation_setting",
    ),
)
# Kept for backwards reference (the radiator-covered unique id is unchanged).
RADIATOR_COVERED_UID = "radiator_covered_setting"


class DanfossLocalSettingSwitch(DanfossLocalTrialEntity, SwitchEntity):
    """A boolean Danfoss setting (radiator covered 0x4016, external window open 0x4003, load
    balancing 0x4032, automatic adaptation run 0x404E), written through the local tunnel under
    supervised trial (``local_write``). State: the head's own value read through the tunnel."""

    entity_description: LocalTrialSwitchDescription

    def __init__(
        self,
        local: DanfossLocalCoordinator,
        cloud: DanfossCoordinator,
        device_id: str,
        description: LocalTrialSwitchDescription,
    ) -> None:
        super().__init__(local, cloud, device_id, description.key)
        self.entity_description = description
        self._attribute = description.attribute

    @property
    def is_on(self) -> bool | None:
        value = self._value(self._attribute)
        return value if isinstance(value, bool) else None

    async def _async_write(self, state: bool) -> None:
        head = self._head
        if head is None:
            raise HomeAssistantError(
                f"{self.entity_description.setting}: the local tunnel cannot reach this head"
            )
        await self._async_run_trial(
            async_local_write_setting(
                self.hass, self.coordinator, head, self.entity_description.setting, state
            )
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_write(False)


class DanfossSwitch(DanfossEntity, SwitchEntity):
    """Setting switch of a head (guarded write, routed by room / local tunnel)."""

    entity_description: DanfossSwitchDescription

    def __init__(
        self,
        coordinator: DanfossCoordinator,
        device_id: str,
        description: DanfossSwitchDescription,
        local: DanfossLocalCoordinator | None = None,
        mqtt: CloudMqttLink | None = None,
        cloud_mqtt_enabled: bool = False,
        supervised_dps: frozenset[int] = frozenset(),
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._local = local
        self._mqtt = mqtt
        self._cloud_mqtt_enabled = cloud_mqtt_enabled
        self._supervised_dps = supervised_dps
        self._attr_unique_id = f"{device_id}_{description.key}"
        # What the last written state showed (availability, write path): the local coordinator's
        # updates only rewrite the state when it changes (see ``_handle_local_update``).
        self._shown: tuple[bool, str] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # An isolated head's write path depends on the LOCAL survey (``_local_head``): listen to
        # the local coordinator too, so the switch follows a head as soon as it is read locally
        # instead of waiting for the next cloud poll. Removed with the entity (no leak on unload).
        if self.entity_description.local_setting is not None and self._local is not None:
            self.async_on_remove(self._local.async_add_listener(self._handle_local_update))
        self._shown = self._shown_key()  # the platform writes the first state right after this

    def _shown_key(self) -> tuple[bool, str]:
        return (self.available, self._write_path(self.device))

    @callback
    def _handle_coordinator_update(self) -> None:
        self._shown = self._shown_key()
        super()._handle_coordinator_update()

    @callback
    def _handle_local_update(self) -> None:
        """A local survey published a head (or finished): rewrite the state only if this switch's
        availability or write path changed. A survey publishes every head of the site one by one;
        rewriting every window switch on each of them would multiply identical state writes."""
        shown = self._shown_key()
        if shown != self._shown:
            self._shown = shown
            self.async_write_ha_state()

    def _mqtt_ready(self, dev: DanfossDevice) -> bool:
        """True if an isolated head can be written through the dedicated-session cloud-MQTT link
        right now: the gate is on, a connected link exists, and it knows this head's gateway. Never
        optimistic — a link that is absent or not connected makes this path unusable. Only a DP
        open on the MQTT path uses it (proven, or a candidate listed for a supervised trial);
        others fall through to tunnel/none."""
        if not (self._cloud_mqtt_enabled and self._mqtt is not None):
            return False
        if not mqtt_dp_open(self.entity_description.dp, self._supervised_dps):
            return False
        if not dev.node_id or not dev.mesh_id:
            return False
        return self._mqtt.can_publish(dev.mesh_id)

    def _local_head(self, dev: DanfossDevice) -> Head | None:
        """The tunnel address of an isolated head, if the local path is usable right now.

        Usable = the setting has a proven tunnel write, the local option is on, the head's gateway
        is known to the tunnel, and the last local survey got an answer from this head (a gateway or
        head that does not answer locally makes the switch unavailable, never a blind write).
        """
        local = self._local
        if self.entity_description.local_setting is None or local is None:
            return None
        if not dev.node_id or not dev.mesh_id or dev.mesh_id not in local.manager.gateway_ids:
            return None
        if not local.last_update_success or (local.data or {}).get(dev.id) is None:
            return None
        return Head(dev.id, dev.node_id, dev.mesh_id)

    def _write_path(self, dev: DanfossDevice | None) -> str:
        if dev is None:
            return PATH_NONE
        companion = getattr(self.coordinator, "companion", None)
        if companion is not None:
            z2m_key = _COMPANION_SWITCH_Z2M_KEYS.get(self.entity_description.key)
            if z2m_key is not None and companion.supports_device_set(dev.id, z2m_key):
                return PATH_COMPANION
            return PATH_NONE
        if not write_allowed(dev):
            return PATH_NONE
        if self.coordinator.group_of(dev.id) is not None:
            return PATH_ROOM
        # Isolated head (order explained in the module docstring).
        mqtt_ready = self._mqtt_ready(dev)
        if mqtt_ready and self._on_trial:
            return PATH_MQTT  # supervised trial of this DP on cloud MQTT
        if self._local_head(dev) is not None:
            return PATH_LOCAL  # proven tunnel write, the head answers locally
        if mqtt_ready:
            return PATH_MQTT  # DP proven on cloud MQTT
        return PATH_NONE

    @property
    def _on_trial(self) -> bool:
        """This switch's DP is a cloud-MQTT candidate opened for a supervised trial."""
        dp = self.entity_description.dp
        return dp in MQTT_CANDIDATE_DPS and dp in self._supervised_dps

    @property
    def available(self) -> bool:
        return super().available and self._write_path(self.device) != PATH_NONE

    @property
    def is_on(self) -> bool | None:
        dev = self.device
        return self.entity_description.value(dev) if dev else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        dev = self.device
        path = self._write_path(dev)
        attrs: dict[str, Any] = {"write_path": path}
        if path == PATH_COMPANION and dev is not None:
            attrs["write_scope"] = "head"
            companion = getattr(self.coordinator, "companion", None)
            route = companion.device_route.get(dev.id) if companion is not None else None
            if route is not None:
                attrs["mqtt_bridge"] = route[0]
        elif path == PATH_ROOM and dev is not None:
            group_id = self.coordinator.group_of(dev.id)
            attrs["write_scope"] = "room"
            attrs["room_head_count"] = len(self.coordinator.room_members(group_id or ""))
        elif path in (PATH_LOCAL, PATH_MQTT):
            attrs["write_scope"] = "head"
            if path == PATH_MQTT and self._on_trial:
                # Not proven on this channel yet: the write is part of a supervised trial.
                attrs["write_trial"] = True
        return attrs

    async def _async_write(self, state: bool) -> None:
        dev = self.device
        path = self._write_path(dev)
        if dev is None or path == PATH_NONE:
            return
        dp = str(self.entity_description.dp)
        if path == PATH_COMPANION:
            companion = getattr(self.coordinator, "companion", None)
            kw = _COMPANION_SWITCH_KWARGS.get(self.entity_description.key)
            if companion is None or kw is None:
                return
            try:
                await companion.async_send_device_set(dev.id, **{kw: state})
            except (KeyError, ValueError) as err:
                raise HomeAssistantError(f"companion switch write failed: {err}") from err
            return
        if path == PATH_ROOM:
            group_id = self.coordinator.group_of(dev.id) or ""
            try:
                await self.coordinator.client.async_group_publish(group_id, {dp: state})
            except CloudError as err:
                raise HomeAssistantError(f"room setting write refused: {err}") from err
            self.coordinator.note_commanded(self.coordinator.room_members(group_id) or [dev.id])
        elif path == PATH_MQTT:
            # Isolated head, dedicated-session cloud MQTT. Gate + a live link required; validated,
            # published and confirmed by ``async_mqtt_write`` (a clear error, never optimistic).
            if self._mqtt is None:
                return
            await async_mqtt_write(
                self.coordinator,
                self._mqtt,
                dev,
                {self.entity_description.dp: state},
                supervised=self._supervised_dps,
            )
            return
        else:
            head = self._local_head(dev)
            if head is None or self._local is None:
                return
            try:
                await self.hass.async_add_executor_job(
                    self._local.manager.write_window_detection, head, state
                )
            except (tunnel.LocalUnavailable, tunnel.LocalError) as err:
                raise HomeAssistantError(f"local setting write failed: {err}") from err
            self.coordinator.note_commanded([dev.id])
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_write(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_write(False)


class DanfossPreheat(CoordinatorEntity[DanfossLocalCoordinator], SwitchEntity):
    """Real preheat (Zigbee attribute 0x0025) via the local tunnel.

    State and write go through the tunnel; unavailable if the head does not answer locally (rather
    than lying). Writing 0x0025 is validated on real hardware (2026-11-19). After a write the head
    itself is read back (not the whole site, which took ~13 min), never an optimistic state.

    Supervised trial of DP 1 over cloud MQTT (candidate, closed by default): on the one designated
    isolated head, with DP 1 listed and the cloud-MQTT option on, the write is published over cloud
    MQTT instead, followed by the settings block over HTTP as the app does, and confirmed by the
    tunnel read alone (``async_mqtt_write_preheat``). While the
    trial is armed the tunnel never writes this head's preheat, so a result cannot be attributed
    to the wrong channel: with the link down the write fails. The state source does not change.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "preheat"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        local: DanfossLocalCoordinator,
        cloud: DanfossCoordinator,
        device_id: str,
        mqtt: CloudMqttLink | None = None,
        cloud_mqtt_enabled: bool = False,
        supervised_dps: frozenset[int] = frozenset(),
    ) -> None:
        super().__init__(local)
        self._cloud = cloud
        self._device_id = device_id
        self._mqtt = mqtt
        self._cloud_mqtt_enabled = cloud_mqtt_enabled
        self._supervised_dps = supervised_dps
        self._attr_unique_id = f"{device_id}_preheat"

    @property
    def _on_trial(self) -> bool:
        """DP 1 is armed for a supervised cloud-MQTT trial on this head: the option is on, the DP
        is listed for this head (the designated trial head), and the head is an isolated one on a
        verified model (the app publishes DP 1 over MQTT for an isolated head only)."""
        dev = self._dev
        return (
            self._cloud_mqtt_enabled
            and dev is not None
            and write_allowed(dev)
            and self._cloud.group_of(dev.id) is None
            and mqtt_dp_open(DP_PREHEAT, self._supervised_dps)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self._on_trial:
            return {"write_path": PATH_MQTT, "write_scope": "head", "write_trial": True}
        return {"write_path": PATH_LOCAL, "write_scope": "head"}

    @property
    def _dev(self) -> DanfossDevice | None:
        return self._cloud.data.get(self._device_id)

    @property
    def device_info(self) -> DeviceInfo:
        dev = self._dev
        info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=(dev.name if dev and dev.name else self._device_id),
            manufacturer="Danfoss",
            model=(dev.product_id if dev else None),
        )
        # The head -> room link (sub-device of the room thermostat) is set on the device
        # registry by device_links.async_link_heads_to_rooms (via_device_id).
        return info

    @property
    def available(self) -> bool:
        dev = self._dev
        if not super().available or dev is None or not dev.online:
            return False
        # Unavailable until the tunnel has a reliable value for this head.
        return self.coordinator.data.get(self._device_id) is not None

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.get(self._device_id)

    async def _async_write(self, active: bool) -> None:
        dev = self._dev
        if dev is None or not dev.node_id or not dev.mesh_id:
            return
        if self._on_trial:
            # Supervised trial: cloud MQTT only, confirmed by the tunnel only. No tunnel write
            # here, whatever happens, or the trial would credit the wrong channel.
            if self._mqtt is None or not self._mqtt.can_publish(dev.mesh_id):
                raise HomeAssistantError(
                    "preheat is armed for a supervised cloud-MQTT trial on this head, and the "
                    "cloud-MQTT link cannot publish: nothing was written"
                )
            await async_mqtt_write_preheat(
                self.coordinator,
                self._cloud,
                self._mqtt,
                dev,
                active,
                supervised=self._supervised_dps,
            )
            return
        head = Head(dev.id, dev.node_id, dev.mesh_id)
        try:
            accepted = await self.hass.async_add_executor_job(
                self.coordinator.manager.write_preheat, head, active
            )
        except (tunnel.LocalUnavailable, tunnel.LocalError) as err:
            raise HomeAssistantError(f"local preheat write failed: {err}") from err
        # Read this head back (whatever the write status): the state shown is what the head says.
        await self.coordinator.async_refresh_head(head)
        if not accepted:
            raise HomeAssistantError("local preheat write rejected by the head")

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_write(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_write(False)


class DanfossViewingDirection(DanfossTrialEntity, SwitchEntity):
    """Viewing direction of an ISOLATED head (DP 101), under supervised trial on cloud MQTT.

    State: the cloud's DP 101 (the gateway's view), unavailable when the cloud does not carry it.
    Write: ``async_mqtt_write_viewing_direction``, confirmed by the per-device cloud route."""

    _attr_translation_key = "viewing_direction"
    _dp = DP_VIEWING_DIRECTION

    def __init__(
        self,
        coordinator: DanfossCoordinator,
        device_id: str,
        link: CloudMqttLink,
        supervised_dps: frozenset[int],
    ) -> None:
        super().__init__(coordinator, device_id, link, supervised_dps)
        self._attr_unique_id = f"{device_id}_viewing_direction"

    @property
    def available(self) -> bool:
        dev = self.device
        return super().available and dev is not None and dev.viewing_direction is not None

    @property
    def is_on(self) -> bool | None:
        dev = self.device
        return dev.viewing_direction if dev else None

    async def _async_write(self, on: bool) -> None:
        dev = self.device
        if dev is None or self._write_path(dev) != PATH_MQTT:
            raise HomeAssistantError("viewing direction write unavailable for this head")
        await self._async_run_trial(
            async_mqtt_write_viewing_direction(
                self.coordinator, self._link, dev, on, supervised=self._supervised_dps
            )
        )

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_write(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_write(False)
