"""v2.x Unified MQTT Companion Coordinator (``docs/companion-contract.md`` §2 & §3).

Subscribes on Home Assistant's Mosquitto broker to one or more Zigbee2MQTT-compatible bridge
prefixes (default: ``("zigbee2mqtt", "danfoss2mqtt")``) and merges all discovered Danfoss devices
into a single fleet:

- ``014G2461`` / ``03wvrwpv`` thermostats -> ``DanfossDevice(category="head")``
- ``014G2480`` / ``mxzo5rhf`` room sensors -> ``DanfossDevice(category="sensor")``
- ``014G2400`` / ``ypieax1h`` boiler relays -> ``DanfossDevice(category="relay")``

Non-Danfoss devices on ``zigbee2mqtt`` (Sonoff routers, Aqara contacts, lights, etc.) are ignored.
Commands to any discovered device are published via ``async_send_device_set`` to the device's own
bridge prefix (``<prefix>/<friendly_name>/set``).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

from .api import (
    DanfossDevice,
    decode_z2m_descriptor,
    decode_z2m_state,
    encode_z2m_set_command,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_COMPANION_PREFIXES: tuple[str, ...] = ("zigbee2mqtt", "danfoss2mqtt")


def _parse_online_payload(raw: str | bytes) -> bool | None:
    text = (raw.decode("utf-8") if isinstance(raw, bytes) else raw).strip()
    if not text:
        return None
    low = text.lower()
    if low in ("online", "true", "1"):
        return True
    if low in ("offline", "false", "0"):
        return False
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "state" in obj:
            return str(obj["state"]).strip().lower() == "online"
    except ValueError:
        pass
    return None


class MqttCompanionCoordinator:
    """Unified MQTT Companion state across ``zigbee2mqtt`` and ``danfoss2mqtt``."""

    def __init__(
        self,
        hass: HomeAssistant,
        prefixes: tuple[str, ...] | list[str] = DEFAULT_COMPANION_PREFIXES,
    ) -> None:
        self.hass = hass
        self.prefixes: tuple[str, ...] = tuple(
            dict.fromkeys(p.strip().rstrip("/") for p in prefixes if p.strip().rstrip("/"))
        )
        # dev_id -> DanfossDevice
        self.data: dict[str, DanfossDevice] = {}
        # dev_id -> (prefix, friendly_name)
        self.device_route: dict[str, tuple[str, str]] = {}
        # (prefix, friendly_name) -> dev_id
        self._by_topic_key: dict[tuple[str, str], str] = {}
        # prefix -> bridge online bool
        self.bridge_online: dict[str, bool] = {p: False for p in self.prefixes}
        # Native rooms published on <prefix>/bridge/rooms (group_id -> raw room dict)
        self.native_rooms: dict[str, dict[str, Any]] = {}
        # Native holidays published on <prefix>/bridge/holidays
        self.holidays: dict[str, dict[str, Any]] = {}

        self._unsubs: list[CALLBACK_TYPE] = []
        self._listeners: list[Callable[[], None]] = []

    @callback
    def async_add_listener(
        self, update_callback: Callable[[], None], context: Any = None
    ) -> CALLBACK_TYPE:
        """Register a listener notified whenever the fleet or room state changes."""
        self._listeners.append(update_callback)

        @callback
        def _remove() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return _remove

    @callback
    def _notify_listeners(self) -> None:
        for listener in list(self._listeners):
            listener()

    async def async_start(self) -> None:
        """Subscribe to all configured bridge prefixes on Mosquitto."""
        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            _LOGGER.warning("Danfoss MQTT Companion: MQTT broker not available.")
            return

        for prefix in self.prefixes:
            for pattern in (
                f"{prefix}/bridge/state",
                f"{prefix}/bridge/devices",
                f"{prefix}/bridge/rooms",
                f"{prefix}/bridge/holidays",
                f"{prefix}/+",
                f"{prefix}/+/availability",
            ):
                unsub = await mqtt.async_subscribe(self.hass, pattern, self._handle_message)
                self._unsubs.append(unsub)

    async def async_stop(self) -> None:
        """Unsubscribe all MQTT topics."""
        while self._unsubs:
            unsub = self._unsubs.pop()
            unsub()

    @callback
    def _handle_message(self, msg: Any) -> None:
        self.process_mqtt_message(msg.topic, msg.payload)

    @callback
    def process_mqtt_message(self, topic: str, raw_payload: str | bytes) -> None:
        """Process a single inbound MQTT message (synchronous, callable directly in tests)."""
        matched_prefix: str | None = None
        for p in self.prefixes:
            if topic.startswith(f"{p}/"):
                matched_prefix = p
                break
        if matched_prefix is None:
            return

        suffix = topic[len(matched_prefix) + 1 :]
        if suffix == "bridge/state":
            online = _parse_online_payload(raw_payload)
            if online is not None:
                self.bridge_online[matched_prefix] = online
                self._notify_listeners()
            return

        if suffix == "bridge/devices":
            self._ingest_bridge_devices(matched_prefix, raw_payload)
            return

        if suffix == "bridge/rooms":
            self._ingest_bridge_rooms(raw_payload)
            return

        if suffix == "bridge/holidays":
            self._ingest_bridge_holidays(raw_payload)
            return

        if suffix.startswith("bridge/") or suffix.endswith("/set"):
            return

        if suffix.endswith("/availability"):
            friendly = suffix[: -len("/availability")]
            if "/" in friendly:
                return
            dev_id = self._by_topic_key.get((matched_prefix, friendly))
            if dev_id is not None and dev_id in self.data:
                online = _parse_online_payload(raw_payload)
                if online is not None:
                    self.data[dev_id].online = online
                    self._notify_listeners()
            return

        if "/" not in suffix:
            self._ingest_device_state(matched_prefix, suffix, raw_payload)

    def _ingest_bridge_devices(self, prefix: str, raw_payload: str | bytes) -> None:
        try:
            text = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload
            entries = json.loads(text)
            if not isinstance(entries, list):
                return
        except (ValueError, UnicodeDecodeError):
            return

        seen_for_prefix: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            dev = decode_z2m_descriptor(entry)
            if dev is None:
                continue
            friendly = str(entry.get("friendly_name") or dev.name)
            existing = self.data.get(dev.id)
            if existing is not None:
                existing.name = dev.name
                existing.product_id = dev.product_id or existing.product_id
                existing.node_id = dev.node_id or existing.node_id
                existing.mesh_id = dev.mesh_id or existing.mesh_id
            else:
                self.data[dev.id] = dev
            self.device_route[dev.id] = (prefix, friendly)
            self._by_topic_key[(prefix, friendly)] = dev.id
            seen_for_prefix.add(dev.id)

        # Remove stale devices that belonged to this prefix and disappeared from bridge/devices
        stale_ids = [
            dev_id
            for dev_id, (p, _f) in list(self.device_route.items())
            if p == prefix and dev_id not in seen_for_prefix
        ]
        for dev_id in stale_ids:
            p, f = self.device_route.pop(dev_id)
            self._by_topic_key.pop((p, f), None)
            self.data.pop(dev_id, None)

        self._notify_listeners()

    def _ingest_device_state(self, prefix: str, friendly: str, raw_payload: str | bytes) -> None:
        dev_id = self._by_topic_key.get((prefix, friendly))
        if dev_id is None or dev_id not in self.data:
            return
        try:
            text = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload
            payload = json.loads(text)
            if not isinstance(payload, dict):
                return
        except (ValueError, UnicodeDecodeError):
            return

        decode_z2m_state(self.data[dev_id], payload)
        self._notify_listeners()

    def _ingest_bridge_rooms(self, raw_payload: str | bytes) -> None:
        try:
            text = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload
            rooms = json.loads(text)
            if not isinstance(rooms, list):
                return
        except (ValueError, UnicodeDecodeError):
            return

        self.native_rooms = {
            str(r["group_id"]): r
            for r in rooms
            if isinstance(r, dict) and r.get("group_id") is not None
        }
        self._notify_listeners()

    def _ingest_bridge_holidays(self, raw_payload: str | bytes) -> None:
        try:
            text = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload
            holidays = json.loads(text)
            if not isinstance(holidays, dict):
                return
        except (ValueError, UnicodeDecodeError):
            return
        self.holidays = holidays
        self._notify_listeners()

    async def async_send_device_set(self, dev_id: str, **kwargs: Any) -> dict[str, Any]:
        """Publish a normalized command to ``<prefix>/<friendly_name>/set`` for ``dev_id``."""
        route = self.device_route.get(dev_id)
        if route is None:
            raise KeyError(f"Unknown device id: {dev_id}")
        prefix, friendly = route
        cmd = encode_z2m_set_command(**kwargs)
        await mqtt.async_publish(
            self.hass, f"{prefix}/{friendly}/set", json.dumps(cmd), qos=0, retain=False
        )
        return cmd

    async def async_send_raw_device_set(self, dev_id: str, payload: dict[str, Any]) -> None:
        """Publish a raw JSON payload (e.g. ``weekly_schedule``) to ``<prefix>/<friendly>/set``."""
        route = self.device_route.get(dev_id)
        if route is None:
            raise KeyError(f"Unknown device id: {dev_id}")
        prefix, friendly = route
        await mqtt.async_publish(
            self.hass, f"{prefix}/{friendly}/set", json.dumps(payload), qos=0, retain=False
        )
