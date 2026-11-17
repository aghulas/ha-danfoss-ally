"""Local tunnel tests (pure functions + link double, synthetic data)."""

import base64

import pytest

from custom_components.danfoss_ally_cloud.api.local import tunnel


def _response_attribute(attr: int, typ: int, value: bytes) -> bytes:
    """DP 199 "read attributes response" frame (non-manufacturer, cmd 0x01)."""
    payload = attr.to_bytes(2, "little") + bytes([0x00, typ]) + value
    z = bytes([0x00, 0x40, 0x01]) + payload  # fc=0, seq, cmd=0x01
    return tunnel.header(tunnel.CLUSTER_THERMOSTAT) + z


def _response_multi(records: list[tuple[int, int, bytes]]) -> bytes:
    """Multi-attribute read-attributes response (records = [(attr, type, value)])."""
    payload = b"".join(a.to_bytes(2, "little") + bytes([0x00, t]) + v for a, t, v in records)
    return tunnel.header(tunnel.CLUSTER_THERMOSTAT) + bytes([0x00, 0x40, 0x01]) + payload


# Realistic response: 1st requested attribute (0x0012, sentinel) + 0x0025 preheat.
def _response_preheat(value_0025: int) -> bytes:
    return _response_multi(
        [
            (0x0012, 0x29, (2100).to_bytes(2, "little", signed=True)),
            (0x0025, 0x30, bytes([value_0025])),
        ]
    )


class _FakeLien:
    def __init__(self, node_id: str, response: bytes) -> None:
        self.node_id = node_id
        self._resp = base64.b64encode(response).decode()
        self.sent: list[bytes] = []

    def send(self, dev_id, node_id, frame):
        self.sent.append(frame)

    def receive(self):
        return (self.node_id, {"199": self._resp})


def test_header():
    assert tunnel.header(0x0201) == bytes.fromhex("4001") + b"\x01\x02" + bytes.fromhex("04010100")


def test_decoder_trame_reponse_attribut():
    brut = _response_attribute(0x0025, 0x30, bytes([0x03]))
    f = tunnel.decode_frame(brut)
    assert f is not None
    assert f["cluster"] == tunnel.CLUSTER_THERMOSTAT
    assert f["command"] == 0x01
    assert f["manufacturer"] is None
    assert f["specific"] is False


def test_decoder_trame_rejette_non_trame():
    assert tunnel.decode_frame(b"\x00\x01\x02") is None


def test_decode_attributes_and_name_preheat():
    # 0x0025 = 3 -> schedule + preheat (bit 1).
    f = tunnel.decode_frame(_response_attribute(0x0025, 0x30, bytes([0x03])))
    vals = tunnel.decode_attributes(f["payload"])
    assert vals[0x0025] == 3
    nomme = tunnel.name_attributes(vals, tunnel.ATTRS_STD)
    assert nomme["programming_mode"] == 3
    assert nomme["preheat"] is True


def test_name_attributes_without_preheat():
    f = tunnel.decode_frame(_response_attribute(0x0025, 0x30, bytes([0x01])))
    nomme = tunnel.name_attributes(tunnel.decode_attributes(f["payload"]), tunnel.ATTRS_STD)
    assert nomme["preheat"] is False


def test_read_preheat_via_double():
    link = _FakeLien("node-xyz", _response_preheat(0x03))
    assert tunnel.read_preheat(link, "dev-1", "node-xyz", duration=1) is True
    assert link.sent  # a frame was indeed sent


def test_read_preheat_wrong_node_returns_none():
    link = _FakeLien("autre-node", _response_preheat(0x03))
    assert tunnel.read_preheat(link, "dev-1", "node-xyz", duration=1, attempts=1) is None


def test_decoder_programme():
    payload = (
        bytes([1, tunnel.DAY_BIT["wednesday"], 0x01])
        + (0).to_bytes(2, "little")
        + (2100).to_bytes(2, "little", signed=True)
    )
    bit, tr = tunnel.decode_schedule(payload)
    assert bit == tunnel.DAY_BIT["wednesday"]
    assert tr == [{"h": "00:00", "c": 21.0}]


def test_verifier_transitions_valide():
    tr = tunnel.check_transitions([{"h": "00:00", "c": 17.0}, {"h": "06:30", "c": 21.0}])
    assert tr[1]["h"] == "06:30"


def test_check_transitions_reject_first_not_midnight():
    with pytest.raises(tunnel.LocalError):
        tunnel.check_transitions([{"h": "06:00", "c": 21.0}])


def test_check_transitions_reject_setpoint_out_of_range():
    with pytest.raises(tunnel.LocalError):
        tunnel.check_transitions([{"h": "00:00", "c": 40.0}])


def test_frame_write_attributes_unknown_type():
    with pytest.raises(tunnel.LocalError):
        tunnel.frame_write_attributes([(0x0025, 0xFF, 1)], manufacturer=False)


def test_comfort_slots():
    tr = [{"h": "00:00", "c": 17.0}, {"h": "06:00", "c": 21.0}, {"h": "22:00", "c": 17.0}]
    assert tunnel.comfort_slots(tr) == [{"start": "06:00", "end": "22:00", "setpoint": 21.0}]


def test_nouveau_mode_prechauffage():
    assert tunnel.new_preheat_mode(0x01, True) == 0x03  # schedule -> + preheat
    assert tunnel.new_preheat_mode(0x03, False) == 0x01  # removes preheat
    assert tunnel.new_preheat_mode(0x03, True) == 0x03  # already active
    assert tunnel.new_preheat_mode(0x01, False) == 0x01  # already inactive


def test_write_attributes_via_double():
    # "write attributes response" (cmd 0x04, status 0 = accepted).
    response = tunnel.header(tunnel.CLUSTER_THERMOSTAT) + bytes([0x00, 0x40, 0x04, 0x00])
    link = _FakeLien("node-xyz", response)
    statut = tunnel.write_attributes(
        link, "dev-1", "node-xyz", [(0x0025, 0x30, 3)], manufacturer=False
    )
    assert statut == 0
