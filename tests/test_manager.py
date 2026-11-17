"""Local tunnel manager tests (threaded survey, networkless double)."""

import base64

import pytest

from custom_components.danfoss_ally_cloud.api import GatewayKey
from custom_components.danfoss_ally_cloud.api.local import tunnel
from custom_components.danfoss_ally_cloud.api.local.manager import Head, LocalTunnelManager


def _response_preheat(value_0025: int) -> bytes:
    payload = (
        (0x0012).to_bytes(2, "little")
        + bytes([0x00, 0x29])
        + (2100).to_bytes(2, "little", signed=True)
        + (0x0025).to_bytes(2, "little")
        + bytes([0x00, 0x30, value_0025])
    )
    return tunnel.header(tunnel.CLUSTER_THERMOSTAT) + bytes([0x00, 0x40, 0x01]) + payload


class _ReadFakeLink:
    def __init__(self, node_id: str, mode_0025: int) -> None:
        self.node_id = node_id
        self._resp = base64.b64encode(_response_preheat(mode_0025)).decode()
        self.closed = False

    def send(self, dev_id, node_id, frame):
        pass

    def receive(self):
        return (self.node_id, {"199": self._resp})

    def close(self):
        self.closed = True


def _gw():
    return {"gw1": GatewayKey(dev_id="gw1", name="A-0", local_key="cle-synth", ip="10.0.0.1")}


def test_survey_preheat():
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: _ReadFakeLink("node1", 0x03))
    res = mgr.survey_preheat([Head("dev1", "node1", "gw1")])
    assert res == {"dev1": True}


def test_survey_ignores_unknown_gateway():
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: _ReadFakeLink("node1", 0x03))
    res = mgr.survey_preheat([Head("devX", "nodeX", "gw-inconnue")])
    assert res == {}


def test_survey_unreachable_gateway_returns_none():
    def boom(g):
        raise RuntimeError("unreachable")

    mgr = LocalTunnelManager(_gw(), open_link=boom)
    res = mgr.survey_preheat([Head("dev1", "node1", "gw1")])
    assert res == {"dev1": None}


def test_gateway_ids():
    assert LocalTunnelManager(_gw()).gateway_ids == {"gw1"}


def test_survey_head_error_isolated(monkeypatch):
    """A head that raises during the read becomes None, without breaking the survey."""

    def boom(*a, **k):
        raise RuntimeError("flaky head")

    monkeypatch.setattr(tunnel, "read_preheat", boom)
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: _ReadFakeLink("node1", 0x03))
    res = mgr.survey_preheat([Head("dev1", "node1", "gw1")])
    assert res == {"dev1": None}


class _RWFakeLink:
    """Answers the 0x0025 read and the attribute write per the command sent."""

    def __init__(self, node_id: str, mode_0025: int) -> None:
        self.node_id = node_id
        self._mode = mode_0025
        self.closed = False
        self._cmd = None

    def send(self, dev_id, node_id, frame):
        self._cmd = frame[10]  # 0x00 = read attributes, 0x02 = write attributes

    def receive(self):
        if self._cmd == 0x02:
            resp = tunnel.header(tunnel.CLUSTER_THERMOSTAT) + bytes([0x00, 0x40, 0x04, 0x00])
        else:
            resp = _response_preheat(self._mode)
        return (self.node_id, {"199": base64.b64encode(resp).decode()})

    def close(self):
        self.closed = True


def test_write_preheat_ok():
    link = _RWFakeLink("node1", 0x01)  # schedule only -> we add preheat
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: link)
    assert mgr.write_preheat(Head("dev1", "node1", "gw1"), True) is True
    assert link.closed is True


def test_write_unknown_gateway():
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: None)
    with pytest.raises(tunnel.LocalUnavailable):
        mgr.write_preheat(Head("devX", "nodeX", "gw-inconnue"), True)


def test_write_unreadable_mode(monkeypatch):
    monkeypatch.setattr(tunnel, "read_programming_mode", lambda *a, **k: None)
    link = _RWFakeLink("node1", 0x01)
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: link)
    with pytest.raises(tunnel.LocalError):
        mgr.write_preheat(Head("dev1", "node1", "gw1"), True)
    assert link.closed is True  # closed even on failure (finally)
