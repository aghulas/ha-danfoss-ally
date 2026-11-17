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
        # Grouped head: attach it to the "room" device (sub-device of the room thermostat).
        group_id = self.coordinator.group_of(self._device_id)
        if group_id is not None:
            info["via_device"] = (DOMAIN, f"group_{group_id}")
        return info
