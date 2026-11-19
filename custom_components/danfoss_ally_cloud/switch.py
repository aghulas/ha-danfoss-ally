"""Switches: child lock (DP 30), window detection (DP 116), preheat (local).

Child lock / window detection, for guard-rail products (WRITE_VERIFIED_PRODUCTS), unavailable while
offline. The write path depends on the head (real-hardware result W-3, 2026-11-19):

- head GROUPED into a room: the setting is published on the ROOM (``s.m.dev.group.dp.publish``,
  contract §4.2), the proven path. ⚠ It applies to EVERY head of that room (exposed in the
  ``write_scope`` / ``room_head_count`` attributes);
- ISOLATED head: ``tuya.m.custom.wkf.settings.change`` is accepted but NEVER applied for DP 30/116
  (W-3, whatever the ``gwId``), and an app capture showed the app does not use it for these DPs (it
  publishes the DP over Tuya cloud MQTT, not implemented here). So: window detection goes through
  the LOCAL TUNNEL when it is active and the head answers locally (W-4 ✅); otherwise, and always
  the child lock (not exposed by the local path), the switch is UNAVAILABLE rather than lying.

Preheat: writing DP 1 on the cloud only changes the gateway cache; the real lever is the Zigbee
attribute 0x0025, via the LOCAL TUNNEL. The preheat switch therefore exists only if the
`enable_local` option is on and the gateway reachable; otherwise it is absent (rather than lying).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import MQTT_WRITE_DPS, CloudError, DanfossDevice, mqtt_write_value, write_allowed
from .api.local import tunnel
from .api.local.manager import Head
from .api.mqtt_client import CloudMqttLink
from .const import DATA_CLOUD_MQTT, DATA_COORDINATOR, DATA_LOCAL, DATA_MQTT_LINK, DOMAIN
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator
from .entity import DanfossEntity

_LOGGER = logging.getLogger(__name__)

# Write paths of a setting switch (``write_path`` attribute).
PATH_ROOM = "room"  # group publish on the head's room: affects every head of the room
PATH_MQTT = "cloud_mqtt"  # isolated head via dedicated-session Tuya cloud MQTT (gated, this head)
PATH_LOCAL = "local"  # local Zigbee tunnel, this head only
PATH_NONE = "none"  # no proven path: the switch is unavailable

# How long to wait for the gateway's inbound protocol-4 confirmation after a cloud-MQTT write,
# before falling back to a cloud re-read (and then a clear error if still unconfirmed).
MQTT_CONFIRM_TIMEOUT = 15.0


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
        icon="mdi:lock",
        dp=30,
        value=lambda d: d.child_lock,
    ),
    DanfossSwitchDescription(
        key="window_detection",
        translation_key="window_detection",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:window-open-variant",
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

    entities: list[SwitchEntity] = [
        DanfossSwitch(coordinator, dev.id, desc, local, mqtt_link, cloud_mqtt_enabled)
        for dev in coordinator.data.values()
        if dev.is_head and write_allowed(dev)
        for desc in SWITCHES
    ]
    if local is not None:
        gws = local.manager.gateway_ids
        entities += [
            DanfossPreheat(local, coordinator, dev.id)
            for dev in coordinator.data.values()
            if dev.is_head and dev.node_id and dev.mesh_id in gws
        ]
    async_add_entities(entities)


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
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._local = local
        self._mqtt = mqtt
        self._cloud_mqtt_enabled = cloud_mqtt_enabled
        self._attr_unique_id = f"{device_id}_{description.key}"

    def _mqtt_ready(self, dev: DanfossDevice) -> bool:
        """True if an isolated head can be written through the dedicated-session cloud-MQTT link
        right now: the gate is on, a connected link exists, and it knows this head's gateway. Never
        optimistic — a link that is absent or not connected makes this path unusable. Only the DPs
        enabled on the MQTT path (DP 30 at first) use it; others fall through to tunnel/none."""
        if not (self._cloud_mqtt_enabled and self._mqtt is not None):
            return False
        if self.entity_description.dp not in MQTT_WRITE_DPS:
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
        if dev is None or not write_allowed(dev):
            return PATH_NONE
        if self.coordinator.group_of(dev.id) is not None:
            return PATH_ROOM
        # Isolated head: dedicated-session cloud MQTT (gated), else local tunnel, else none.
        if self._mqtt_ready(dev):
            return PATH_MQTT
        if self._local_head(dev) is not None:
            return PATH_LOCAL
        return PATH_NONE

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
        if path == PATH_ROOM and dev is not None:
            group_id = self.coordinator.group_of(dev.id)
            attrs["write_scope"] = "room"
            attrs["room_head_count"] = len(self.coordinator.room_members(group_id or ""))
        elif path in (PATH_LOCAL, PATH_MQTT):
            attrs["write_scope"] = "head"
        return attrs

    async def _async_write(self, state: bool) -> None:
        dev = self.device
        path = self._write_path(dev)
        if dev is None or path == PATH_NONE:
            return
        dp = str(self.entity_description.dp)
        if path == PATH_ROOM:
            group_id = self.coordinator.group_of(dev.id) or ""
            try:
                await self.coordinator.client.async_group_publish(group_id, {dp: state})
            except CloudError as err:
                raise HomeAssistantError(f"room setting write refused: {err}") from err
            self.coordinator.note_commanded(self.coordinator.room_members(group_id) or [dev.id])
        elif path == PATH_MQTT:
            # Isolated head, dedicated-session cloud MQTT. Gate + a live link required; the option
            # is OFF by default and a first real publish needs an explicit supervised go-ahead.
            if self._mqtt is None or not dev.node_id or not dev.mesh_id:
                return
            # Validate the value before sending (DP-30-only / boolean) — a clear error, never a
            # blind send. Then publish and wait for a confirmation (no optimistic success).
            value = mqtt_write_value(self.entity_description.dp, state)
            try:
                await self._mqtt.publish_dp(dev.mesh_id, dev.node_id, {dp: value})
                confirmed = await self._mqtt.await_confirmation(
                    dev.node_id, self.entity_description.dp, value, timeout_s=MQTT_CONFIRM_TIMEOUT
                )
            except Exception as err:  # noqa: BLE001 - surface any send failure, never a blind write
                raise HomeAssistantError(f"cloud-MQTT setting write failed: {err}") from err
            self.coordinator.note_commanded([dev.id])
            if confirmed:
                _LOGGER.debug("cloud-MQTT DP %s confirmed by inbound echo frame", dp)
            else:
                # Fall back to a cloud re-read; if still unconfirmed, say so (do not claim success).
                await self.coordinator.async_request_refresh()
                dev2 = self.device
                if dev2 is None or self.entity_description.value(dev2) != value:
                    raise HomeAssistantError(
                        "cloud-MQTT write not confirmed (no inbound frame, cloud still differs)"
                    )
                _LOGGER.debug("cloud-MQTT DP %s confirmed by cloud re-read (no echo frame)", dp)
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
    """

    _attr_has_entity_name = True
    _attr_translation_key = "preheat"
    _attr_icon = "mdi:fire"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, local: DanfossLocalCoordinator, cloud: DanfossCoordinator, device_id: str
    ) -> None:
        super().__init__(local)
        self._cloud = cloud
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_preheat"

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
        group_id = self._cloud.group_of(self._device_id)
        if group_id is not None:
            info["via_device"] = (DOMAIN, f"group_{group_id}")  # type: ignore[typeddict-unknown-key]  # deprecated in HA 2026 (removed 2027.8): move to via_device_id
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
