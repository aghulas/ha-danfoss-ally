"""Binary sensors: online (connectivity), window open, heat required, mounting mode.

`online` is authoritative for connectivity (not `update_time`, an event-driven registration
timestamp that can stay frozen - see docs/architecture.md).
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api.mqtt_client import CloudMqttLink
from .const import DATA_COORDINATOR, DATA_LOCAL, DATA_MQTT_LINK, DOMAIN
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator
from .entity import DanfossEntity, DanfossHomeEntity, DanfossLocalEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanfossCoordinator = data[DATA_COORDINATOR]
    entities: list[BinarySensorEntity] = []
    for dev in coordinator.data.values():
        if not dev.is_head:
            continue
        entities.append(DanfossConnectivity(coordinator, dev.id))
        entities.append(DanfossWindow(coordinator, dev.id))
        entities.append(DanfossHeatRequired(coordinator, dev.id))
        entities.append(DanfossMountingMode(coordinator, dev.id))
    # Boiler relay on/off (read only, contract §4.6): one per relay device.
    for dev in coordinator.data.values():
        if dev.is_relay:
            entities.append(DanfossRelay(coordinator, dev.id))
    # Holiday (read only, contract §4.5): one per home.
    for gid, holiday in coordinator.holidays.items():
        entities.append(DanfossHoliday(coordinator, gid, holiday.get("name")))
    # Cloud-MQTT link connectivity (only when the live link exists, i.e. enable_cloud_mqtt on): a
    # diagnostic so the link never fails silently.
    # Read through the local tunnel by the daily settings pass: the heads it can address.
    local: DanfossLocalCoordinator | None = data.get(DATA_LOCAL)
    if local is not None:
        gws = local.manager.gateway_ids
        entities.extend(
            DanfossRadiatorCovered(local, coordinator, dev.id)
            for dev in coordinator.data.values()
            if dev.is_head and dev.node_id and dev.mesh_id in gws
        )
    link: CloudMqttLink | None = data.get(DATA_MQTT_LINK)
    if link is not None:
        entities.append(DanfossCloudMqttConnectivity(entry.entry_id, link))
    async_add_entities(entities)


class DanfossCloudMqttConnectivity(BinarySensorEntity):
    """Connectivity of the experimental cloud-MQTT link (one per entry). Polled; no secret."""

    _attr_name = "Cloud MQTT link"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = True

    def __init__(self, entry_id: str, link: CloudMqttLink) -> None:
        self._link = link
        self._attr_unique_id = f"{entry_id}_cloud_mqtt_link"

    @property
    def is_on(self) -> bool:
        return self._link.connected

    @property
    def extra_state_attributes(self) -> dict[str, str | bool]:
        # ``state`` tells a link in backoff (connecting) from one that gave up (refused).
        return {"state": self._link.state, "listen_only": self._link.listen_only}


class DanfossConnectivity(DanfossEntity, BinarySensorEntity):
    """Online / offline - available even offline (that is its purpose)."""

    _require_online = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "online"

    def __init__(self, coordinator: DanfossCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_online"

    @property
    def is_on(self) -> bool | None:
        dev = self.device
        return dev.online if dev else None


class DanfossWindow(DanfossEntity, BinarySensorEntity):
    """Open window detected by the head (DP 25)."""

    _attr_device_class = BinarySensorDeviceClass.WINDOW
    _attr_translation_key = "window"

    def __init__(self, coordinator: DanfossCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_window"

    @property
    def is_on(self) -> bool | None:
        dev = self.device
        return dev.window_open if dev else None


class DanfossHeatRequired(DanfossEntity, BinarySensorEntity):
    """The head asks the heat source for heat (DP 162 ``heat_supply_request``, read only).

    Same notion as Zigbee2MQTT's ``heat_required`` (docs/zigbee2mqtt-alignment.md). Unknown when
    the cloud does not carry the DP.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "heat_required"

    def __init__(self, coordinator: DanfossCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_heat_required"

    @property
    def is_on(self) -> bool | None:
        dev = self.device
        return dev.heat_request if dev else None


class DanfossMountingMode(DanfossEntity, BinarySensorEntity):
    """The head is in mounting mode, hence not regulating (DP 149, read only).

    Same notion as Zigbee2MQTT's ``mounted_mode_active`` (docs/zigbee2mqtt-alignment.md). Unknown
    when the cloud does not carry the DP.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "mounting_mode"

    def __init__(self, coordinator: DanfossCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_mounting_mode"

    @property
    def is_on(self) -> bool | None:
        dev = self.device
        return dev.mounting if dev else None


class DanfossRadiatorCovered(DanfossLocalEntity, BinarySensorEntity):
    """The head is set as "radiator covered" (Danfoss attribute 0x4016, read only).

    Same notion as Zigbee2MQTT's ``radiator_covered``. Read by the local tunnel's daily settings
    pass; see ``DanfossLocalEntity`` for availability and freshness.
    """

    _daily = True
    _attribute = "radiator_covered"
    _attr_translation_key = "radiator_covered"

    def __init__(
        self, local: DanfossLocalCoordinator, cloud: DanfossCoordinator, device_id: str
    ) -> None:
        super().__init__(local, cloud, device_id)
        self._attr_unique_id = f"{device_id}_radiator_covered"

    @property
    def is_on(self) -> bool | None:
        raw = self._raw
        return raw if isinstance(raw, bool) else None


class DanfossRelay(DanfossEntity, BinarySensorEntity):
    """Boiler relay on/off (DP 1, read only — contract §4.6).

    Read only by design: the app has no manual relay on/off (confirmed 2026-11-18); the relay is
    server-driven from the heat demand of the linked rooms. The control lever is the room↔relay link
    (``set_relay_room``), not a DP 1 switch. Unavailable while the relay is offline: the cloud then
    keeps its last DP 1, which read ``off`` for a relay that was simply unreachable (real install,
    2026-11-19). ``is_on`` is ``None`` when the DP is absent.
    """

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "boiler_relay"

    def __init__(self, coordinator: DanfossCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_boiler_relay"

    @property
    def is_on(self) -> bool | None:
        dev = self.device
        return dev.relay_on if dev else None


class DanfossHoliday(DanfossHomeEntity, BinarySensorEntity):
    """Holiday *in progress* on a home (read only, contract §4.5).

    ``vacation.detail`` also returns a *planned* holiday, so the state follows the record's
    ``isRunning`` flag, not its presence (a planned holiday two weeks ahead read ``on`` before,
    measured 2026-11-19). Unknown when a record lacks the flag. Attributes: ``scheduled`` (a
    holiday is on record but not started yet) and the full record as ``detail``. Writes go through
    the gated vacation services, not this entity.
    """

    _attr_translation_key = "holiday"

    def __init__(self, coordinator: DanfossCoordinator, gid: str, name: str | None) -> None:
        super().__init__(coordinator, gid, name)
        self._attr_unique_id = f"home_{gid}_holiday"

    @property
    def is_on(self) -> bool | None:
        holiday = self.holiday
        if not holiday:
            return None
        active = holiday.get("active")
        return bool(active) if active is not None else None

    @property
    def extra_state_attributes(self) -> dict | None:
        holiday = self.holiday
        if not holiday:
            return None
        attrs: dict = {"scheduled": holiday.get("scheduled")}
        if holiday.get("detail"):
            attrs["detail"] = holiday["detail"]
        return attrs
