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

    monkeypatch.setattr(tunnel, "read_standard", boom)
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


def test_read_preheat_one_head(monkeypatch):
    calls = []

    def fake_read(link, dev_id, node_id, **kw):
        calls.append((dev_id, node_id))
        return {"preheat": True, "programming_mode": 3}

    monkeypatch.setattr(tunnel, "read_standard", fake_read)
    link = _RWFakeLink("node1", 0x03)
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: link)
    assert mgr.read_preheat(Head("dev1", "node1", "gw1")) is True
    assert calls == [("dev1", "node1")]
    assert link.closed is True


def test_read_preheat_unknown_gateway():
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: None)
    with pytest.raises(tunnel.LocalUnavailable):
        mgr.read_preheat(Head("devX", "nodeX", "gw-inconnue"))


class _GatedLink(_ReadFakeLink):
    """A link whose answers are released by the test, head by head (a slow gateway)."""

    def __init__(self, mode_0025: int, gates: dict) -> None:
        super().__init__("", mode_0025)
        self._gates = gates
        self._current = ""

    def send(self, dev_id, node_id, frame):
        self._current = node_id

    def receive(self):
        if not self._gates[self._current].wait(0.01):
            return None
        return (self._current, {"199": self._resp})


def test_survey_preheat_reports_each_head_as_read():
    import threading

    gates = {"node1": threading.Event(), "node2": threading.Event()}
    link = _GatedLink(0x03, gates)
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: link)
    seen: list = []
    first = threading.Event()

    def on_result(dev_id, value):
        seen.append((dev_id, value))
        first.set()

    out: dict = {}
    heads = [Head("dev1", "node1", "gw1"), Head("dev2", "node2", "gw1")]
    t = threading.Thread(target=lambda: out.update(mgr.survey_preheat(heads, on_result)))
    t.start()
    gates["node1"].set()
    assert first.wait(3)
    assert seen == [("dev1", True)] and t.is_alive()  # known before the survey is over
    gates["node2"].set()
    t.join(3)
    assert out == {"dev1": True, "dev2": True}
    assert seen == [("dev1", True), ("dev2", True)]
    assert link.closed is True


def test_survey_preheat_stops_on_request():
    import threading
    import time

    gates = {"node1": threading.Event(), "node2": threading.Event()}
    link = _GatedLink(0x03, gates)
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: link)
    stop = threading.Event()
    seen: list = []
    out: dict = {}
    heads = [Head("dev1", "node1", "gw1"), Head("dev2", "node2", "gw1")]
    t = threading.Thread(target=lambda: out.update(mgr.survey_preheat(heads, seen.append, stop)))
    t.start()
    time.sleep(0.05)
    t0 = time.monotonic()
    stop.set()
    t.join(3)
    assert not t.is_alive() and time.monotonic() - t0 < 2  # returns at once, not after the heads
    assert out == {} and seen == []
    gates["node1"].set()  # the worker finishes the head it was on, reports nothing, reads no other
    deadline = time.monotonic() + 3
    while not link.closed and time.monotonic() < deadline:
        time.sleep(0.01)
    assert link.closed is True and out == {} and seen == []


def test_survey_preheat_listener_error_does_not_break_the_survey():
    def boom(dev_id, value):
        raise RuntimeError("listener ko")

    mgr = LocalTunnelManager(_gw(), open_link=lambda g: _ReadFakeLink("node1", 0x03))
    assert mgr.survey_preheat([Head("dev1", "node1", "gw1")], boom) == {"dev1": True}


def test_survey_preheat_unreachable_gateway_reports_none():
    def boom(g):
        raise RuntimeError("unreachable")

    seen: list = []
    mgr = LocalTunnelManager(_gw(), open_link=boom)
    res = mgr.survey_preheat([Head("dev1", "node1", "gw1")], lambda d, v: seen.append((d, v)))
    assert res == {"dev1": None} and seen == [("dev1", None)]


def test_read_programming_mode_one_head(monkeypatch):
    """The schedule-write guard's read: raw 0x0025, short and single-attempt by default."""
    calls = []

    def fake_read(link, dev_id, node_id, **kw):
        calls.append((dev_id, node_id, kw))
        return 0x01

    monkeypatch.setattr(tunnel, "read_programming_mode", fake_read)
    link = _RWFakeLink("node1", 0x01)
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: link)
    assert mgr.read_programming_mode(Head("dev1", "node1", "gw1")) == 0x01
    assert calls == [("dev1", "node1", {"duration": 8, "attempts": 1})]
    assert link.closed is True


def test_read_programming_mode_unknown_gateway():
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: None)
    with pytest.raises(tunnel.LocalUnavailable):
        mgr.read_programming_mode(Head("devX", "nodeX", "gw-inconnue"))


def test_survey_preheat_reports_the_standard_attributes_of_each_head():
    """The frame read for the preheat also carries the programming mode: it is handed over."""
    seen = []
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: _ReadFakeLink("node1", 0x03))
    res = mgr.survey_preheat(
        [Head("dev1", "node1", "gw1")], on_attributes=lambda d, a: seen.append((d, a))
    )
    assert res == {"dev1": True}
    assert [d for d, _ in seen] == ["dev1"]
    assert seen[0][1]["programming_mode"] == 0x03 and seen[0][1]["preheat"] is True


def test_survey_preheat_attributes_none_for_an_unreachable_gateway():
    def refuse(g):
        raise OSError("down")

    seen = []
    mgr = LocalTunnelManager(_gw(), open_link=refuse)
    mgr.survey_preheat(
        [Head("dev1", "node1", "gw1")], on_attributes=lambda d, a: seen.append((d, a))
    )
    assert seen == [("dev1", None)]


def test_read_standard_unknown_gateway():
    mgr = LocalTunnelManager(_gw())
    with pytest.raises(tunnel.LocalUnavailable):
        mgr.read_standard(Head("devX", "nodeX", "gw-inconnue"))


def test_survey_settings_reads_each_head(monkeypatch):
    def fake_read(link, dev_id, node_id, **kw):
        return {"radiator_covered": dev_id == "dev1"} if dev_id != "dev3" else None

    monkeypatch.setattr(tunnel, "read_settings", fake_read)
    seen = []
    mgr = LocalTunnelManager(_gw(), open_link=lambda g: _ReadFakeLink("node1", 0x03))
    heads = [Head(f"dev{i}", f"node{i}", "gw1") for i in (1, 2, 3)]
    res = mgr.survey_settings(heads, lambda d, a: seen.append(d))
    assert res == {
        "dev1": {"radiator_covered": True},
        "dev2": {"radiator_covered": False},
        "dev3": None,
    }
    assert seen == ["dev1", "dev2", "dev3"]
    assert mgr.survey_settings(heads[:1]) == {"dev1": {"radiator_covered": True}}


def test_read_settings_skips_the_second_frame_when_the_head_does_not_answer(monkeypatch):
    asked = []

    def fake_read(link, dev_id, node_id, table, manufacturer, **kw):
        asked.append(table)
        return None

    monkeypatch.setattr(tunnel, "read_attributes", fake_read)
    assert tunnel.read_settings(object(), "dev1", "node1") is None
    assert asked == [tunnel.ATTRS_DANFOSS_A]


def test_read_settings_merges_both_frames_and_tolerates_a_missing_second(monkeypatch):
    answers = {id(tunnel.ATTRS_DANFOSS_A): {"orientation": True}}

    def fake_read(link, dev_id, node_id, table, manufacturer, **kw):
        assert manufacturer is True
        return answers.get(id(table))

    monkeypatch.setattr(tunnel, "read_attributes", fake_read)
    assert tunnel.read_settings(object(), "dev1", "node1") == {"orientation": True}
    answers[id(tunnel.ATTRS_DANFOSS_B)] = {"window_state": 1}
    assert tunnel.read_settings(object(), "dev1", "node1") == {
        "orientation": True,
        "window_state": 1,
    }
