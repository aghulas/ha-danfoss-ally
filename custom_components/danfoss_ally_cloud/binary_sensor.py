"""Binary sensors: online (connectivity), window open.

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
from .const import DATA_COORDINATOR, DATA_MQTT_LINK, DOMAIN
from .coordinator import DanfossCoordinator
from .entity import DanfossEntity, DanfossHomeEntity


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
    # Boiler relay on/off (read only, contract §4.6): one per relay device.
    for dev in coordinator.data.values():
        if dev.is_relay:
            entities.append(DanfossRelay(coordinator, dev.id))
    # Holiday (read only, contract §4.5): one per home.
    for gid, holiday in coordinator.holidays.items():
        entities.append(DanfossHoliday(coordinator, gid, holiday.get("name")))
    # Cloud-MQTT link connectivity (only when the live link exists, i.e. enable_cloud_mqtt on): a
    # diagnostic so the link never fails silently.
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


class DanfossRelay(DanfossEntity, BinarySensorEntity):
    """Boiler relay on/off (DP 1, read only — contract §4.6).

    Read only by design: the app has no manual relay on/off (confirmed 2026-11-18); the relay is
    server-driven from the heat demand of the linked rooms. The control lever is the room↔relay link
    (``set_relay_room``), not a DP 1 switch. Stays available even when the relay is briefly offline
    (the last state is still informative); ``is_on`` is ``None`` when the DP is absent.
    """

    _require_online = False
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "boiler_relay"
    _attr_icon = "mdi:water-boiler"

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
    _attr_icon = "mdi:bag-suitcase"

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
