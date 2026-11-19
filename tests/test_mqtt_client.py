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


def _listener():
    return mc.CloudMqttListener(
        credentials=mc.MqttCredentials(host="h", client_id="c", username="u", password="p"),
        gateways={GW: mc.GatewayRef(dev_id=GW, local_key=KEY)},
    )


def test_listener_has_no_publish_path():
    """Hard guarantee: the probe object exposes no send method at all (not just a flag)."""
    lst = _listener()
    for name in dir(lst):
        assert "publish" not in name.lower(), f"unexpected send-like member: {name}"
    assert not hasattr(lst, "publish")
    assert not hasattr(lst, "publish_dp")
    assert not hasattr(lst, "plan_dp")


def test_listener_handle_message_counts_and_decodes():
    lst = _listener()
    raw = mp.encode_frame(KEY, {"cid": "node-9", "dps": {"30": True}}, seq=4, origin=7, protocol=4)
    lst.handle_message(f"smart/mb/in/{GW}", raw)
    lst.handle_message(f"smart/mb/in/{GW}", raw)
    assert lst.stats.received[GW] == 2
    assert lst.stats.decoded[GW] == 2
    assert lst.stats.samples[0] == {"gateway": GW, "protocol": 4, "cid": "node-9"}


def test_listener_unknown_gateway_and_bad_frame():
    lst = _listener()
    raw = mp.encode_frame(KEY, {"cid": "n", "dps": {}}, seq=1, origin=1, protocol=4)
    lst.handle_message("smart/mb/in/unknown", raw)  # unknown gw -> ignored entirely
    assert lst.stats.received == {} and lst.stats.decoded == {}
    lst.handle_message(f"smart/mb/in/{GW}", b"2.3" + bytes(60))  # received but undecodable
    assert lst.stats.received[GW] == 1 and lst.stats.decoded.get(GW, 0) == 0


def test_listener_samples_capped():
    lst = mc.CloudMqttListener(
        credentials=mc.MqttCredentials(host="h", client_id="c", username="u", password="p"),
        gateways={GW: mc.GatewayRef(dev_id=GW, local_key=KEY)},
        max_samples=2,
    )
    raw = mp.encode_frame(KEY, {"cid": "n", "dps": {}}, seq=1, origin=1, protocol=4)
    for _ in range(5):
        lst.handle_message(f"smart/mb/in/{GW}", raw)
    assert len(lst.stats.samples) == 2
    assert lst.stats.received[GW] == 5


def test_probe_stats_diagnostics_shape_no_secrets():
    lst = _listener()
    lst.stats.connack_rc = 0
    lst.stats.connack_text = "ok"
    raw = mp.encode_frame(KEY, {"cid": "node-9", "dps": {"30": True}}, seq=4, origin=7, protocol=4)
    lst.handle_message(f"smart/mb/in/{GW}", raw)
    d = lst.stats.as_diagnostics()
    assert d["connack_rc"] == 0
    assert d["total_received"] == 1 and d["total_decoded"] == 1
    assert d["received_per_gateway"] == {GW: 1}
    # no secret-ish keys present
    for k in ("sid", "ecode", "username", "password", "local_key", "localKey"):
        assert k not in d


class _FakePaho:
    """Minimal paho.mqtt.client.Client double: records calls, lets tests fire callbacks."""

    instances = []

    def __init__(self, client_id=None, clean_session=True, protocol=None):
        self.client_id = client_id
        self.on_connect = self.on_message = self.on_disconnect = None
        self.subscribed = []
        self.username = self.password = None
        self.tls = None
        self.loop_started = self.loop_stopped = self.disconnected = False
        self.published = []
        self.connected_to = None
        import types

        self._thread = types.SimpleNamespace(name=f"paho-mqtt-client-{client_id}")
        _FakePaho.instances.append(self)

    def username_pw_set(self, u, p):
        self.username, self.password = u, p

    def tls_set(self, **kw):
        self.tls = kw

    def connect_async(self, host, port, keepalive=60):
        self.connected_to = (host, port)

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True

    def subscribe(self, topic, qos=0):
        self.subscribed.append((topic, qos))

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))


def test_listener_start_subscribes_on_connack0_and_stop_closes(monkeypatch):
    import paho.mqtt.client as paho

    _FakePaho.instances.clear()
    monkeypatch.setattr(paho, "Client", _FakePaho)
    lst = _listener()
    lst.start(ca_certs="/dev/null")
    c = _FakePaho.instances[-1]
    assert c.connected_to == ("h", 8883) and c.loop_started and c.username == "u"
    assert c._thread.name == "danfoss-cloud-mqtt-probe"  # no client id leaks into logs
    # broker accepts -> subscribe to the gateway inbound topic
    c.on_connect(c, None, None, 0)
    assert lst.stats.connack_rc == 0
    assert c.subscribed == [(f"smart/mb/in/{GW}", 1)]
    # a message flows through handle_message
    raw = mp.encode_frame(KEY, {"cid": "n", "dps": {"30": True}}, seq=2, origin=3, protocol=4)
    c.on_message(c, None, type("M", (), {"topic": f"smart/mb/in/{GW}", "payload": raw}))
    assert lst.stats.decoded[GW] == 1
    lst.stop("done")
    assert c.loop_stopped and c.disconnected and lst.stats.stopped_reason == "done"


def test_listener_start_records_refused(monkeypatch):
    import paho.mqtt.client as paho

    _FakePaho.instances.clear()
    monkeypatch.setattr(paho, "Client", _FakePaho)
    lst = _listener()
    lst.start(ca_certs="/dev/null")
    c = _FakePaho.instances[-1]
    c.on_connect(c, None, None, 5)  # not authorised
    assert lst.stats.connack_rc == 5 and c.subscribed == []
    lst.stop()


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
