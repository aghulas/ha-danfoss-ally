"""Common entity base: coordinator binding and device info."""

from __future__ import annotations

from collections.abc import Awaitable, Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import DanfossDevice, mqtt_dp_open, write_allowed
from .api.mqtt_client import CloudMqttLink
from .const import DOMAIN
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator
from .mqtt_write import CONFIRMED_BY_CLOUD, CONFIRMED_BY_TUNNEL, UNCHANGED, WriteNotConfirmed

# Write paths shown in the ``write_path`` attribute of the trial entities.
TRIAL_PATH_MQTT = "cloud_mqtt"
TRIAL_PATH_NONE = "none"


def remove_registry_entries(
    hass: HomeAssistant, entry: ConfigEntry, platform: str, unique_ids: Iterable[str]
) -> None:
    """Remove the registry entries (of this config entry only) of entities the configuration no
    longer provides, so they do not linger "restored, unavailable"."""
    unique_ids = list(unique_ids)
    if not unique_ids:
        return
    registry = er.async_get(hass)
    for unique_id in unique_ids:
        entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
        if entity_id is None:
            continue
        registered = registry.async_get(entity_id)
        if registered is not None and registered.config_entry_id == entry.entry_id:
            registry.async_remove(entity_id)


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


class DanfossTrialEntity(DanfossEntity):
    """A head setting under SUPERVISED TRIAL on Tuya cloud MQTT (batch C: viewing direction,
    orientation). Created only while the trial of its DP is armed for this head
    (``mqtt_write.trial_dp_armed``), in the config category.

    Available only while the write could go out right now (isolated head of a verified model, DP
    open for this head, link able to publish to its gateway) AND the state is known from its read
    source; never an optimistic state. The last trial write is reported in ``trial_result``
    (``confirmed_by_tunnel``, ``confirmed_by_cloud``, ``unchanged``, ``refused``,
    ``not_confirmed``), ``trial_at`` and ``trial_error``."""

    _attr_entity_category = EntityCategory.CONFIG
    _dp: int

    def __init__(
        self,
        coordinator: DanfossCoordinator,
        device_id: str,
        link: CloudMqttLink,
        supervised_dps: frozenset[int],
    ) -> None:
        super().__init__(coordinator, device_id)
        self._link = link
        self._supervised_dps = supervised_dps
        self._trial: dict[str, Any] = {}

    def _write_path(self, dev: DanfossDevice | None) -> str:
        if dev is None or not write_allowed(dev) or not dev.node_id or not dev.mesh_id:
            return TRIAL_PATH_NONE
        if self.coordinator.group_of(dev.id) is not None:
            return TRIAL_PATH_NONE  # a grouped head is written through its room, not here
        if not mqtt_dp_open(self._dp, self._supervised_dps):
            return TRIAL_PATH_NONE
        return TRIAL_PATH_MQTT if self._link.can_publish(dev.mesh_id) else TRIAL_PATH_NONE

    @property
    def available(self) -> bool:
        return super().available and self._write_path(self.device) != TRIAL_PATH_NONE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        path = self._write_path(self.device)
        attrs: dict[str, Any] = {"write_path": path}
        if path == TRIAL_PATH_MQTT:
            attrs["write_scope"] = "head"
            attrs["write_trial"] = True
        attrs.update(self._trial)
        return attrs

    async def _async_run_trial(self, write: Awaitable[str]) -> None:
        """Run one trial write and keep its outcome in the attributes (the error is re-raised)."""
        now = dt_util.utcnow().isoformat()
        try:
            source = await write
        except WriteNotConfirmed as err:
            self._trial = {
                "trial_result": "not_confirmed",
                "trial_at": now,
                "trial_error": str(err),
            }
            self._on_not_confirmed()
            self.async_write_ha_state()
            raise
        except HomeAssistantError as err:
            self._trial = {"trial_result": "refused", "trial_at": now, "trial_error": str(err)}
            self.async_write_ha_state()
            raise
        result = {
            UNCHANGED: "unchanged",
            CONFIRMED_BY_TUNNEL: "confirmed_by_tunnel",
            CONFIRMED_BY_CLOUD: "confirmed_by_cloud",
        }.get(source, source)
        self._trial = {"trial_result": result, "trial_at": now}
        self.async_write_ha_state()

    def _on_not_confirmed(self) -> None:
        """Hook: a frame went out and nothing confirmed it."""
