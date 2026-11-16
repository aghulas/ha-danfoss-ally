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
        info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=(dev.nom if dev and dev.nom else self._device_id),
            manufacturer="Danfoss",
            model=(dev.product_id if dev else None),
        )
        # Tête groupée : la rattacher à l'appareil « pièce » (sous-appareil du thermostat de pièce).
        group_id = self.coordinator.group_of(self._device_id)
        if group_id is not None:
            info["via_device"] = (DOMAIN, f"group_{group_id}")
        return info
