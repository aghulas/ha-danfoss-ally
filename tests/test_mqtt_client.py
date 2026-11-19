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
