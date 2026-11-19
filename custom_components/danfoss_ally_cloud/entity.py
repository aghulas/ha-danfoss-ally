"""Common entity base: coordinator binding and device info."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DanfossDevice
from .const import DOMAIN
from .coordinator import DanfossCoordinator


class DanfossEntity(CoordinatorEntity[DanfossCoordinator]):
    """Entity attached to a Danfoss device, driven by the coordinator."""

    _attr_has_entity_name = True
    # Measurement entities become unavailable when the head is offline (frozen values would be
    # misleading, cf. docs/architecture.md). Connectivity does not.
    _require_online = True

    def __init__(self, coordinator: DanfossCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id

    @property
    def device(self) -> DanfossDevice | None:
        return self.coordinator.data.get(self._device_id)

    @property
    def available(self) -> bool:
        dev = self.device
        if not super().available or dev is None:
            return False
        return dev.online or not self._require_online

    @property
    def device_info(self) -> DeviceInfo:
        dev = self.device
        info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=(dev.name if dev and dev.name else self._device_id),
            manufacturer="Danfoss",
            model=(dev.product_id if dev else None),
        )
        # The head -> room link (sub-device of the room thermostat) is set on the device
        # registry by device_links.async_link_heads_to_rooms (via_device_id).
        return info


class DanfossHomeEntity(CoordinatorEntity[DanfossCoordinator]):
    """Entity attached to a HOME (account "home"), not to a device.

    Home-level reads (holiday, contract §4.5) have no device of their own: they hang off a dedicated
    "home" device so they group cleanly in the UI. Always available (connectivity is per head).
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: DanfossCoordinator, gid: str, name: str | None) -> None:
        super().__init__(coordinator)
        self._gid = gid
        self._home_name = name

    @property
    def holiday(self) -> dict | None:
        return self.coordinator.holidays.get(self._gid)

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"home_{self._gid}")},
            name=self._home_name or f"Home {self._gid}",
            manufacturer="Danfoss",
        )
