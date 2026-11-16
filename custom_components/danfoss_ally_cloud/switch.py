"""Interrupteurs : verrouillage enfant (DP 30), détection de fenêtre (DP 116).

Écriture voie 1a par tuya.m.custom.wkf.settings.change, uniquement pour les produits du garde-fou
(WRITE_VERIFIED_PRODUCTS). Indisponible si la tête est hors ligne (plutôt que mentir).

Le pré-chauffage n'est PAS exposé ici : écrire le DP 1 côté cloud ne change que le cache de la
passerelle ; le vrai levier est l'attribut Zigbee 0x0025, réservé au tunnel local (v0.3).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DanfossDevice, ecriture_autorisee
from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import DanfossCoordinator
from .entity import DanfossEntity


@dataclass(frozen=True, kw_only=True)
class DanfossSwitchDescription(SwitchEntityDescription):
    """Interrupteur : DP cible et lecture de l'état décodé."""

    dp: int
    value: Callable[[DanfossDevice], bool | None]


SWITCHES: tuple[DanfossSwitchDescription, ...] = (
    DanfossSwitchDescription(
        key="verrou_enfant",
        translation_key="verrou_enfant",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:lock",
        dp=30,
        value=lambda d: d.verrouillage,
    ),
    DanfossSwitchDescription(
        key="detection_fenetre",
        translation_key="detection_fenetre",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:window-open-variant",
        dp=116,
        value=lambda d: d.detection_fenetre,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DanfossCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        DanfossSwitch(coordinator, dev.id, desc)
        for dev in coordinator.data.values()
        if dev.est_tete and ecriture_autorisee(dev)
        for desc in SWITCHES
    )


class DanfossSwitch(DanfossEntity, SwitchEntity):
    """Interrupteur de réglage d'une tête (écriture gardée)."""

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

    async def _async_ecrire(self, etat: bool) -> None:
        dev = self.device
        if dev is None or not ecriture_autorisee(dev):
            return
        await self.coordinator.client.async_write_setting(
            dev.id, dev.product_id, {str(self.entity_description.dp): etat}
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_ecrire(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_ecrire(False)
