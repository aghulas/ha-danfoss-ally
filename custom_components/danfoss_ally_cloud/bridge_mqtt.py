"""v2.x ``danfoss2mqtt`` bidirectional MQTT bridge on Home Assistant's Mosquitto broker.

Implements the bridge side of ``docs/companion-contract.md``:

- Publishes (retained):
  - ``<base>/bridge/state`` (``"online"`` / ``"offline"``)
  - ``<base>/bridge/devices`` (all Danfoss heads ``014G2461``, room sensors ``014G2480``, and boiler
    relays ``014G2400`` serialized via ``api.z2m_contract.encode_z2m_descriptor``)
  - ``<base>/bridge/rooms`` (aggregated ``RoomState`` list for native Danfoss rooms)
  - ``<base>/bridge/holidays``, ``<base>/bridge/relays``, ``<base>/bridge/alerts``
  - ``<base>/<friendly_name>/availability`` and ``<base>/<friendly_name>`` (full Z2M-aligned state
    including local tunnel attributes when available)
- Subscribes to:
  - ``<base>/+/set``: routes per-device Z2M commands (``occupied_heating_setpoint``,
    ``max_heat_setpoint_limit``, ``min_heat_setpoint_limit``, ``keypad_lockout``,
    ``window_open_feature``, ``programming_operation_mode``, ``external_measured_room_sensor``,
    ``window_open_external``, ``load_room_mean``) to the configured async device command handler.
    Non-optimistic: the device state topic is only re-published after the handler completes.
  - ``<base>/bridge/request/+``: routes fleet/room RPC calls to the configured async bridge request
    handler and publishes ``{"status": "ok"|"error", "data": ..., "transaction": ...}`` on
    ``<base>/bridge/response/<action>``.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

from .api import DanfossDevice, encode_z2m_descriptor, encode_z2m_state
from .api.rooms import RoomState

_LOGGER = logging.getLogger(__name__)

AVAIL_ONLINE = "online"
AVAIL_OFFLINE = "offline"

DeviceCommandHandler = Callable[[DanfossDevice, dict[str, Any]], Awaitable[None]]
BridgeRequestHandler = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def serialize_room_state(
    room: RoomState,
    *,
    members: list[str] | tuple[str, ...] = (),
    home_id: str | None = None,
) -> dict[str, Any]:
    """Serialize a ``RoomState`` (+ member list) for ``<base>/bridge/rooms``."""
    return {
        "group_id": room.group_id,
        "name": room.name,
        "home_id": home_id,
        "pid": room.pid,
        "head_count": room.head_count,
        "members": list(members),
        "online": room.online,
        "temperature": room.temperature,
        "setpoint": room.setpoint,
        "setpoints": dict(room.setpoints),
        "mode": room.mode,
        "heating": room.heating,
        "min_setpoint": room.min_setpoint,
        "max_setpoint": room.max_setpoint,
    }


class Danfoss2MqttBridge:
    """Bidirectional v2.x ``danfoss2mqtt`` bridge over Home Assistant's MQTT component."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: Any,
        base_topic: str = "danfoss2mqtt",
        *,
        local_coordinator: Any | None = None,
        on_device_set: DeviceCommandHandler | None = None,
        on_bridge_request: BridgeRequestHandler | None = None,
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._local = local_coordinator
        self._base = base_topic.rstrip("/") or "danfoss2mqtt"
        self._on_device_set = on_device_set
        self._on_bridge_request = on_bridge_request
        self._unsubs: list[CALLBACK_TYPE] = []
        self._by_friendly: dict[str, DanfossDevice] = {}

    @property
    def base_topic(self) -> str:
        return self._base

    def _local_attrs_for(self, dev_id: str) -> dict[str, Any] | None:
        if self._local is None:
            return None
        settings = getattr(self._local, "settings", None)
        if isinstance(settings, dict):
            entry = settings.get(dev_id)
            if isinstance(entry, dict):
                return entry
        return None

    def bridge_devices_payload(self) -> list[dict[str, Any]]:
        """List of Z2M device descriptors for all heads, room sensors, and boiler relays."""
        out: list[dict[str, Any]] = []
        self._by_friendly.clear()
        devices: dict[str, DanfossDevice] = getattr(self._coordinator, "data", None) or {}
        for dev in devices.values():
            if dev.is_head or dev.is_sensor or dev.is_relay:
                desc = encode_z2m_descriptor(dev)
                self._by_friendly[desc["friendly_name"]] = dev
                out.append(desc)
        return out

    def bridge_rooms_payload(self) -> list[dict[str, Any]]:
        """List of serialized native Danfoss rooms for ``<base>/bridge/rooms``."""
        rooms: dict[str, RoomState] = getattr(self._coordinator, "rooms", None) or {}
        topo: dict[str, Any] = getattr(self._coordinator, "_rooms_topology", None) or {}
        device_home: dict[str, str] = getattr(self._coordinator, "device_home", None) or {}
        devices: dict[str, DanfossDevice] = getattr(self._coordinator, "data", None) or {}
        group_of = getattr(self._coordinator, "group_of", None)
        out: list[dict[str, Any]] = []
        for gid, room in rooms.items():
            topo_room = topo.get(gid)
            if topo_room is not None and hasattr(topo_room, "members"):
                members = list(topo_room.members)
            elif callable(group_of):
                members = [d_id for d_id in devices if group_of(d_id) == gid]
            else:
                members = []
            home_id = getattr(topo_room, "home_gid", None) or next(
                (device_home[m] for m in members if m in device_home),
                None,
            )
            out.append(serialize_room_state(room, members=members, home_id=home_id))
        return out

    async def async_start(self) -> None:
        """Publish initial bridge/fleet state and subscribe to ``+/set`` and ``bridge/request``."""
        if not await mqtt.async_wait_for_mqtt_client(self._hass):
            _LOGGER.warning("danfoss2mqtt bridge requested but MQTT broker is unavailable.")
            return

        await self.async_publish_all()

        unsub_set = await mqtt.async_subscribe(
            self._hass, f"{self._base}/+/set", self._handle_device_set_message
        )
        self._unsubs.append(unsub_set)

        unsub_req = await mqtt.async_subscribe(
            self._hass, f"{self._base}/bridge/request/+", self._handle_bridge_request_message
        )
        self._unsubs.append(unsub_req)

        unsub_coord = self._coordinator.async_add_listener(self._on_coordinator_update)
        self._unsubs.append(unsub_coord)

    async def async_stop(self) -> None:
        """Unsubscribe listeners and mark ``<base>/bridge/state`` offline."""
        while self._unsubs:
            unsub = self._unsubs.pop()
            unsub()
        with contextlib.suppress(Exception):
            await mqtt.async_publish(
                self._hass, f"{self._base}/bridge/state", AVAIL_OFFLINE, qos=0, retain=True
            )

    @callback
    def _on_coordinator_update(self) -> None:
        self._hass.async_create_task(self.async_publish_all())

    async def async_publish_all(self) -> None:
        """Publish ``bridge/state``, ``bridge/devices``, ``bridge/rooms``, and all device states."""
        await mqtt.async_publish(
            self._hass, f"{self._base}/bridge/state", AVAIL_ONLINE, qos=0, retain=True
        )
        await mqtt.async_publish(
            self._hass,
            f"{self._base}/bridge/devices",
            json.dumps(self.bridge_devices_payload()),
            qos=0,
            retain=True,
        )
        await mqtt.async_publish(
            self._hass,
            f"{self._base}/bridge/rooms",
            json.dumps(self.bridge_rooms_payload()),
            qos=0,
            retain=True,
        )
        holidays = getattr(self._coordinator, "holidays", None)
        if isinstance(holidays, dict):
            await mqtt.async_publish(
                self._hass,
                f"{self._base}/bridge/holidays",
                json.dumps(holidays),
                qos=0,
                retain=True,
            )

        devices: dict[str, DanfossDevice] = getattr(self._coordinator, "data", None) or {}
        for dev in devices.values():
            if dev.is_head or dev.is_sensor or dev.is_relay:
                await self.async_publish_device(dev)

    async def async_publish_device(self, dev: DanfossDevice) -> None:
        """Publish availability and state for a single ``DanfossDevice``."""
        desc = encode_z2m_descriptor(dev)
        friendly = desc["friendly_name"]
        self._by_friendly[friendly] = dev

        await mqtt.async_publish(
            self._hass,
            f"{self._base}/{friendly}/availability",
            AVAIL_ONLINE if dev.online else AVAIL_OFFLINE,
            qos=0,
            retain=True,
        )
        state = encode_z2m_state(dev, local_attrs=self._local_attrs_for(dev.id))
        if dev.is_relay and not state:
            return
        await mqtt.async_publish(
            self._hass,
            f"{self._base}/{friendly}",
            json.dumps(state),
            qos=0,
            retain=True,
        )

    @callback
    def _handle_device_set_message(self, msg: Any) -> None:
        self._hass.async_create_task(self._async_process_device_set(msg.topic, msg.payload))

    async def _async_process_device_set(self, topic: str, raw_payload: str | bytes) -> None:
        """Dispatch ``<base>/<friendly_name>/set`` to ``on_device_set`` (non-optimistic)."""
        if self._on_device_set is None:
            return
        prefix = f"{self._base}/"
        if not topic.startswith(prefix) or not topic.endswith("/set"):
            return
        friendly = topic[len(prefix) : -len("/set")]
        dev = self._by_friendly.get(friendly)
        if dev is None:
            _LOGGER.warning("danfoss2mqtt: unknown target %s on /set", friendly)
            return
        try:
            text = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError("JSON object expected")
        except (ValueError, UnicodeDecodeError) as err:
            _LOGGER.warning("danfoss2mqtt: invalid JSON on %s: %s", topic, err)
            return

        try:
            await self._on_device_set(dev, payload)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("danfoss2mqtt: write failed for %s: %s", friendly, err)
            return

        # Re-publish only from the refreshed coordinator state (never optimistic).
        refreshed = (getattr(self._coordinator, "data", None) or {}).get(dev.id, dev)
        await self.async_publish_device(refreshed)

    @callback
    def _handle_bridge_request_message(self, msg: Any) -> None:
        self._hass.async_create_task(self._async_process_bridge_request(msg.topic, msg.payload))

    async def _async_process_bridge_request(self, topic: str, raw_payload: str | bytes) -> None:
        """Handle ``<base>/bridge/request/<action>`` and reply on ``.../response/<action>``."""
        prefix = f"{self._base}/bridge/request/"
        if not topic.startswith(prefix):
            return
        action = topic[len(prefix) :]
        resp_topic = f"{self._base}/bridge/response/{action}"

        try:
            text = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else raw_payload
            payload = json.loads(text) if text else {}
            if not isinstance(payload, dict):
                raise ValueError("JSON object expected")
        except (ValueError, UnicodeDecodeError) as err:
            await mqtt.async_publish(
                self._hass,
                resp_topic,
                json.dumps({"status": "error", "error": f"invalid JSON: {err}"}),
                qos=0,
                retain=False,
            )
            return

        tx = payload.get("transaction")
        if self._on_bridge_request is None:
            reply: dict[str, Any] = {"status": "error", "error": "bridge requests not configured"}
        else:
            try:
                data = await self._on_bridge_request(action, payload)
                reply = {"status": "ok", "data": data}
            except Exception as err:  # noqa: BLE001
                reply = {"status": "error", "error": str(err)}
        if tx is not None:
            reply["transaction"] = tx

        await mqtt.async_publish(
            self._hass, resp_topic, json.dumps(reply), qos=0, retain=False
        )
