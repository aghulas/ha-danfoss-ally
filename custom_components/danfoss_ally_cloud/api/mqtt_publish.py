"""Tuya cloud MQTT DP publish (protocol 2.3) - PROTOTYPE, codec only, no network.

Why: the Danfoss app writes an isolated head's settings (DP 1, 30, 116, 133, 101, 18, 27,
118+16, 119, 120) with ``AbsThingDevice.publishDps`` -> MQTT publish on
``smart/mb/out/<gateway devId>``; ``tuya.m.custom.wkf.settings.change`` is NOT that path (W-3,
capture 2026-11-19). This module reproduces the frame the app builds, from the decompiled Thing
SDK of the Danfoss app (classes4/5/9.dex; class names are obfuscated, the "compiled from"
names are given):

- ``MqttControl2_3`` (qpbpqpq) / ``PublishMapper`` (qqddbpb) / ``AesGcmUtil``: encoder.
- ``MsgProtocol2_3`` (qbpppdb): decoder of ``smart/mb/in/<gw>`` (same layout).
- ``dddbppd`` + ``dqdpbbd.sendCommand``: DP publish = protocol 5, data ``{cid, ctype, dps}``.
- ``SandO``: per-device (sequence, origin) counter.
- ``SdkMqttCertificationInfo`` (dqqbdqb): broker username/password (see docs/cloud-mqtt-publish.md).

Frame 2.3 (bytes)::

    header  = b"2.3" | seq (uint32 BE) | origin (uint32 BE) | 0x00  (12 bytes = GCM AAD)
    body    = nonce (12 random bytes) | AES-GCM ciphertext | tag (16 bytes)
    key     = gateway localKey, as ASCII bytes (16 chars -> AES-128)
    plaintext = JSON {"data": <data>, "protocol": <int>, "t": <epoch seconds>}  (compact)

Nothing here opens a connection or sends anything: callers get a topic and a payload. Sending it
to a real gateway is a WRITE on a real head and is out of scope until Rémi gives the go-ahead
(see the design note). SECRETS: the localKey and the session material are never logged nor put
in a repr.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import struct
import time
from dataclasses import dataclass, field
from typing import Any

from Crypto.Cipher import AES

PV_2_3 = "2.3"
HEADER_LEN = 12
NONCE_LEN = 12
TAG_LEN = 16

# Thing SDK protocol numbers (dddbppd): 5 = DP publish (the one we need), 22 = DP publish variant
# used by another builder, 31 = DP query, 63 = sub-device add/cancel, 200/51 = config.
PROTOCOL_DP_PUBLISH = 5

TOPIC_OUT = "smart/mb/out/"  # app -> gateway (MqttConfig.downTopicSuffix)
TOPIC_IN = "smart/mb/in/"  # gateway -> app (MqttConfig.upTopicSuffix)

BROKER_PORT = 8883  # TLS ("ssl://" + mobileMqttsUrl + ":8883")
DEFAULT_TAG = "DEFAULT"  # MQTT server instance tag (dppdpbd.pppbppp)
CLIENT_ID_SALT = "sdkfasodifca"  # qdpppbq.initMqttConfig


class FrameError(ValueError):
    """Malformed, unsupported or undecryptable 2.3 frame."""


def topic_out(gateway_id: str) -> str:
    """Topic the app publishes a sub-device command to: its GATEWAY's devId, not the head's."""
    if not gateway_id:
        raise ValueError("gateway devId required")
    return TOPIC_OUT + gateway_id


def topic_in(gateway_id: str) -> str:
    """Topic the gateway answers / reports on (the app subscribes before publishing)."""
    if not gateway_id:
        raise ValueError("gateway devId required")
    return TOPIC_IN + gateway_id


def _key(local_key: str) -> bytes:
    k = local_key.encode("utf-8")
    if len(k) not in (16, 24, 32):
        # Real gateway localKeys are 16 ASCII chars. Do not echo the key in the message.
        raise FrameError(f"localKey must be 16/24/32 bytes, got {len(k)}")
    return k


def header(seq: int, origin: int, pv: str = PV_2_3) -> bytes:
    """12-byte header, also the AES-GCM additional authenticated data."""
    if pv != PV_2_3:
        raise FrameError(f"unsupported pv {pv!r} (only 2.3)")
    return pv.encode("ascii") + struct.pack(">II", seq & 0xFFFFFFFF, origin & 0xFFFFFFFF) + b"\x00"


def plaintext(data: Any, protocol: int = PROTOCOL_DP_PUBLISH, t: int | None = None) -> bytes:
    """PublishBean2_3 as fastjson writes it: fields in alphabetical order, compact."""
    body = {"data": data, "protocol": protocol, "t": int(time.time()) if t is None else t}
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def encode_frame(
    local_key: str,
    data: Any,
    *,
    seq: int,
    origin: int,
    protocol: int = PROTOCOL_DP_PUBLISH,
    t: int | None = None,
    nonce: bytes | None = None,
) -> bytes:
    """Build a 2.3 frame (MqttControl2_3). ``nonce`` only for deterministic tests."""
    hdr = header(seq, origin)
    nonce = os.urandom(NONCE_LEN) if nonce is None else nonce
    if len(nonce) != NONCE_LEN:
        raise FrameError("nonce must be 12 bytes")
    cipher = AES.new(_key(local_key), AES.MODE_GCM, nonce=nonce, mac_len=TAG_LEN)
    cipher.update(hdr)
    ct, tag = cipher.encrypt_and_digest(plaintext(data, protocol, t))
    return hdr + nonce + ct + tag


@dataclass(frozen=True)
class Frame:
    """Decoded 2.3 frame. ``body`` = {"data", "protocol", "t"}."""

    pv: str
    seq: int
    origin: int
    body: dict[str, Any]

    @property
    def protocol(self) -> int | None:
        return self.body.get("protocol")

    @property
    def data(self) -> Any:
        return self.body.get("data")


def decode_frame(local_key: str, frame: bytes) -> Frame:
    """Decode and authenticate a 2.3 frame (MsgProtocol2_3). Raises FrameError."""
    if len(frame) < HEADER_LEN + NONCE_LEN + TAG_LEN:
        raise FrameError("frame too short")
    hdr = frame[:HEADER_LEN]
    pv = hdr[:3].decode("ascii", "replace")
    if pv != PV_2_3:
        raise FrameError(f"unsupported pv {pv!r} (only 2.3)")
    seq, origin = struct.unpack(">II", hdr[3:11])
    nonce = frame[HEADER_LEN : HEADER_LEN + NONCE_LEN]
    ct, tag = frame[HEADER_LEN + NONCE_LEN : -TAG_LEN], frame[-TAG_LEN:]
    cipher = AES.new(_key(local_key), AES.MODE_GCM, nonce=nonce, mac_len=TAG_LEN)
    cipher.update(hdr)
    try:
        raw = cipher.decrypt_and_verify(ct, tag)
    except ValueError as e:  # wrong key, wrong AAD or tampered frame
        raise FrameError("authentication failed (wrong localKey or corrupted frame)") from e
    try:
        body = json.loads(raw)
    except ValueError as e:
        raise FrameError("decrypted payload is not JSON") from e
    if not isinstance(body, dict):
        raise FrameError("decrypted payload is not a JSON object")
    return Frame(pv=pv, seq=seq, origin=origin, body=body)


@dataclass
class SeqOrigin:
    """SandO: ``origin`` random per client session, ``seq`` starts at 2 and is bumped BEFORE each
    publish (first frame carries 3). The receiver drops a repeated (seq, origin)
    ("cloud command repeat"), so keep one instance per gateway for the whole MQTT session."""

    origin: int = field(default_factory=lambda: random.randint(1000, 1_000_999))  # noqa: S311
    seq: int = 2

    def next(self) -> tuple[int, int]:
        self.seq += 1
        return self.seq, self.origin


def dp_publish_data(node_id: str, dps: dict[str | int, Any], ctype: int = 0) -> dict[str, Any]:
    """``data`` of a DP publish addressed to a Zigbee sub-device (dqdpbbd.bdpdqbp):
    ``cid`` = the head's node id (Zigbee short id, DanfossDevice.node_id), ``ctype`` 0."""
    if not node_id:
        raise ValueError("node_id (cid) required: the topic is the gateway's")
    if not dps:
        raise ValueError("no DP to publish")
    return {"cid": node_id, "ctype": ctype, "dps": {str(k): v for k, v in dps.items()}}


@dataclass(frozen=True)
class PublishPlan:
    """What would be sent: MQTT topic, payload bytes, QoS 1, not retained."""

    topic: str
    payload: bytes
    seq: int
    origin: int
    qos: int = 1
    retain: bool = False


def build_dp_publish(
    *,
    gateway_id: str,
    gateway_pv: str,
    local_key: str,
    node_id: str,
    dps: dict[str | int, Any],
    counter: SeqOrigin,
    t: int | None = None,
) -> PublishPlan:
    """Plan the publish the app does for ``publishDps`` on a head behind ``gateway_id``.

    Pure: sends nothing. ``gateway_pv`` is the gateway's ``pv`` from the device list; only 2.3 is
    implemented (2.2 = AES-ECB, another layout) so anything else is refused, not guessed.
    """
    if gateway_pv != PV_2_3:
        raise FrameError(f"gateway pv {gateway_pv!r} not supported (only 2.3)")
    seq, origin = counter.next()
    payload = encode_frame(local_key, dp_publish_data(node_id, dps), seq=seq, origin=origin, t=t)
    return PublishPlan(topic=topic_out(gateway_id), payload=payload, seq=seq, origin=origin)


# --- Broker credentials (SdkMqttCertificationInfo, appTag "os", ThingSmartNetWork.mSdk = true) ---


def _md5_hex(s: str) -> str:
    # MD5Util.md5AsBase64 is misnamed: it returns the lowercase MD5 HEX digest.
    return hashlib.md5(s.encode("utf-8")).hexdigest()  # noqa: S324 - protocol, not security


def mqtt_client_id(package: str, device_id: str, uid: str, tag: str = DEFAULT_TAG) -> str:
    """``<package>_mb_<deviceId>_<md5hex(uid + salt)>_<tag>`` (qdpppbq.initMqttConfig).

    ⚠ Same deviceId as the app => same clientId => the broker kicks the other client. A distinct
    deviceId (derive_distinct_device_id) is advised, as for the HTTP session conflict."""
    return f"{package}_mb_{device_id}_{_md5_hex(uid + CLIENT_ID_SALT)}_{tag}"


def mqtt_username(partner_identity: str, app_id: str, ch_key: str, sid: str, ecode: str) -> str:
    """``<partnerIdentity>_v1_<appId>_<chKey>_mb_<sid><last16(md5hex(md5hex(appId) + ecode))>``.

    ``chKey`` = ThingNetworkSecurity.getChKey(ctx, appId) - the SAME call that fills the HTTP
    ``chKey`` parameter, i.e. the installation chKey the integration already has. ``app_id`` =
    ThingSmartNetWork.mAppId (the HTTP ``clientId``). Secret: never log the result."""
    tail = _md5_hex(_md5_hex(app_id) + ecode)[-16:]
    return f"{partner_identity}_v1_{app_id}_{ch_key}_mb_{sid}{tail}"


def mqtt_password(native_cmd2_output: str) -> str:
    """Middle 16 chars of ``doCommandNative(ctx, 2, ecode, null, mD=false)``.

    Command 2 of libthing_security is NOT reverse-engineered yet: the caller must supply its
    output (frida oracle on a synthetic ecode, then a static formula; see the design note)."""
    if not native_cmd2_output or len(native_cmd2_output) < 16:
        raise ValueError("doCommandNative cmd=2 output required (not reproduced yet)")
    half = len(native_cmd2_output) >> 1
    return native_cmd2_output[half - 8 : half + 8]


def user_topic(partner_identity: str, uid: str) -> str:
    """Per-user topic the app subscribes to (``<partnerIdentity>/mb/<uid>``)."""
    return f"{partner_identity}/mb/{uid}"
