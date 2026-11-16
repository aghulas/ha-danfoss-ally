"""Base commune des entités : liaison au coordinateur et info appareil."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DanfossDevice
from .const import DOMAIN
from .coordinator import DanfossCoordinator


class DanfossEntity(CoordinatorEntity[DanfossCoordinator]):
    """Entité rattachée à un appareil Danfoss, pilotée par le coordinateur."""

    _attr_has_entity_name = True
    # Les entités de mesure deviennent indisponibles quand la tête est hors ligne
    # (valeurs figées = mensongères, cf. docs/architecture.md). La connectivité, non.
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
        return dev.en_ligne or not self._require_online

    @property
    def device_info(self) -> DeviceInfo:
        dev = self.device
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=(dev.nom if dev and dev.nom else self._device_id),
            manufacturer="Danfoss",
            model=(dev.product_id if dev else None),
        )


class DanfossRoomEntity(CoordinatorEntity[DanfossCoordinator]):
    """Entité rattachée à un appareil « pièce » (groupe-programme), piloté par le coordinateur."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DanfossCoordinator, group_id: str) -> None:
        super().__init__(coordinator)
        self._group_id = group_id

    @property
    def room(self) -> dict | None:
        return self.coordinator.rooms_by_id.get(self._group_id)

    @property
    def available(self) -> bool:
        return super().available and self.room is not None

    @property
    def device_info(self) -> DeviceInfo:
        room = self.room
        return DeviceInfo(
            identifiers={(DOMAIN, f"room_{self._group_id}")},
            name=(room["name"] if room and room.get("name") else self._group_id),
            manufacturer="Danfoss",
            model="Pièce",
        )
