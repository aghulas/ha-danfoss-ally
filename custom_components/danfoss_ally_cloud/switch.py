"""Interrupteurs : verrou enfant (DP 30), détection fenêtre (DP 116), pré-chauffage (local).

Verrou/fenêtre : écriture voie 1a par tuya.m.custom.wkf.settings.change, pour les produits du
garde-fou (WRITE_VERIFIED_PRODUCTS), indisponibles hors ligne. Pré-chauffage : écrire le DP 1 côté
cloud ne change que le cache de la passerelle ; le vrai levier est l'attribut Zigbee 0x0025, par le
TUNNEL LOCAL. Le switch pré-chauffage n'existe donc que si l'option `enable_local` est active et la
passerelle joignable ; sinon il est absent (plutôt que mensonger).
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

from .api import DanfossDevice, ecriture_autorisee
from .api.local.manager import Head
from .const import DATA_COORDINATOR, DATA_LOCAL, DOMAIN
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator
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
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanfossCoordinator = data[DATA_COORDINATOR]
    local: DanfossLocalCoordinator | None = data.get(DATA_LOCAL)

    entities: list[SwitchEntity] = [
        DanfossSwitch(coordinator, dev.id, desc)
        for dev in coordinator.data.values()
        if dev.est_tete and ecriture_autorisee(dev)
        for desc in SWITCHES
    ]
    if local is not None:
        gws = local.manager.gateway_ids
        entities += [
            DanfossPreheat(local, coordinator, dev.id)
            for dev in coordinator.data.values()
            if dev.est_tete and dev.node_id and dev.mesh_id in gws
        ]
    async_add_entities(entities)


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
            dev.id, dev.product_id or "", {str(self.entity_description.dp): etat}
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_ecrire(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_ecrire(False)


class DanfossPreheat(CoordinatorEntity[DanfossLocalCoordinator], SwitchEntity):
    """Pré-chauffage réel (attribut Zigbee 0x0025) par le tunnel local.

    État et écriture passent par le tunnel ; indisponible si la tête ne répond pas en local (plutôt
    que mentir). ⚠ L'écriture de 0x0025 n'est pas confirmée en réel : à valider sur l'install.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "pre_chauffage"
    _attr_icon = "mdi:fire"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, local: DanfossLocalCoordinator, cloud: DanfossCoordinator, device_id: str
    ) -> None:
        super().__init__(local)
        self._cloud = cloud
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_pre_chauffage"

    @property
    def _dev(self) -> DanfossDevice | None:
        return self._cloud.data.get(self._device_id)

    @property
    def device_info(self) -> DeviceInfo:
        dev = self._dev
        info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=(dev.nom if dev and dev.nom else self._device_id),
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
        if not super().available or dev is None or not dev.en_ligne:
            return False
        # Indisponible tant que le tunnel n'a pas une valeur fiable pour cette tête.
        return self.coordinator.data.get(self._device_id) is not None

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.get(self._device_id)

    async def _async_ecrire(self, actif: bool) -> None:
        dev = self._dev
        if dev is None or not dev.node_id or not dev.mesh_id:
            return
        head = Head(dev.id, dev.node_id, dev.mesh_id)
        await self.hass.async_add_executor_job(
            self.coordinator.manager.ecrire_prechauffage, head, actif
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_ecrire(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_ecrire(False)
