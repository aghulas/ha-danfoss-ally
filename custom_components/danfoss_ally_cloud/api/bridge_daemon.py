"""Standalone ``danfoss2mqtt`` bridge daemon & CLI (Batch 2.6, ``docs/companion-contract.md`` §4).

Zero Home Assistant dependency: connects ``pydanfoss_cloud`` (``DanfossDevice`` fleet + rooms) to a
standard Mosquitto MQTT broker (via ``paho-mqtt``) and speaks the Zigbee2MQTT dialect defined in
``api/z2m_contract.py``.

Can run as:
- a standalone CLI process (``danfoss2mqtt`` console script in ``pyproject.toml``),
- a Docker container / Home Assistant Add-on alongside ``ebusd`` and ``zigbee2mqtt``,
- or embedded in tests using an injected ``MqttTransport`` double (no network).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections.abc import Callable
from typing import Any, Protocol

from .decode import DanfossDevice
from .rooms import RoomState
from .z2m_contract import encode_z2m_descriptor, encode_z2m_state

_LOGGER = logging.getLogger(__name__)

AVAIL_ONLINE = "online"
AVAIL_OFFLINE = "offline"


class MqttTransport(Protocol):
    """Minimal MQTT client interface (implemented by paho-mqtt wrapper or test double)."""

    def publish(self, topic: str, payload: str, *, retain: bool = False) -> None: ...

    def subscribe(self, topic: str, callback: Callable[[str, str], None]) -> None: ...


class StandaloneDanfoss2MqttDaemon:
    """Pure-Python ``danfoss2mqtt`` bridge daemon with no Home Assistant dependency."""

    def __init__(
        self,
        transport: MqttTransport,
        base_topic: str = "danfoss2mqtt",
        *,
        on_device_set: Callable[[DanfossDevice, dict[str, Any]], None] | None = None,
        on_bridge_request: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self._transport = transport
        self._base = base_topic.rstrip("/") or "danfoss2mqtt"
        self._on_device_set = on_device_set
        self._on_bridge_request = on_bridge_request
        self._devices: dict[str, DanfossDevice] = {}
        self._by_friendly: dict[str, DanfossDevice] = {}
        self._local_attrs: dict[str, dict[str, Any]] = {}

    @property
    def base_topic(self) -> str:
        return self._base

    def start(self) -> None:
        """Announce bridge online and subscribe to ``+/set`` and ``bridge/request/+``."""
        self._transport.publish(f"{self._base}/bridge/state", AVAIL_ONLINE, retain=True)
        self._transport.subscribe(f"{self._base}/+/set", self._handle_set)
        self._transport.subscribe(
            f"{self._base}/bridge/request/+", self._handle_bridge_request
        )

    def stop(self) -> None:
        """Mark bridge offline on clean shutdown."""
        self._transport.publish(f"{self._base}/bridge/state", AVAIL_OFFLINE, retain=True)

    def publish_fleet(
        self,
        devices: list[DanfossDevice],
        rooms: list[RoomState] | None = None,
        local_attrs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Publish ``bridge/devices``, ``bridge/rooms``, and all device states to Mosquitto."""
        self._devices = {d.id: d for d in devices}
        if local_attrs is not None:
            self._local_attrs = dict(local_attrs)

        descriptors: list[dict[str, Any]] = []
        self._by_friendly.clear()
        for dev in devices:
            if dev.is_head or dev.is_sensor or dev.is_relay:
                desc = encode_z2m_descriptor(dev)
                self._by_friendly[desc["friendly_name"]] = dev
                descriptors.append(desc)

        self._transport.publish(
            f"{self._base}/bridge/devices",
            json.dumps(descriptors),
            retain=True,
        )

        if rooms is not None:
            rooms_payload = [
                {
                    "group_id": r.group_id,
                    "name": r.name,
                    "pid": r.pid,
                    "head_count": r.head_count,
                    "online": r.online,
                    "temperature": r.temperature,
                    "setpoint": r.setpoint,
                    "setpoints": dict(r.setpoints),
                    "mode": r.mode,
                    "heating": r.heating,
                }
                for r in rooms
            ]
            self._transport.publish(
                f"{self._base}/bridge/rooms",
                json.dumps(rooms_payload),
                retain=True,
            )

        for dev in devices:
            if dev.is_head or dev.is_sensor or dev.is_relay:
                self.publish_device(dev)

    def publish_device(self, dev: DanfossDevice) -> None:
        """Publish availability and state for a single ``DanfossDevice``."""
        desc = encode_z2m_descriptor(dev)
        friendly = desc["friendly_name"]
        self._by_friendly[friendly] = dev
        self._transport.publish(
            f"{self._base}/{friendly}/availability",
            AVAIL_ONLINE if dev.online else AVAIL_OFFLINE,
            retain=True,
        )
        state = encode_z2m_state(dev, local_attrs=self._local_attrs.get(dev.id))
        if dev.is_relay and not state:
            return
        self._transport.publish(
            f"{self._base}/{friendly}",
            json.dumps(state),
            retain=True,
        )

    def _handle_set(self, topic: str, raw_payload: str) -> None:
        if self._on_device_set is None:
            return
        prefix = f"{self._base}/"
        if not topic.startswith(prefix) or not topic.endswith("/set"):
            return
        friendly = topic[len(prefix) : -len("/set")]
        dev = self._by_friendly.get(friendly)
        if dev is None:
            _LOGGER.warning("danfoss2mqtt daemon: unknown target %s", friendly)
            return
        try:
            payload = json.loads(raw_payload)
            if not isinstance(payload, dict):
                raise ValueError("JSON object expected")
        except ValueError as err:
            _LOGGER.warning("danfoss2mqtt daemon: invalid JSON on %s: %s", topic, err)
            return
        self._on_device_set(dev, payload)

    def _handle_bridge_request(self, topic: str, raw_payload: str) -> None:
        prefix = f"{self._base}/bridge/request/"
        if not topic.startswith(prefix):
            return
        action = topic[len(prefix) :]
        resp_topic = f"{self._base}/bridge/response/{action}"
        try:
            payload = json.loads(raw_payload) if raw_payload else {}
            if not isinstance(payload, dict):
                raise ValueError("JSON object expected")
        except ValueError as err:
            self._transport.publish(
                resp_topic,
                json.dumps({"status": "error", "error": f"invalid JSON: {err}"}),
                retain=False,
            )
            return

        tx = payload.get("transaction")
        if self._on_bridge_request is None:
            reply: dict[str, Any] = {"status": "error", "error": "unsupported request"}
        else:
            try:
                data = self._on_bridge_request(action, payload)
                reply = {"status": "ok", "data": data}
            except Exception as err:  # noqa: BLE001
                reply = {"status": "error", "error": str(err)}
        if tx is not None:
            reply["transaction"] = tx
        self._transport.publish(resp_topic, json.dumps(reply), retain=False)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="danfoss2mqtt",
        description="Standalone Danfoss Ally -> Mosquitto (Zigbee2MQTT dialect) bridge daemon.",
    )
    parser.add_argument(
        "--mqtt-host",
        default=os.environ.get("DANFOSS_MQTT_HOST", "localhost"),
        help="Mosquitto broker hostname (default: DANFOSS_MQTT_HOST or localhost)",
    )
    parser.add_argument(
        "--mqtt-port",
        type=int,
        default=int(os.environ.get("DANFOSS_MQTT_PORT", "1883")),
        help="Mosquitto broker port (default: 1883)",
    )
    parser.add_argument(
        "--base-topic",
        default=os.environ.get("DANFOSS_BASE_TOPIC", "danfoss2mqtt"),
        help="Base MQTT topic (default: danfoss2mqtt)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``danfoss2mqtt``."""
    args = build_arg_parser().parse_args(argv)
    _LOGGER.info(
        "danfoss2mqtt configured for broker %s:%d (topic %s)",
        args.mqtt_host,
        args.mqtt_port,
        args.base_topic,
    )
    return 0
