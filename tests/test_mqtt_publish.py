"""Tuya cloud MQTT 2.3 frame codec (prototype) - synthetic data only, no network."""

import json
import struct

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from custom_components.danfoss_ally_cloud.api import mqtt_publish as mp

KEY = "0123456789abcdef"  # synthetic 16-char localKey
GW = "bfsyntheticgw00000xyz"  # synthetic gateway devId
NONCE = bytes(range(12))


def test_header_layout():
    h = mp.header(3, 123456)
    assert h == b"2.3" + b"\x00\x00\x00\x03" + struct.pack(">I", 123456) + b"\x00"
    assert len(h) == mp.HEADER_LEN


def test_plaintext_is_fastjson_like():
    p = mp.plaintext({"cid": "abcd", "ctype": 0, "dps": {"30": True}}, 5, 1700000000)
    assert p == b'{"data":{"cid":"abcd","ctype":0,"dps":{"30":true}},"protocol":5,"t":1700000000}'


def test_encode_matches_independent_aesgcm():
    """Cross-check with another AES-GCM implementation (cryptography), AAD = 12-byte header."""
    data = mp.dp_publish_data("1a2b", {30: True})
    frame = mp.encode_frame(KEY, data, seq=3, origin=4242, t=1700000000, nonce=NONCE)
    hdr = mp.header(3, 4242)
    expected = (
        hdr + NONCE + AESGCM(KEY.encode()).encrypt(NONCE, mp.plaintext(data, 5, 1700000000), hdr)
    )
    assert frame == expected
    assert len(frame) == 12 + 12 + len(mp.plaintext(data, 5, 1700000000)) + 16


def test_roundtrip_and_fields():
    data = mp.dp_publish_data("1a2b", {"116": False, 133: "Horizontal"})
    frame = mp.encode_frame(KEY, data, seq=7, origin=999_999, t=1700000001)
    f = mp.decode_frame(KEY, frame)
    assert (f.pv, f.seq, f.origin, f.protocol) == ("2.3", 7, 999_999, 5)
    assert f.data == {"cid": "1a2b", "ctype": 0, "dps": {"116": False, "133": "Horizontal"}}
    assert f.body["t"] == 1700000001


def test_decode_frame_built_independently():
    """A frame produced by another implementation (as the gateway would) decodes."""
    body = {"data": {"cid": "1a2b", "dps": {"30": False}}, "protocol": 5, "t": 1}
    hdr = b"2.3" + struct.pack(">II", 11, 2000) + b"\x00"
    ct = AESGCM(KEY.encode()).encrypt(NONCE, json.dumps(body).encode(), hdr)
    f = mp.decode_frame(KEY, hdr + NONCE + ct)
    assert f.seq == 11 and f.origin == 2000 and f.data["dps"] == {"30": False}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b[:3] + b"\x00\x00\x00\x04" + b[7:],  # header is authenticated (AAD)
        lambda b: b[:-1] + bytes([b[-1] ^ 1]),  # tag
        lambda b: b[:30] + bytes([b[30] ^ 1]) + b[31:],  # ciphertext
    ],
)
def test_tamper_detected(mutate):
    frame = mp.encode_frame(KEY, {"x": 1}, seq=3, origin=1000, nonce=NONCE)
    with pytest.raises(mp.FrameError):
        mp.decode_frame(KEY, mutate(frame))


def test_wrong_key_does_not_leak_key():
    frame = mp.encode_frame(KEY, {"x": 1}, seq=3, origin=1000)
    with pytest.raises(mp.FrameError) as e:
        mp.decode_frame("fedcba9876543210", frame)
    assert KEY not in str(e.value) and "fedcba" not in str(e.value)


def test_rejects_bad_inputs():
    with pytest.raises(mp.FrameError):
        mp.decode_frame(KEY, b"2.3short")
    with pytest.raises(mp.FrameError):
        mp.decode_frame(KEY, b"2.2" + bytes(60))
    with pytest.raises(mp.FrameError):
        mp.encode_frame("short", {}, seq=3, origin=1000)
    with pytest.raises(mp.FrameError):
        mp.header(3, 1000, pv="2.2")
    with pytest.raises(ValueError):
        mp.dp_publish_data("", {"30": True})
    with pytest.raises(ValueError):
        mp.dp_publish_data("1a2b", {})


def test_seq_origin_like_sando():
    c = mp.SeqOrigin(origin=5000)
    assert c.next() == (3, 5000)
    assert c.next() == (4, 5000)
    assert 1000 <= mp.SeqOrigin().origin < 1_001_000


def test_build_dp_publish_targets_gateway_topic():
    c = mp.SeqOrigin(origin=1234)
    plan = mp.build_dp_publish(
        gateway_id=GW, gateway_pv="2.3", local_key=KEY, node_id="1a2b", dps={"30": True}, counter=c
    )
    assert plan.topic == "smart/mb/out/" + GW
    assert (plan.qos, plan.retain, plan.seq, plan.origin) == (1, False, 3, 1234)
    f = mp.decode_frame(KEY, plan.payload)
    assert f.data == {"cid": "1a2b", "ctype": 0, "dps": {"30": True}}
    assert mp.topic_in(GW) == "smart/mb/in/" + GW


def test_build_dp_publish_refuses_other_pv():
    with pytest.raises(mp.FrameError):
        mp.build_dp_publish(
            gateway_id=GW,
            gateway_pv="2.2",
            local_key=KEY,
            node_id="1a2b",
            dps={"30": True},
            counter=mp.SeqOrigin(),
        )


def test_credentials_shapes_synthetic():
    cid = mp.mqtt_client_id("com.example.app", "dev123", "uid1")
    assert cid.startswith("com.example.app_mb_dev123_") and cid.endswith("_DEFAULT")
    assert len(cid.split("_")[3]) == 32  # md5 hex
    user = mp.mqtt_username("p100", "appid", "abcd1234", "SID", "ECODE")
    assert (
        user.startswith("p100_v1_appid_abcd1234_mb_SID")
        and len(user) == len("p100_v1_appid_abcd1234_mb_SID") + 16
    )
    assert mp.mqtt_password("0" * 24 + "X" * 16 + "0" * 24) == "X" * 16
    with pytest.raises(ValueError):
        mp.mqtt_password("")
    assert mp.user_topic("p100", "uid1") == "p100/mb/uid1"
