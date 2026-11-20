"""Selects: the mounting orientation of an isolated head (DP 133), under supervised trial.

Orientation (Zigbee2MQTT ``thermostat_orientation``, the app's "mounting vertical / horizontal")
is a CANDIDATE on Tuya cloud MQTT, closed by default. The select exists only while its supervised
trial is armed for the designated isolated head of a verified model, with the local tunnel on
(docs/viewing-orientation-trial.md):

- state: the head's own flag (Danfoss attribute 0x4014), read through the local tunnel by the
  daily settings pass or by the read-back after a write; never the cloud's DP 133, which is only
  shown as the ``cloud_value`` attribute for the cross-check;
- write: ``{"133": "Vertical" | "Horizontal"}`` over cloud MQTT, confirmed by reading the flag
  back through the tunnel (``mqtt_write.async_mqtt_write_orientation``);
- after a write that sent its frame without being confirmed, the select is unavailable until the
  head is read again: the value shown before can no longer be trusted.

The meaning of the flag (false horizontal, true vertical) is Zigbee2MQTT's, not established here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api.mqtt_client import CloudMqttLink
from .const import (
    DATA_COORDINATOR,
    DATA_LOCAL,
    DATA_MQTT_LINK,
    DOMAIN,
    DP_ORIENTATION,
)
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator
from .entity import TRIAL_PATH_MQTT, DanfossTrialEntity, remove_registry_entries
from .mqtt_write import (
    ORIENTATION_FLAG,
    async_mqtt_write_orientation,
    supervised_for,
    trial_dp_armed,
)

# Option (HA state) -> value of the app's frame.
_OPTIONS = {"horizontal": "Horizontal", "vertical": "Vertical"}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanfossCoordinator = data[DATA_COORDINATOR]
    local: DanfossLocalCoordinator | None = data.get(DATA_LOCAL)
    link: CloudMqttLink | None = data.get(DATA_MQTT_LINK)
    gws = local.manager.gateway_ids if local is not None else set()

    entities: list[SelectEntity] = []
    closed: list[str] = []
    for dev in coordinator.data.values():
        if not dev.is_head:
            continue
        uid = f"{dev.id}_orientation_setting"
        addressable = bool(dev.node_id) and dev.mesh_id in gws
        if not (
            local is not None
            and addressable
            and trial_dp_armed(data, coordinator, dev, DP_ORIENTATION)
        ):
            closed.append(uid)  # trial disarmed or moved, or no tunnel to confirm with
        elif link is not None:
            entities.append(
                DanfossOrientation(coordinator, local, dev.id, link, supervised_for(data, dev.id))
            )
        # Armed but no link (it failed to start): transient, the registry entry is kept.
    remove_registry_entries(hass, entry, "select", closed)
    async_add_entities(entities)


class DanfossOrientation(DanfossTrialEntity, SelectEntity):
    """Mounting orientation of an ISOLATED head (DP 133), under supervised trial on cloud MQTT."""

    _attr_translation_key = "orientation_setting"
    _attr_options = list(_OPTIONS)
    _dp = DP_ORIENTATION

    def __init__(
        self,
        coordinator: DanfossCoordinator,
        local: DanfossLocalCoordinator,
        device_id: str,
        link: CloudMqttLink,
        supervised_dps: frozenset[int],
    ) -> None:
        super().__init__(coordinator, device_id, link, supervised_dps)
        self._local = local
        self._attr_unique_id = f"{device_id}_orientation_setting"
        # Set when a frame went out without confirmation: values read before it are not shown.
        self._untrusted_before: datetime | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The state comes from the local coordinator: follow its updates too.
        self.async_on_remove(self._local.async_add_listener(self.async_write_ha_state))

    @property
    def _settings(self) -> dict[str, Any] | None:
        return self._local.settings.get(self._device_id)

    @property
    def _flag(self) -> bool | None:
        settings = self._settings
        if settings is None:
            return None
        flag = settings.get("orientation")
        if not isinstance(flag, bool):
            return None
        if self._untrusted_before is not None:
            read_at = settings.get("read_at")
            if not isinstance(read_at, datetime) or read_at <= self._untrusted_before:
                return None
        return flag

    @property
    def available(self) -> bool:
        return super().available and self._flag is not None

    @property
    def current_option(self) -> str | None:
        flag = self._flag
        if flag is None:
            return None
        return next(opt for opt, value in _OPTIONS.items() if ORIENTATION_FLAG[value] is flag)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        settings = self._settings or {}
        dev = self.device
        attrs["raw"] = settings.get("orientation")
        attrs["read_at"] = settings.get("read_at")
        attrs["cloud_value"] = dev.orientation if dev else None
        return attrs

    def _on_not_confirmed(self) -> None:
        self._untrusted_before = dt_util.utcnow()

    async def async_select_option(self, option: str) -> None:
        dev = self.device
        if dev is None or self._write_path(dev) != TRIAL_PATH_MQTT:
            raise HomeAssistantError("orientation write unavailable for this head")
        if option not in _OPTIONS:
            raise HomeAssistantError(f"unknown orientation: {option!r}")
        await self._async_run_trial(
            async_mqtt_write_orientation(
                self._local,
                self.coordinator,
                self._link,
                dev,
                _OPTIONS[option],
                supervised=self._supervised_dps,
            )
        )
