"""CloudMqttLink pure-logic tests (no network, synthetic data)."""

import pytest

from custom_components.danfoss_ally_cloud.api import mqtt_client as mc
from custom_components.danfoss_ally_cloud.api import mqtt_publish as mp

KEY = "0123456789abcdef"  # synthetic 16-char localKey
GW = "bfsyngatewaydevid000x"


def _link(connected=False):
    link = mc.CloudMqttLink(
        credentials=mc.MqttCredentials(host="h", client_id="c", username="u", password="p"),
        gateways={GW: mc.GatewayRef(dev_id=GW, local_key=KEY)},
    )
    link._connected = connected
    return link


def test_region_host():
    assert mc.region_host("eu") == "m1.tuyaeu.com"
    assert mc.region_host("US") == "m1.tuyaus.com"
    assert mc.region_host(None) == "m1.tuyaeu.com"
    assert mc.region_host("zz") == "m1.tuyaeu.com"  # unknown -> EU


def test_build_credentials_matches_mqtt_publish_and_uses_dedicated_device_id():
    from custom_components.danfoss_ally_cloud.api.client import derive_distinct_device_id

    sk = "com.danfoss.ally_" + "aa:" * 15 + "aa_" + "b" * 32 + "_" + "c" * 32
    creds = mc.build_credentials(
        region="eu",
        sign_key=sk,
        sid="eu123",
        ecode="ECODE0123456789",
        uid="uid-1",
        partner_identity="p100",
        device_id="appdeviceid0000",
        ch_key="abcd1234",
    )
    assert creds.host == "m1.tuyaeu.com" and creds.port == 8883
    assert creds.password == mp.mqtt_password(sk, "ECODE0123456789")
    assert creds.username == mp.mqtt_username(
        "p100", mc.DEFAULT_APP_ID, "abcd1234", "eu123", "ECODE0123456789"
    )
    # clientId uses a DEDICATED deviceId, not the app's.
    rd = derive_distinct_device_id("appdeviceid0000", mc.RD_DEVICE_ID_MARKER)
    assert rd != "appdeviceid0000"
    assert creds.client_id == mp.mqtt_client_id("com.danfoss.ally", rd, "uid-1")
    assert "<redacted>" in str(creds.redacted())


def test_seq_origin_is_per_gateway_and_persists():
    link = _link()
    a1 = link.seq_for("gwA")
    a2 = link.seq_for("gwA")
    b = link.seq_for("gwB")
    assert a1 is a2 and a1 is not b  # one SeqOrigin per gateway, kept across calls
    s1, o1 = a1.next()
    s2, o2 = a1.next()
    assert o1 == o2 and s2 == s1 + 1  # monotonic within a gateway


def test_can_publish_requires_connected_and_known_gateway():
    assert _link(connected=False).can_publish(GW) is False
    assert _link(connected=True).can_publish(GW) is True
    assert _link(connected=True).can_publish("other") is False


def test_plan_dp_targets_gateway_topic_and_roundtrips():
    link = _link(connected=True)
    plan = link.plan_dp(GW, "node-9", {"30": True})
    assert plan.topic == f"smart/mb/out/{GW}"
    assert (plan.qos, plan.retain) == (1, False)
    f = mp.decode_frame(KEY, plan.payload)
    assert f.data == {"cid": "node-9", "ctype": 0, "dps": {"30": True}}
    assert f.protocol == mp.PROTOCOL_DP_PUBLISH


def test_plan_dp_unknown_gateway_raises():
    with pytest.raises(mp.FrameError):
        _link(connected=True).plan_dp("nope", "node-9", {"30": True})


def test_decode_inbound_uses_right_key_and_rejects_unknown():
    link = _link(connected=True)
    # A frame as the gateway would send it (built with the gateway localKey).
    raw = mp.encode_frame(
        KEY, {"cid": "node-9", "dps": {"116": False}}, seq=4, origin=7, protocol=4
    )
    got = link.decode_inbound(f"smart/mb/in/{GW}", raw)
    assert got is not None
    gw_id, frame = got
    assert gw_id == GW and frame.data["dps"] == {"116": False} and frame.protocol == 4
    # Unknown gateway topic -> None (no key).
    assert link.decode_inbound("smart/mb/in/unknown", raw) is None
    # Wrong key -> authentication fails -> None (not an exception).
    bad = mc.CloudMqttLink(
        credentials=link.credentials,
        gateways={GW: mc.GatewayRef(dev_id=GW, local_key="fedcba9876543210")},
    )
    assert bad.decode_inbound(f"smart/mb/in/{GW}", raw) is None


def test_inbound_topics():
    assert _link().inbound_topics() == [f"smart/mb/in/{GW}"]


async def test_publish_dp_refuses_when_not_connected():
    link = _link(connected=False)
    with pytest.raises(mp.FrameError):
        await link.publish_dp(GW, "node-9", {"30": True})


# --- listen-only probe (no publish path) --------------------------------------------------------


class _FakePaho:
    """Minimal paho.mqtt.client.Client double: records calls, lets tests fire callbacks."""

    instances = []

    def __init__(
        self, client_id=None, clean_session=True, protocol=None, callback_api_version=None
    ):
        # callback_api_version: passed by _new_paho_client when the real paho is 2.x (the module
        # the tests patch keeps its CallbackAPIVersion enum); None on paho 1.6.1.
        self.client_id = client_id
        self.callback_api_version = callback_api_version
        self.on_connect = self.on_message = self.on_disconnect = None
        self.subscribed = []
        self.username = self.password = None
        self.tls = None
        self.loop_started = self.loop_stopped = self.disconnected = False
        self.loop_stop_thread = None
        self.published = []
        self.connected_to = None
        import types

        self._thread = types.SimpleNamespace(name=f"paho-mqtt-client-{client_id}")
        _FakePaho.instances.append(self)

    def username_pw_set(self, u, p):
        self.username, self.password = u, p

    def tls_set(self, **kw):
        self.tls = kw

    def reconnect_delay_set(self, **kw):
        self.reconnect_delay = kw

    def connect_async(self, host, port, keepalive=60):
        self.connected_to = (host, port)

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        import threading

        self.loop_stopped = True
        self.loop_stop_thread = threading.current_thread()

    def disconnect(self):
        self.disconnected = True

    def subscribe(self, topic, qos=0):
        self.subscribed.append((topic, qos))

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))


async def test_link_start_connect_publish_and_stop(monkeypatch):
    import paho.mqtt.client as paho

    _FakePaho.instances.clear()
    monkeypatch.setattr(paho, "Client", _FakePaho)
    link = mc.CloudMqttLink(
        credentials=mc.MqttCredentials(host="h", client_id="c", username="u", password="p"),
        gateways={GW: mc.GatewayRef(dev_id=GW, local_key=KEY)},
    )
    link.start(ca_certs="/dev/null")
    c = _FakePaho.instances[-1]
    assert c.loop_started and c._thread.name == "danfoss-cloud-mqtt-link"
    # not authorised yet -> cannot publish
    assert link.can_publish(GW) is False
    c.on_connect(c, None, None, 0)  # broker accepts
    assert link.can_publish(GW) is True
    assert c.subscribed == [(f"smart/mb/in/{GW}", 1)]
    plan = await link.publish_dp(GW, "node-9", {"30": True})
    assert plan.topic == f"smart/mb/out/{GW}"
    assert c.published and c.published[-1][0] == f"smart/mb/out/{GW}"  # bytes went out
    f = mp.decode_frame(KEY, c.published[-1][1])
    assert f.data == {"cid": "node-9", "ctype": 0, "dps": {"30": True}}
    c.on_disconnect(c, None, 0)
    assert link.can_publish(GW) is False  # drop -> unavailable, never optimistic
    link.stop()
    assert c.loop_stopped and c.disconnected


async def test_await_confirmation_resolves_on_matching_inbound_frame():
    import asyncio

    link = mc.CloudMqttLink(
        credentials=mc.MqttCredentials(host="h", client_id="c", username="u", password="p"),
        gateways={GW: mc.GatewayRef(dev_id=GW, local_key=KEY)},
    )

    async def feed_after(delay):
        await asyncio.sleep(delay)
        # an inbound protocol-4 report echoing DP 30 = True for node-9
        raw = mp.encode_frame(
            KEY, {"cid": "node-9", "dps": {"30": True}}, seq=9, origin=1, protocol=4
        )
        link._on_inbound(*link.decode_inbound(f"smart/mb/in/{GW}", raw))

    task = asyncio.ensure_future(feed_after(0.01))
    ok = await link.await_confirmation("node-9", 30, True, timeout_s=1.0)
    await task
    assert ok is True


async def test_await_confirmation_times_out_without_frame():
    link = mc.CloudMqttLink(
        credentials=mc.MqttCredentials(host="h", client_id="c", username="u", password="p"),
        gateways={GW: mc.GatewayRef(dev_id=GW, local_key=KEY)},
    )
    assert await link.await_confirmation("node-9", 30, True, timeout_s=0.05) is False
    assert link._waiters == []  # cleaned up


async def test_await_confirmation_ignores_other_cid_or_value():
    import asyncio

    link = mc.CloudMqttLink(
        credentials=mc.MqttCredentials(host="h", client_id="c", username="u", password="p"),
        gateways={GW: mc.GatewayRef(dev_id=GW, local_key=KEY)},
    )

    async def feed():
        await asyncio.sleep(0.01)
        other = mp.encode_frame(
            KEY, {"cid": "other", "dps": {"30": True}}, seq=1, origin=1, protocol=4
        )
        link._on_inbound(*link.decode_inbound(f"smart/mb/in/{GW}", other))
        wrongval = mp.encode_frame(
            KEY, {"cid": "node-9", "dps": {"30": False}}, seq=2, origin=1, protocol=4
        )
        link._on_inbound(*link.decode_inbound(f"smart/mb/in/{GW}", wrongval))

    task = asyncio.ensure_future(feed())
    assert await link.await_confirmation("node-9", 30, True, timeout_s=0.1) is False
    await task


def test_new_paho_client_supports_paho1_and_paho2():
    """paho 1.6.1 (no CallbackAPIVersion) vs paho 2.x: pass VERSION1 only when the enum exists."""
    import types

    captured: dict = {}

    class _Client:
        def __init__(self, **kw):
            captured.update(kw)

    # paho 1.6.1: no CallbackAPIVersion -> no callback_api_version kwarg
    m1 = types.SimpleNamespace(Client=_Client, MQTTv311=4)
    mc._new_paho_client(m1, "cid")
    assert captured["client_id"] == "cid" and "callback_api_version" not in captured

    captured.clear()

    # paho 2.x: CallbackAPIVersion.VERSION1 is passed (keeps the v1 callback signatures)
    class _CB:
        VERSION1 = "v1"

    m2 = types.SimpleNamespace(Client=_Client, MQTTv311=4, CallbackAPIVersion=_CB)
    mc._new_paho_client(m2, "cid")
    assert captured["callback_api_version"] == "v1"
