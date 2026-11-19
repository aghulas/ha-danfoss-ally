"""Async Tuya-cloud MQTT link for isolated-head DP publish (EXPERIMENTAL, gated OFF by default).

Builds on :mod:`mqtt_publish` (frame codec + credential derivation, reverse-engineered and validated
on real frames — see docs/cloud-mqtt-publish.md). This module adds the live layer: credentials for a
**dedicated R&D deviceId** (so it never shares the Tuya session with the Danfoss app, the iPhone app
or the MCP connector), one connection per config entry, a per-gateway ``SeqOrigin`` kept for the
whole session, subscription to ``smart/mb/in/<gw>`` and inbound-frame decoding, and a gated publish.

Transport: **aiomqtt** (chosen over bare paho-mqtt), lazy-imported only when a connection is
opened. Rationale: aiomqtt is a thin asyncio wrapper over the very paho-mqtt that Home Assistant
already ships, so it adds no new native dependency and no second MQTT stack; it gives a native
``async with`` client and an async message iterator, dropping straight into HA's loop with no
bridging of a paho background thread into asyncio (that bridging is the usual source of race
conditions and shutdown leaks). Because it is lazy-imported, installs that leave the feature OFF
never load it.

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

# ThingSmartNetWork.mAppId (= the HTTP clientId). The MQTT username's chKey is getChKey(ctx, appId),
# so this is the app id used there, not the account deviceId.
DEFAULT_APP_ID = "7kypwcaqcvw3uvr7u95a"


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
    _seq: dict[str, mp.SeqOrigin] = field(default_factory=dict)
    _connected: bool = False
    _client: Any = None

    # --- pure logic (unit-tested offline) ---

    @property
    def connected(self) -> bool:
        return self._connected

    def seq_for(self, gateway_id: str) -> mp.SeqOrigin:
        if gateway_id not in self._seq:
            self._seq[gateway_id] = mp.SeqOrigin()
        return self._seq[gateway_id]

    def can_publish(self, gateway_id: str) -> bool:
        """True only if the link is connected and that gateway's crypto material is known.
        Callers use this for entity availability — never assume a path that cannot actually send."""
        return self._connected and gateway_id in self.gateways

    def plan_dp(self, gateway_id: str, node_id: str, dps: dict[str | int, Any]) -> mp.PublishPlan:
        """Build the publish plan for a head (node_id) behind ``gateway_id``. Raises if the gateway
        is unknown. Does NOT send."""
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

    # --- async I/O (aiomqtt, lazy-imported; exercised only on a live, gated connection) ---

    async def run(self, ready: Callable[[], None] | None = None) -> None:
        """Connect, subscribe to every gateway's inbound topic, and dispatch decoded frames to
        ``on_frame`` until cancelled. READ path only; never publishes. Reconnection on ``sid``
        refresh is handled by the caller recreating the link with fresh credentials."""
        import aiomqtt  # lazy: only when a live connection is opened

        c = self.credentials
        async with aiomqtt.Client(
            hostname=c.host,
            port=c.port,
            identifier=c.client_id,
            username=c.username,
            password=c.password,
            tls_params=aiomqtt.TLSParameters(),
        ) as client:
            self._client = client
            self._connected = True
            try:
                for topic in self.inbound_topics():
                    await client.subscribe(topic, qos=1)
                if ready is not None:
                    ready()
                async for message in client.messages:
                    dec = self.decode_inbound(str(message.topic), bytes(message.payload))
                    if dec is not None and self.on_frame is not None:
                        self.on_frame(*dec)
            finally:
                self._connected = False

    async def publish_dp(
        self, gateway_id: str, node_id: str, dps: dict[str | int, Any]
    ) -> mp.PublishPlan:
        """Publish a head DP over the live connection. GATED: a caller reaches this only behind the
        opt-in option and a real write request; raises if not connected. Returns the plan sent."""
        if not self._connected or self._client is None:
            raise mp.FrameError("MQTT link not connected")
        plan = self.plan_dp(gateway_id, node_id, dps)
        await self._client.publish(
            plan.topic, payload=plan.payload, qos=plan.qos, retain=plan.retain
        )
        return plan


# --- Listen-only probe (paho; NO publish path by construction) -----------------------------------
#
# A deliberately separate class from CloudMqttLink: it has no publish method and never calls the
# client's publish(), so there is no send path to misuse (a test asserts this). paho-mqtt is used
# here (bundled by Home Assistant, so no new dependency and it runs on the Pi) rather than aiomqtt.
# It records a redacted result for diagnostics: CONNACK rc, timestamps, per-gateway received/decoded
# counts, a few sample (protocol, cid) tuples, and the last error — never any secret or raw payload.


@dataclass
class MqttProbeStats:
    """Redacted result of a probe run. No sid/ecode/username/localKey or raw bytes."""

    started_at: float | None = None
    connack_rc: int | None = None
    connack_text: str | None = None
    connected_at: float | None = None
    disconnected_at: float | None = None
    stopped_reason: str | None = None
    received: dict[str, int] = field(default_factory=dict)  # gateway_id -> frames received
    decoded: dict[str, int] = field(default_factory=dict)  # gateway_id -> frames decoded
    samples: list[dict[str, Any]] = field(default_factory=list)  # [{gateway, protocol, cid}]
    last_error: str | None = None

    def as_diagnostics(self) -> dict[str, Any]:
        """Plain dict for diagnostics. Everything here is already non-secret."""
        return {
            "started_at": self.started_at,
            "connack_rc": self.connack_rc,
            "connack_text": self.connack_text,
            "connected_at": self.connected_at,
            "disconnected_at": self.disconnected_at,
            "stopped_reason": self.stopped_reason,
            "received_per_gateway": dict(self.received),
            "decoded_per_gateway": dict(self.decoded),
            "sample_frames": list(self.samples),
            "last_error": self.last_error,
            "total_received": sum(self.received.values()),
            "total_decoded": sum(self.decoded.values()),
        }


class CloudMqttListener:
    """Read-only Tuya cloud MQTT probe. Connects, subscribes to smart/mb/in/<gw>, decodes inbound
    frames into redacted stats, and auto-stops. **No publish path**: this class exposes no send
    method and never calls the client's publish()."""

    def __init__(
        self,
        credentials: MqttCredentials,
        gateways: dict[str, GatewayRef],
        *,
        max_samples: int = 5,
    ) -> None:
        self._creds = credentials
        self._gateways = gateways
        self._max_samples = max_samples
        self.stats = MqttProbeStats()
        self._client: Any = None

    # Pure handler (unit-tested): decode one message into the stats. No I/O, no send.
    def handle_message(self, topic: str, payload: bytes) -> None:
        gateway_id = topic.rsplit("/", 1)[-1]
        gw = self._gateways.get(gateway_id)
        if gw is None:
            return
        self.stats.received[gateway_id] = self.stats.received.get(gateway_id, 0) + 1
        try:
            frame = mp.decode_frame(gw.local_key, payload)
        except mp.FrameError:
            return
        self.stats.decoded[gateway_id] = self.stats.decoded.get(gateway_id, 0) + 1
        if len(self.stats.samples) < self._max_samples:
            data = frame.data if isinstance(frame.data, dict) else {}
            self.stats.samples.append(
                {"gateway": gateway_id, "protocol": frame.protocol, "cid": data.get("cid")}
            )

    def inbound_topics(self) -> list[str]:
        return [mp.topic_in(gw.dev_id) for gw in self._gateways.values()]

    def start(self, *, ca_certs: str | None = None) -> None:
        """Open the read-only connection (paho, TLS) and subscribe; non-blocking (loop thread)."""
        import ssl
        import time

        import paho.mqtt.client as mqtt

        if ca_certs is None:
            try:
                import certifi

                ca_certs = certifi.where()
            except ImportError:
                ca_certs = None

        self.stats.started_at = time.time()
        c = self._creds

        def on_connect(client: Any, _u: Any, _f: Any, rc: int) -> None:
            self.stats.connack_rc = rc
            self.stats.connack_text = mqtt.connack_string(rc)
            # Logged (non-secret) so the verdict is readable from the HA log without diagnostics.
            _LOGGER.warning("cloud-mqtt probe: CONNACK rc=%s (%s)", rc, self.stats.connack_text)
            if rc == 0:
                self.stats.connected_at = time.time()
                for topic in self.inbound_topics():
                    client.subscribe(topic, qos=1)

        def on_message(_client: Any, _u: Any, msg: Any) -> None:
            try:
                self.handle_message(str(msg.topic), bytes(msg.payload))
            except Exception as err:  # noqa: BLE001 - never let a bad frame kill the loop
                self.stats.last_error = f"{type(err).__name__}"

        def on_disconnect(_client: Any, _u: Any, rc: int) -> None:
            self.stats.disconnected_at = time.time()

        client = mqtt.Client(client_id=c.client_id, clean_session=True, protocol=mqtt.MQTTv311)
        client.on_connect = on_connect
        client.on_message = on_message
        client.on_disconnect = on_disconnect
        client.username_pw_set(c.username, c.password)
        client.tls_set(ca_certs=ca_certs, cert_reqs=ssl.CERT_REQUIRED)
        self._client = client
        try:
            client.connect_async(c.host, c.port, keepalive=60)
            client.loop_start()
            # paho names its loop thread "paho-mqtt-client-<client_id>", which would put the client
            # id (it embeds the deviceId) in the HA log's threadName. Rename it so no identifier
            # leaks into logs (diagnostics already redact it). Best-effort, private attr.
            thread = getattr(client, "_thread", None)
            if thread is not None:
                thread.name = "danfoss-cloud-mqtt-probe"
        except Exception as err:  # noqa: BLE001 - record and stay down, never raise into setup
            self.stats.last_error = f"{type(err).__name__}: {err}"

    def stop(self, reason: str = "stopped") -> None:
        self.stats.stopped_reason = reason
        # Non-secret summary to the HA log: the verdict counts, readable via the admin connector.
        _LOGGER.warning(
            "cloud-mqtt probe stopped (%s): connack_rc=%s received=%s decoded=%s last_error=%s",
            reason,
            self.stats.connack_rc,
            sum(self.stats.received.values()),
            sum(self.stats.decoded.values()),
            self.stats.last_error,
        )
        client = self._client
        self._client = None
        if client is not None:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:  # noqa: BLE001
                pass
