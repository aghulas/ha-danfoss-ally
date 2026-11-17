"""Additional local tunnel tests: remaining branches + LocalLink (fake tinytuya)."""

import base64
import sys

import pytest

from custom_components.danfoss_ally_cloud.api.keys import GatewayKey
from custom_components.danfoss_ally_cloud.api.local import tunnel

# --- trames : branches manufacturer et programme -------------------------------------------------


def test_frame_read_attributes_manufacturer():
    t = tunnel.frame_read_attributes([0x0012], manufacturer=True, seq=0x40)
    z = t[8:]
    assert z[0] & 0x04  # bit manufacturer
    assert int.from_bytes(z[1:3], "little") == tunnel.MANUFACTURER


def test_frame_write_attributes_manufacturer():
    t = tunnel.frame_write_attributes([(0x0025, 0x30, 3)], manufacturer=True)
    z = t[8:]
    assert z[0] & 0x04 and int.from_bytes(z[1:3], "little") == tunnel.MANUFACTURER


def test_frame_read_schedule():
    t = tunnel.frame_read_schedule("thursday")
    assert t[8:] == bytes([0x01, 0x40, 0x02, tunnel.DAY_BIT["thursday"], 0x01])


def test_frame_write_schedule():
    t = tunnel.frame_write_schedule(
        "monday", [{"h": "00:00", "c": 17.0}, {"h": "06:30", "c": 21.0}]
    )
    z = t[8:]
    assert z[:3] == bytes([0x01, 0x40, 0x01])
    assert z[3] == 2 and z[4] == tunnel.DAY_BIT["monday"]  # 2 transitions, bit du jour


# --- minutes / check_transitions : chemins d'erreur ----------------------------------------


def test_minutes_valide():
    assert tunnel.minutes("06:30") == 390
    assert tunnel.minutes("24:00") == 1440


@pytest.mark.parametrize("h", ["bananes", "6h30", "25:00", "00:70"])
def test_minutes_invalide(h):
    with pytest.raises(tunnel.LocalError):
        tunnel.minutes(h)


def test_verifier_transitions_trop_nombreuses():
    tr = [{"h": f"{i:02d}:00", "c": 20.0} for i in range(7)]
    with pytest.raises(tunnel.LocalError):
        tunnel.check_transitions(tr)


def test_verifier_transitions_desordre():
    with pytest.raises(tunnel.LocalError):
        tunnel.check_transitions([{"h": "00:00", "c": 18.0}, {"h": "00:00", "c": 21.0}])


# --- decoders: remaining branches ------------------------------------------------------------


def test_decoder_trame_fabricant():
    # fc avec bit manufacturer (0x04) : z = [fc, fab_lo, fab_hi, seq, cmd, ...payload]
    z = bytes([0x04]) + tunnel.MANUFACTURER.to_bytes(2, "little") + bytes([0x40, 0x01, 0xAA])
    brut = tunnel.header(tunnel.CLUSTER_THERMOSTAT) + z
    f = tunnel.decode_frame(brut)
    assert f["manufacturer"] == tunnel.MANUFACTURER
    assert f["command"] == 0x01
    assert f["payload"] == b"\xaa"


def test_decode_attributes_nonzero_status_and_cutoff():
    # 0x0012 status!=0 -> None; then truncated attribute -> stop.
    payload = (0x0012).to_bytes(2, "little") + bytes([0x02])  # statut 0x02
    payload += (0x0015).to_bytes(2, "little") + bytes(
        [0x00, 0x29, 0x10]
    )  # type 0x29 = 2 B, truncated
    out = tunnel.decode_attributes(payload)
    assert out[0x0012] is None
    assert 0x0015 not in out  # coupure sur longueur insuffisante


def test_decode_schedule_cutoff():
    # n=2 announced but only one complete transition -> break.
    payload = bytes([2, tunnel.DAY_BIT["tuesday"], 0x01])
    payload += (0).to_bytes(2, "little") + (2100).to_bytes(2, "little", signed=True)
    payload += (360).to_bytes(2, "little")  # 2nd incomplete transition
    _, tr = tunnel.decode_schedule(payload)
    assert len(tr) == 1


def test_name_other_attribute():
    # 0x0030 (source_consigne) : branche else, value brute.
    out = tunnel.name_attributes({0x0030: 2}, tunnel.ATTRS_STD)
    assert out["setpoint_source"] == 2


def test_comfort_slots_empty():
    assert tunnel.comfort_slots(None) == []
    assert tunnel.comfort_slots([]) == []


# --- request / read_day / read_schedule / writes (doubles) -----------------------------------


class _FakeLienJour:
    """Answers the requested day by reading the bit in the sent frame (offset 11)."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self._bit = None

    def send(self, dev_id, node_id, frame):
        self._bit = frame[11]

    def receive(self):
        corps = (
            bytes([1, self._bit, 0x01])
            + (0).to_bytes(2, "little")
            + (2100).to_bytes(2, "little", signed=True)
        )
        z = bytes([0x01, 0x40, 0x00]) + corps  # specifique, cmd 0x00
        resp = tunnel.header(tunnel.CLUSTER_THERMOSTAT) + z
        return (self.node_id, {"199": base64.b64encode(resp).decode()})


def test_read_day():
    link = _FakeLienJour("node-1")
    tr = tunnel.read_day(link, "dev-1", "node-1", "tuesday", duration=1, attempts=1)
    assert tr == [{"h": "00:00", "c": 21.0}]


def test_read_schedule_seven_days():
    link = _FakeLienJour("node-1")
    prog = tunnel.read_schedule(link, "dev-1", "node-1")
    assert set(prog) == set(tunnel.WEEKDAYS)
    assert prog["sunday"] == [{"h": "00:00", "c": 21.0}]


def test_read_programming_mode():
    response = tunnel.header(tunnel.CLUSTER_THERMOSTAT) + bytes([0x00, 0x40, 0x01])
    response += (
        (0x0012).to_bytes(2, "little")
        + bytes([0x00, 0x29])
        + (2100).to_bytes(2, "little", signed=True)
    )
    response += (0x0025).to_bytes(2, "little") + bytes([0x00, 0x30, 0x03])

    class _L:
        def send(self, *a):
            pass

        def receive(self):
            return ("node-1", {"199": base64.b64encode(response).decode()})

    assert tunnel.read_programming_mode(_L(), "dev-1", "node-1", duration=1, attempts=1) == 3


def test_demander_base64_invalide_rend_none():
    class _L:
        def send(self, *a):
            pass

        def receive(self):
            return ("node-1", {"199": "!!!pas du base64!!!"})

    out = tunnel.request(_L(), "dev-1", "node-1", b"x", lambda f: 1, duration=1, attempts=1)
    assert out is None


def test_read_attributes_rejects_specific_frame():
    # "specific" response (schedule) where attributes are expected -> accept returns None.
    corps = (
        bytes([1, tunnel.DAY_BIT["monday"], 0x01])
        + (0).to_bytes(2, "little")
        + (2100).to_bytes(2, "little", signed=True)
    )
    resp = tunnel.header(tunnel.CLUSTER_THERMOSTAT) + bytes([0x01, 0x40, 0x00]) + corps

    class _L:
        def send(self, *a):
            pass

        def receive(self):
            return ("node-1", {"199": base64.b64encode(resp).decode()})

    assert tunnel.read_preheat(_L(), "dev-1", "node-1", duration=1, attempts=1) is None


def test_write_preheat():
    response = tunnel.header(tunnel.CLUSTER_THERMOSTAT) + bytes([0x00, 0x40, 0x04, 0x00])

    class _L:
        def __init__(self):
            self.sent = []

        def send(self, dev, node, frame):
            self.sent.append(frame)

        def receive(self):
            return ("node-1", {"199": base64.b64encode(response).decode()})

    link = _L()
    assert tunnel.write_preheat(link, "dev-1", "node-1", True, 0x01) == 0
    assert link.sent
    # The frame writes 0x0025 as bitmap8 (ZCL type 0x18, not 0x30 enum8), schedule bit preserved:
    # 0x01 (schedule only) | 0x02 (preheat) = 0x03.
    enreg = tunnel.header(tunnel.CLUSTER_THERMOSTAT) + bytes([0x00, 0x40, 0x02])
    enreg += (0x0025).to_bytes(2, "little") + bytes([0x18, 0x03])
    assert link.sent[-1] == enreg


# --- LocalLink (fake tinytuya injected into sys.modules) --------------------------------------


class _FakeDevice:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.values: dict = {}

    def set_socketTimeout(self, t):
        self.timeout = t

    def set_value(self, dp, val, nowait=False):
        self.values[dp] = val

    def heartbeat(self, nowait=False):
        pass

    def receive(self):
        return {"cid": "node-1", "dps": {"199": "payload"}}

    def close(self):
        self.closed = True


class _FakeTinytuya:
    Device = _FakeDevice


@pytest.fixture
def faux_tinytuya(monkeypatch):
    monkeypatch.setitem(sys.modules, "tinytuya", _FakeTinytuya)
    return _FakeTinytuya


def test_locallink_without_ip_raises():
    with pytest.raises(tunnel.LocalUnavailable):
        tunnel.LocalLink(GatewayKey("gw-1", "GW", "lk", ip=None))


def test_locallink_cycle(faux_tinytuya):
    link = tunnel.LocalLink(GatewayKey("gw-1", "GW", "lk", ip="10.0.0.9"))
    link.send("dev-1", "node-1", b"\x01\x02")
    recu = link.receive()
    assert recu == ("node-1", {"199": "payload"})
    link.close()
