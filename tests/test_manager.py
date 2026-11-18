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


def test_descale_ok(monkeypatch):
    """descale opens a link, writes 0x4010/0x4011 and closes (status 0 -> True)."""
    monkeypatch.setattr(tunnel, "write_descale", lambda link, d, n, day, hour: 0)
    state = {}

    class _L:
        def close(self):
            state["closed"] = True

    mgr = LocalTunnelManager(_gw(), open_link=lambda g: _L())
    assert mgr.descale(Head("dev1", "node1", "gw1"), "wednesday", "13:00") is True
    assert state["closed"] is True


def test_descale_unknown_gateway():
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: None)
    with pytest.raises(tunnel.LocalUnavailable):
        mgr.descale(Head("devX", "nodeX", "gw-inconnue"), "monday", "08:00")


def test_set_override_ok(monkeypatch):
    monkeypatch.setattr(tunnel, "write_setpoint", lambda link, d, n, celsius: int(celsius * 100))
    state = {}

    class _L:
        def close(self):
            state["closed"] = True

    mgr = LocalTunnelManager(_gw(), open_link=lambda g: _L())
    assert mgr.set_override(Head("dev1", "node1", "gw1"), 20.0) == 2000
    assert state["closed"] is True


def test_read_schedule_passthrough(monkeypatch):
    sched = {"monday": [{"h": "06:00", "c": 21.0}]}
    monkeypatch.setattr(tunnel, "read_schedule", lambda link, d, n: sched)
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: _ReadFakeLink("node1", 0x03))
    assert mgr.read_schedule(Head("dev1", "node1", "gw1")) == sched


def test_set_override_unknown_gateway():
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: None)
    with pytest.raises(tunnel.LocalUnavailable):
        mgr.set_override(Head("x", "y", "gw-inconnue"), 20.0)


def test_write_window_detection_ok(monkeypatch):
    monkeypatch.setattr(
        tunnel, "write_setting_dp", lambda link, d, n, setting, value: (setting, value)
    )
    state = {}

    class _L:
        def close(self):
            state["closed"] = True

    mgr = LocalTunnelManager(_gw(), open_link=lambda g: _L())
    assert mgr.write_window_detection(Head("dev1", "node1", "gw1"), True) == (
        "window_detection",
        True,
    )
    assert state["closed"] is True


def test_write_window_detection_unknown_gateway():
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: None)
    with pytest.raises(tunnel.LocalUnavailable):
        mgr.write_window_detection(Head("x", "y", "gw-inconnue"), False)


def test_survey_heads_summarizes(monkeypatch):
    """survey_heads runs the tunnel survey and summarizes each head (read-only)."""
    raw = {
        "dev1": {"attributes": {"current_setpoint": 21.0}, "schedule": {}},
        "dev2": {"attributes": {}, "unreachable": True},
    }
    monkeypatch.setattr(tunnel, "survey", lambda gateways, heads: raw)
    monkeypatch.setattr(tunnel, "summarize_head", lambda e: {"ok": bool(e.get("attributes"))})
    mgr = LocalTunnelManager(_gw())
    res = mgr.survey_heads([Head("dev1", "n1", "gw1"), Head("dev2", "n2", "gw1")])
    assert res == {"dev1": {"ok": True}, "dev2": {"ok": False}}


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
