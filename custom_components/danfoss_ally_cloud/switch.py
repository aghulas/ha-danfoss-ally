"""Switches: child lock (DP 30), window detection (DP 116), preheat (local).

Child lock / window: path-1a write via tuya.m.custom.wkf.settings.change, for guard-rail products
(WRITE_VERIFIED_PRODUCTS), unavailable while offline. Preheat: writing DP 1 on the cloud only
changes the gateway cache; the real lever is the Zigbee attribute 0x0025, via the LOCAL TUNNEL. The
preheat switch therefore exists only if the `enable_local` option is on and the gateway reachable;
otherwise it is absent (rather than lying).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DanfossDevice, write_allowed
from .api.local.manager import Head
from .const import DATA_COORDINATOR, DATA_LOCAL, DOMAIN
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator
from .entity import DanfossEntity


@dataclass(frozen=True, kw_only=True)
class DanfossSwitchDescription(SwitchEntityDescription):
    """Switch: target DP and read of the decoded state."""

    dp: int
    value: Callable[[DanfossDevice], bool | None]


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
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanfossCoordinator = data[DATA_COORDINATOR]
    local: DanfossLocalCoordinator | None = data.get(DATA_LOCAL)

    entities: list[SwitchEntity] = [
        DanfossSwitch(coordinator, dev.id, desc)
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
    """Setting switch of a head (guarded write)."""

    entity_description: DanfossSwitchDescription

    def __init__(
        self, coordinator: DanfossCoordinator, device_id: str, description: DanfossSwitchDescription
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        dev = self.device
        return self.entity_description.value(dev) if dev else None

    async def _async_write(self, state: bool) -> None:
        dev = self.device
        if dev is None or not write_allowed(dev):
            return
        await self.coordinator.client.async_write_setting(
            dev.id,
            dev.product_id or "",
            {str(self.entity_description.dp): state},
            gw_id=dev.mesh_id,
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_write(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_write(False)


class DanfossPreheat(CoordinatorEntity[DanfossLocalCoordinator], SwitchEntity):
    """Real preheat (Zigbee attribute 0x0025) via the local tunnel.

    State and write go through the tunnel; unavailable if the head does not answer locally (rather
    than lying). ⚠ Writing 0x0025 is not confirmed on real hardware: to validate on the install.
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
            info["via_device"] = (DOMAIN, f"group_{group_id}")
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
        await self.hass.async_add_executor_job(self.coordinator.manager.write_preheat, head, active)
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_write(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_write(False)
