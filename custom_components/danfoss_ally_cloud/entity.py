"""Common entity base: coordinator binding and device info."""

from __future__ import annotations

from typing import Any

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DanfossDevice
from .const import DOMAIN
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator


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


class DanfossLocalEntity(CoordinatorEntity[DanfossLocalCoordinator]):
    """Read-only entity of a head whose value the head gave through the local tunnel.

    ``_daily`` False: the value comes from the frame of each preheat survey
    (``DanfossLocalCoordinator.attributes``); unavailable until the last survey has an answer from
    the head. ``_daily`` True: it comes from the settings pass (``.settings``, at most once a
    day); the last value read is kept, dated by the ``read_at`` attribute. Either way unavailable
    while the head is offline, and never a value the head did not give.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _daily = False
    _attribute: str

    def __init__(
        self, local: DanfossLocalCoordinator, cloud: DanfossCoordinator, device_id: str
    ) -> None:
        super().__init__(local)
        self._cloud = cloud
        self._device_id = device_id

    @property
    def _source(self) -> dict[str, Any] | None:
        store = self.coordinator.settings if self._daily else self.coordinator.attributes
        return store.get(self._device_id)

    @property
    def _raw(self) -> Any:
        source = self._source
        return None if source is None else source.get(self._attribute)

    @property
    def device_info(self) -> DeviceInfo:
        dev = self._cloud.data.get(self._device_id)
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=(dev.name if dev and dev.name else self._device_id),
            manufacturer="Danfoss",
            model=(dev.product_id if dev else None),
        )

    @property
    def available(self) -> bool:
        dev = self._cloud.data.get(self._device_id)
        if not super().available or dev is None or not dev.online or self._raw is None:
            return False
        # Per-survey values follow the preheat switch: the last survey must have an answer.
        return self._daily or self.coordinator.data.get(self._device_id) is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"raw": self._raw}
        source = self._source
        if self._daily and source is not None:
            attrs["read_at"] = source.get("read_at")
        return attrs


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
