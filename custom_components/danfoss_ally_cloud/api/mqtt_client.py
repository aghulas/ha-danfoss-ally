"""Async Tuya-cloud MQTT link for isolated-head DP publish (EXPERIMENTAL, gated OFF by default).

Builds on :mod:`mqtt_publish` (frame codec + credential derivation, reverse-engineered and validated
on real frames — see docs/cloud-mqtt-publish.md). This module adds the live layer: credentials for a
**dedicated R&D deviceId** (so it never shares the Tuya session with the Danfoss app, the iPhone app
or the MCP connector), one connection per config entry, a per-gateway ``SeqOrigin`` kept for the
whole session, subscription to ``smart/mb/in/<gw>`` and inbound-frame decoding, and a gated publish.

Transport: **paho-mqtt**, lazy-imported only when a connection is opened. Rationale: paho is already
bundled by Home Assistant (its core MQTT integration uses it), so there is no new dependency and no
second MQTT stack, and real-hardware validation confirmed it connects and coexists with the app from
the Pi. The loop runs in paho's background thread (renamed so the client id never reaches the HA
log); callbacks only touch plain counters/flags, read back on the event loop.

SAFETY: nothing here is wired to publish on its own. The publish method exists but a caller invokes
it only behind the gated option AND a real connection; there is no optimistic state. Secrets
(localKey, username, password, sid, ecode) never reach logs or ``repr``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import mqtt_publish as mp
from .client import derive_distinct_device_id

_LOGGER = logging.getLogger(__name__)

# Region -> MQTT broker host (mirrors the HTTP datacenter; the SDK uses the same m1.<region> host).
REGION_MQTT_HOST = {
    "eu": "m1.tuyaeu.com",
    "us": "m1.tuyaus.com",
    "cn": "m1.tuyacn.com",
    "in": "m1.tuyain.com",
}
DEFAULT_REGION = "eu"

# Marker for the dedicated R&D deviceId, distinct from the integration's own ("ha") and the app's.
RD_DEVICE_ID_MARKER = "mqttrd"

# The HTTP client id. The MQTT username uses this app id and the installation chKey (not the
# account deviceId).
DEFAULT_APP_ID = "7kypwcaqcvw3uvr7u95a"


def _new_paho_client(mqtt: Any, client_id: str) -> Any:
    """Create a paho ``Client`` compatible with both paho-mqtt 1.6.x and 2.x. On 2.x the callback
    API version must be chosen explicitly; we keep the v1 callback signatures used below, so we pass
    ``CallbackAPIVersion.VERSION1`` when that enum exists (paho 2) and nothing on paho 1.6.1."""
    kwargs: dict[str, Any] = {
        "client_id": client_id,
        "clean_session": True,
        "protocol": mqtt.MQTTv311,
    }
    cb = getattr(mqtt, "CallbackAPIVersion", None)
    if cb is not None:
        kwargs["callback_api_version"] = cb.VERSION1
    return mqtt.Client(**kwargs)


def region_host(region: str | None) -> str:
    """Broker host for a datacenter code; falls back to EU for an unknown/empty region."""
    return REGION_MQTT_HOST.get((region or DEFAULT_REGION).lower(), REGION_MQTT_HOST["eu"])


@dataclass(frozen=True)
class MqttCredentials:
    """What an MQTT connect needs. All fields except host/port are secret-derived."""

    host: str
    client_id: str
    username: str
    password: str
    port: int = mp.BROKER_PORT

    def redacted(self) -> dict[str, Any]:
        """Loggable view: host/port only, never the credentials."""
        return {"host": self.host, "port": self.port, "client_id": "<redacted>"}


def build_credentials(
    *,
    region: str,
    sign_key: str,
    sid: str,
    ecode: str,
    uid: str,
    partner_identity: str,
    device_id: str,
    ch_key: str,
    app_id: str = DEFAULT_APP_ID,
    package: str = "com.danfoss.ally",
) -> MqttCredentials:
    """Derive the broker credentials. ``device_id`` is the account's captured id; we connect under a
    DEDICATED derived id (``RD_DEVICE_ID_MARKER``) so the clientId cannot collide with the app
    or the integration's own session. Username/password derivations are byte-exact vs the app
    (docs §6 step 3): username uses ``app_id``/``ch_key`` (not the deviceId), so this id
    is safe here.
    """
    rd_device_id = derive_distinct_device_id(device_id, RD_DEVICE_ID_MARKER)
    return MqttCredentials(
        host=region_host(region),
        client_id=mp.mqtt_client_id(package, rd_device_id, uid),
        username=mp.mqtt_username(partner_identity, app_id, ch_key, sid, ecode),
        password=mp.mqtt_password(sign_key, ecode),
    )


@dataclass(frozen=True)
class GatewayRef:
    """A gateway we can talk to: its devId (topic), localKey (crypto) and protocol version."""

    dev_id: str
    local_key: str
    pv: str = mp.PV_2_3


@dataclass
class CloudMqttLink:
    """Per-entry MQTT link. Pure routing/accounting here; I/O is in the async methods below.

    ``gateways`` maps gateway devId -> GatewayRef. ``on_frame(gateway_id, frame)`` is called per
    decoded inbound frame. A ``SeqOrigin`` is kept per gateway for the whole session (the receiver
    drops repeated (seq, origin), so it must not reset mid-session)."""

    credentials: MqttCredentials
    gateways: dict[str, GatewayRef]
    on_frame: Callable[[str, mp.Frame], None] | None = None
    # Optional: returns fresh credentials (e.g. after the integration refreshed the sid). Used on
    # reconnect so a rotated session is picked up instead of retrying stale credentials.
    creds_provider: Callable[[], MqttCredentials] | None = None
    # Listen-only link (coverage measure): subscribes and decodes, and has NO send path —
    # ``can_publish`` is False, ``plan_dp`` and ``publish_dp`` raise. Set once, at construction.
    listen_only: bool = False
    # Plain counters, updated on the MQTT client's thread and read for the diagnostics.
    received: int = 0  # messages received on the inbound topics
    decoded: int = 0  # of which decoded and authenticated
    connects: int = 0  # accepted connections (1 + the reconnections)
    disconnects: int = 0
    _seq: dict[str, mp.SeqOrigin] = field(default_factory=dict)
    _connected: bool = False
    _client: Any = None
    # Pending write confirmations: (node_id, dp_str, value, loop, future). Resolved true when an
    # inbound frame echoes that DP for that cid (the gateway's protocol-4 report).
    _waiters: list[tuple[str, str, Any, Any, Any]] = field(default_factory=list)

    # --- pure logic (unit-tested offline) ---

    @property
    def connected(self) -> bool:
        return self._connected

    def _on_inbound(self, gateway_id: str, frame: mp.Frame) -> None:
        """Dispatch a decoded inbound frame: resolve any matching write-confirmation waiter, then
        call ``on_frame``. Runs on paho's thread, so futures are set via their own loop."""
        data: dict[Any, Any] = frame.data if isinstance(frame.data, dict) else {}
        cid = data.get("cid")
        raw_dps = data.get("dps")
        dps: dict[Any, Any] = raw_dps if isinstance(raw_dps, dict) else {}
        for node_id, dp_str, value, loop, fut in list(self._waiters):
            if cid == node_id and dp_str in dps and dps[dp_str] == value and not fut.done():
                loop.call_soon_threadsafe(fut.set_result, True)
        if self.on_frame is not None:
            self.on_frame(gateway_id, frame)

    async def await_confirmation(
        self, node_id: str, dp: int, value: Any, *, timeout_s: float
    ) -> bool:
        """Wait up to ``timeout`` s for an inbound frame confirming ``dp==value`` on ``node_id``.
        Returns False on timeout (the caller then falls back to a cloud re-read)."""
        import asyncio

        loop = asyncio.get_running_loop()
        fut: Any = loop.create_future()
        waiter = (node_id, str(dp), value, loop, fut)
        self._waiters.append(waiter)
        try:
            return bool(await asyncio.wait_for(fut, timeout_s))
        except TimeoutError:
            return False
        finally:
            if waiter in self._waiters:
                self._waiters.remove(waiter)

    def seq_for(self, gateway_id: str) -> mp.SeqOrigin:
        if gateway_id not in self._seq:
            self._seq[gateway_id] = mp.SeqOrigin()
        return self._seq[gateway_id]

    def can_publish(self, gateway_id: str) -> bool:
        """True only if the link is connected and that gateway's crypto material is known.
        Callers use this for entity availability — never assume a path that cannot actually send."""
        return self._connected and not self.listen_only and gateway_id in self.gateways

    def plan_dp(self, gateway_id: str, node_id: str, dps: dict[str | int, Any]) -> mp.PublishPlan:
        """Build the publish plan for a head (node_id) behind ``gateway_id``. Raises if the gateway
        is unknown or the link is listen-only. Does NOT send."""
        if self.listen_only:
            raise mp.FrameError("listen-only link: no publish")
        gw = self.gateways.get(gateway_id)
        if gw is None:
            raise mp.FrameError(f"unknown gateway {gateway_id}")
        return mp.build_dp_publish(
            gateway_id=gw.dev_id,
            gateway_pv=gw.pv,
            local_key=gw.local_key,
            node_id=node_id,
            dps=dps,
            counter=self.seq_for(gateway_id),
        )

    def decode_inbound(self, topic: str, payload: bytes) -> tuple[str, mp.Frame] | None:
        """Decode a message on ``smart/mb/in/<gw>`` with that gateway's localKey. Returns
        (gateway_id, frame), or None if the topic/key is unknown or the frame fails to auth."""
        gateway_id = topic.rsplit("/", 1)[-1]
        gw = self.gateways.get(gateway_id)
        if gw is None:
            return None
        try:
            return gateway_id, mp.decode_frame(gw.local_key, payload)
        except mp.FrameError:
            return None

    def inbound_topics(self) -> list[str]:
        return [mp.topic_in(gw.dev_id) for gw in self.gateways.values()]

    # --- I/O (paho — bundled by HA; only on a gated connect) ---

    def start(self, *, ca_certs: str | None = None) -> None:
        """Open the live connection (paho, TLS), subscribe to every gateway's inbound topic, and
        dispatch decoded frames to ``on_frame``. Non-blocking (loop in a thread). The connection is
        read+write capable, but ``publish_dp`` is reached only behind the opt-in write gate, and
        refuses outright on a ``listen_only`` link."""
        import ssl

        import paho.mqtt.client as mqtt

        if ca_certs is None:
            try:
                import certifi

                ca_certs = certifi.where()
            except ImportError:
                ca_certs = None

        c = self.credentials

        def on_connect(client: Any, _u: Any, _f: Any, rc: int) -> None:
            _LOGGER.warning("cloud-mqtt link: CONNACK rc=%s (%s)", rc, mqtt.connack_string(rc))
            self._connected = rc == 0
            if rc == 0:
                self.connects += 1
                for topic in self.inbound_topics():
                    client.subscribe(topic, qos=1)

        def on_message(_client: Any, _u: Any, msg: Any) -> None:
            self.received += 1
            dec = self.decode_inbound(str(msg.topic), bytes(msg.payload))
            if dec is not None:
                self.decoded += 1
                self._on_inbound(*dec)

        def on_disconnect(client: Any, _u: Any, rc: int) -> None:
            if self._connected:
                self.disconnects += 1
            self._connected = False
            # Refresh credentials before paho auto-reconnects, so a rotated sid is picked up rather
            # than retried stale. Best-effort on the loop thread.
            if self.creds_provider is not None:
                try:
                    fresh = self.creds_provider()
                    self.credentials = fresh
                    client.username_pw_set(fresh.username, fresh.password)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "cloud-mqtt link: credential refresh failed: %s", type(err).__name__
                    )

        client = _new_paho_client(mqtt, c.client_id)
        client.on_connect = on_connect
        client.on_message = on_message
        client.on_disconnect = on_disconnect
        client.username_pw_set(c.username, c.password)
        client.tls_set(ca_certs=ca_certs, cert_reqs=ssl.CERT_REQUIRED)
        client.reconnect_delay_set(min_delay=2, max_delay=60)  # exponential backoff on reconnect
        self._client = client
        client.connect_async(c.host, c.port, keepalive=60)
        client.loop_start()
        # Keep the client id (it embeds the deviceId) out of the HA log's threadName.
        thread = getattr(client, "_thread", None)
        if thread is not None:
            thread.name = "danfoss-cloud-mqtt-link"

    def stop(self) -> None:
        self._connected = False
        client = self._client
        self._client = None
        if client is not None:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:  # noqa: BLE001
                pass

    async def publish_dp(
        self, gateway_id: str, node_id: str, dps: dict[str | int, Any]
    ) -> mp.PublishPlan:
        """Publish a head DP over the live connection. GATED: a caller reaches this only behind the
        opt-in option and a real write request; raises if not connected or if the link is
        listen-only. Returns the plan sent. ``async`` for the caller's convenience; the paho publish
        itself is non-blocking."""
        if self.listen_only:
            raise mp.FrameError("listen-only link: no publish")
        if not self._connected or self._client is None:
            raise mp.FrameError("MQTT link not connected")
        plan = self.plan_dp(gateway_id, node_id, dps)
        self._client.publish(plan.topic, payload=plan.payload, qos=plan.qos, retain=plan.retain)
        return plan
