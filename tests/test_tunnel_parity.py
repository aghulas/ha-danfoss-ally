"""Local tunnel parity tests with the MCP connector (synthetic data only).

Covers the primitives ported from ``~/dev/danfoss-ally-mcp/local.py``: schedule write
(SetWeeklySchedule), setpoint override (DP 171), descaling (0x4010/0x4011), window detection
(0x4051), multi-gateway fleet survey, and the associated pure summaries. No real key or device:
frames and surveys are fabricated.
"""

import base64

import pytest

from custom_components.danfoss_ally_cloud.api.keys import GatewayKey
from custom_components.danfoss_ally_cloud.api.local import tunnel

# --- outils de doublure -----------------------------------------------------------------------


def _b64(frame: bytes) -> str:
    return base64.b64encode(frame).decode()


def _response_default(cmd_answered: int, statut: int) -> bytes:
    """Default ZCL response (0x0B): [answered cmd, status]."""
    return tunnel.header(tunnel.CLUSTER_THERMOSTAT) + bytes(
        [0x00, 0x40, 0x0B, cmd_answered, statut]
    )


def _response_write(manufacturer: bool, statut: int = 0x00) -> bytes:
    """ "write attributes response" (cmd 0x04)."""
    if manufacturer:
        z = bytes([0x04]) + tunnel.MANUFACTURER.to_bytes(2, "little") + bytes([0x40, 0x04, statut])
    else:
        z = bytes([0x00, 0x40, 0x04, statut])
    return tunnel.header(tunnel.CLUSTER_THERMOSTAT) + z


def _response_attribute_mfr(records: list[tuple[int, int, bytes]]) -> bytes:
    """Manufacturer-code read-attributes response (cmd 0x01)."""
    payload = b"".join(a.to_bytes(2, "little") + bytes([0x00, t]) + v for a, t, v in records)
    z = bytes([0x04]) + tunnel.MANUFACTURER.to_bytes(2, "little") + bytes([0x40, 0x01]) + payload
    return tunnel.header(tunnel.CLUSTER_THERMOSTAT) + z


class _FakeLien:
    """Always answers the same frame, records the frames (DP 198) and the DPs (outside tunnel)."""

    def __init__(self, node_id: str, response: bytes) -> None:
        self.node_id = node_id
        self._resp = _b64(response)
        self.sent: list[bytes] = []
        self.dps: list[tuple[str, object]] = []

    def send(self, dev_id, node_id, frame):
        self.sent.append(frame)

    def send_dp(self, dev_id, node_id, dp, value):
        self.dps.append((dp, value))

    def receive(self):
        return (self.node_id, {"199": self._resp})


# --- 1. schedule write (SetWeeklySchedule) ---------------------------------------------------


def test_write_day_accepted():
    link = _FakeLien("node-1", _response_default(0x01, 0x00))
    statut = tunnel.write_day(
        link, "dev-1", "node-1", "monday", [{"h": "00:00", "c": 17.0}, {"h": "06:30", "c": 21.0}]
    )
    assert statut == 0
    assert link.sent  # a SetWeeklySchedule frame was sent
    z = link.sent[-1][8:]
    assert z[:3] == bytes([0x01, 0x40, 0x01]) and z[3] == 2  # cmd 0x01, 2 transitions


def test_write_day_error_status():
    link = _FakeLien("node-1", _response_default(0x01, 0x85))
    assert tunnel.write_day(link, "dev-1", "node-1", "tuesday", [{"h": "00:00", "c": 19.0}]) == 0x85


def test_write_day_single_transition_at_midnight():
    # R1: a day with a single transition, at 00:00, is valid.
    link = _FakeLien("node-1", _response_default(0x01, 0x00))
    assert tunnel.write_day(link, "dev-1", "node-1", "saturday", [{"h": "00:00", "c": 16.0}]) == 0


def test_write_day_six_transitions_valid():
    # R1: up to six transitions per day, the first at 00:00.
    tr = [{"h": "00:00", "c": 17.0}]
    tr += [{"h": f"{6 + i:02d}:00", "c": 21.0 if i % 2 == 0 else 17.0} for i in range(5)]
    assert len(tr) == 6
    link = _FakeLien("node-1", _response_default(0x01, 0x00))
    assert tunnel.write_day(link, "dev-1", "node-1", "thursday", tr) == 0


def test_write_day_seven_transitions_refused():
    tr = [{"h": f"{i:02d}:00", "c": 20.0} for i in range(7)]
    link = _FakeLien("node-1", _response_default(0x01, 0x00))
    with pytest.raises(tunnel.LocalError):
        tunnel.write_day(link, "dev-1", "node-1", "thursday", tr)


def test_write_day_first_not_midnight_refused():
    link = _FakeLien("node-1", _response_default(0x01, 0x00))
    with pytest.raises(tunnel.LocalError):
        tunnel.write_day(link, "dev-1", "node-1", "thursday", [{"h": "06:00", "c": 21.0}])


# --- 2. setpoint override (DP 171) -----------------------------------------------------------


def test_setpoint_value_hundredths():
    assert tunnel.setpoint_value(21.0) == 2100
    assert tunnel.setpoint_value(16.5) == 1650


@pytest.mark.parametrize("c", [4.5, 35.5, 20.3])
def test_setpoint_value_out_of_range(c):
    with pytest.raises(tunnel.LocalError):
        tunnel.setpoint_value(c)


def test_write_setpoint_publishes_dp171():
    link = _FakeLien("node-1", b"")
    val = tunnel.write_setpoint(link, "dev-1", "node-1", 19.5)
    assert val == 1950
    assert link.dps == [("171", 1950)]


# --- 3. descaling (0x4010 / 0x4011) ----------------------------------------------------------


def test_descale_records_encoding():
    enreg = tunnel.descale_records("wednesday", "12:30")
    assert enreg == [(0x4010, 0x30, 3), (0x4011, 0x21, 750)]  # mercredi = index 3 ; 12:30 = 750 min


def test_descale_records_unknown_day():
    with pytest.raises(tunnel.LocalError):
        tunnel.descale_records("lunedì", "12:00")


def test_write_descale_manufacturer():
    link = _FakeLien("node-1", _response_write(manufacturer=True))
    assert tunnel.write_descale(link, "dev-1", "node-1", "friday", "09:00") == 0
    z = link.sent[-1][8:]
    assert z[0] & 0x04  # manufacturer-code frame
    assert int.from_bytes(z[1:3], "little") == tunnel.MANUFACTURER


# --- 4. window detection (0x4051) + DP settings ----------------------------------------------


def test_read_window_detection():
    link = _FakeLien("node-1", _response_attribute_mfr([(0x4051, 0x10, bytes([0x01]))]))
    assert tunnel.read_window_detection(link, "dev-1", "node-1", duration=1, attempts=1) is True


def test_read_window_detection_closed():
    link = _FakeLien("node-1", _response_attribute_mfr([(0x4051, 0x10, bytes([0x00]))]))
    assert tunnel.read_window_detection(link, "dev-1", "node-1", duration=1, attempts=1) is False


def test_write_setting_dp_window():
    link = _FakeLien("node-1", b"")
    assert tunnel.write_setting_dp(link, "dev-1", "node-1", "window_detection", True) is True
    assert link.dps == [("116", True)]


def test_write_setting_dp_lock():
    link = _FakeLien("node-1", b"")
    tunnel.write_setting_dp(link, "dev-1", "node-1", "child_lock", 1)
    assert link.dps == [("30", True)]  # coerced to bool by SETTINGS_DP


def test_write_setting_dp_unknown():
    link = _FakeLien("node-1", b"")
    with pytest.raises(tunnel.LocalError):
        tunnel.write_setting_dp(link, "dev-1", "node-1", "mode_vacances", True)


# --- name_attributes: Danfoss attributes ---


def test_name_attributes_descale_and_booleans():
    vals = {0x4010: 3, 0x4011: 750, 0x4051: 1, 0x4014: 0}
    out = tunnel.name_attributes(vals, tunnel.ATTRS_DANFOSS_A + tunnel.ATTRS_DANFOSS_B)
    assert out["descale_day"] == "wednesday"
    assert out["descale_time"] == "12:30"
    assert out["window_detection"] is True
    assert out["orientation"] is False


def test_name_attributes_adaptation_state():
    out = tunnel.name_attributes({0x404D: 0x03}, tunnel.ATTRS_DANFOSS_B)
    assert out["adaptation_state"] == 3
    assert out["adaptation_done"] is True


# --- transitions_from_slots + comfort_slots ---


def test_transitions_from_slots():
    tr = tunnel.transitions_from_slots(
        [{"start": "08:00", "end": "12:00"}, {"start": "14:00", "end": "18:00"}], 21.0, 17.0
    )
    assert tr[0] == {"h": "00:00", "c": 17.0}
    assert {"h": "08:00", "c": 21.0} in tr and {"h": "14:00", "c": 21.0} in tr


def test_transitions_from_slots_start_midnight():
    tr = tunnel.transitions_from_slots([{"start": "00:00", "end": "06:00"}], 21.0, 17.0)
    assert tr[0] == {"h": "00:00", "c": 21.0}
    assert tr[1] == {"h": "06:00", "c": 17.0}


def test_transitions_from_slots_overlap():
    with pytest.raises(tunnel.LocalError):
        tunnel.transitions_from_slots(
            [{"start": "08:00", "end": "12:00"}, {"start": "11:00", "end": "13:00"}], 21.0, 17.0
        )


def test_comfort_slots_day_starts_in_comfort():
    # MCP fix: a slot at 00:00 must appear (reference = the lowest setpoint).
    tr = [{"h": "00:00", "c": 21.0}, {"h": "22:00", "c": 17.0}]
    assert tunnel.comfort_slots(tr) == [{"start": "00:00", "end": "22:00", "setpoint": 21.0}]


def test_comfort_slots_merge_consecutive_segments():
    tr = [
        {"h": "00:00", "c": 17.0},
        {"h": "06:00", "c": 21.0},
        {"h": "12:00", "c": 21.0},
        {"h": "18:00", "c": 17.0},
    ]
    assert tunnel.comfort_slots(tr) == [{"start": "06:00", "end": "18:00", "setpoint": 21.0}]


# --- 5. fleet survey + read_head + summaries -------------------------------------------------


class _FakeHead:
    """Answers each survey (standard / danfoss A / danfoss B) and each schedule day."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self._response: bytes | None = None

    def send(self, dev_id, node_id, frame):
        z = frame[8:]
        if z[0] == 0x01 and z[2] == 0x02:  # lecture programme (specifique, cmd 0x02)
            bit = z[3]
            corps = (
                bytes([1, bit, 0x01])
                + (0).to_bytes(2, "little")
                + (2100).to_bytes(2, "little", signed=True)
            )
            self._response = (
                tunnel.header(tunnel.CLUSTER_THERMOSTAT) + bytes([0x01, 0x40, 0x00]) + corps
            )
        elif z[0] == 0x00:  # lecture attributs standard (non manufacturer, cmd read 0x00)
            self._response = _response_attribute_std(
                [
                    (0x0012, 0x29, (2100).to_bytes(2, "little", signed=True)),
                    (0x0025, 0x30, bytes([0x03])),
                ]
            )
        elif z[0] == 0x04:  # lecture attributs Danfoss (manufacturer)
            premier = int.from_bytes(frame[13:15], "little")
            if premier == 0x4010:
                self._response = _response_attribute_mfr(
                    [(0x4010, 0x30, bytes([3])), (0x4011, 0x21, (750).to_bytes(2, "little"))]
                )
            else:  # danfoss B: 0x404B (1st requested, sentinel) + 0x4051 window detection
                self._response = _response_attribute_mfr(
                    [
                        (0x404B, 0x29, (0).to_bytes(2, "little", signed=True)),
                        (0x4051, 0x10, bytes([0x01])),
                    ]
                )

    def receive(self):
        return (self.node_id, {"199": _b64(self._response)}) if self._response else None

    def close(self):
        pass


def _response_attribute_std(records: list[tuple[int, int, bytes]]) -> bytes:
    """NON-manufacturer read-attributes response (cmd 0x01)."""
    payload = b"".join(a.to_bytes(2, "little") + bytes([0x00, t]) + v for a, t, v in records)
    return tunnel.header(tunnel.CLUSTER_THERMOSTAT) + bytes([0x00, 0x40, 0x01]) + payload


def test_read_head_complete():
    e = tunnel.read_head(_FakeHead("node-1"), "dev-1", "node-1")
    assert not e.get("unreachable")
    assert e["attributes"]["programming_mode"] == 3
    assert e["attributes"]["preheat"] is True
    assert e["attributes"]["descale_day"] == "wednesday"
    assert e["attributes"]["window_detection"] is True
    assert set(e["schedule"]) == set(tunnel.WEEKDAYS)
    assert e["schedule"]["monday"] == [{"h": "00:00", "c": 21.0}]


class _TeteMuette:
    """Never answers: unreachable head."""

    def send(self, *a):
        pass

    def receive(self):
        return None

    def close(self):
        pass


def test_read_head_unreachable():
    e = tunnel.read_head(_TeteMuette(), "dev-1", "node-1", schedule=True)
    assert e.get("unreachable") is True
    assert e["attributes"] == {}


class _Head:
    def __init__(self, dev_id, node_id, gateway_id):
        self.dev_id = dev_id
        self.node_id = node_id
        self.gateway_id = gateway_id


def test_survey_multi_gateways():
    gws = {
        "gw-A": GatewayKey("gw-A", "A", "k", ip="10.0.0.1"),
        "gw-B": GatewayKey("gw-B", "B", "k", ip="10.0.0.2"),
    }
    heads = [
        _Head("head-1", "node-1", "gw-A"),
        _Head("head-2", "node-2", "gw-A"),
        _Head("head-3", "node-3", "gw-B"),
    ]
    res = tunnel.survey(gws, heads, open_link=lambda gw: _LienParc())
    assert set(res) == {"head-1", "head-2", "head-3"}
    assert all(not e.get("unreachable") for e in res.values())


class _LienParc:
    """Gateway link that answers any head (on the node requested in the frame)."""

    def __init__(self) -> None:
        self._head = _FakeHead("")

    def send(self, dev_id, node_id, frame):
        self._head.node_id = node_id
        self._head.send(dev_id, node_id, frame)

    def receive(self):
        return self._head.receive()

    def close(self):
        pass


def test_survey_unreachable_gateway():
    gws = {"gw-A": GatewayKey("gw-A", "A", "k", ip="10.0.0.1")}
    heads = [_Head("head-1", "node-1", "gw-A")]

    def open_link(gw):
        raise tunnel.LocalUnavailable("gateway down")

    res = tunnel.survey(gws, heads, open_link=open_link)
    assert res["head-1"]["unreachable"] is True
    assert "error" in res["head-1"]


def test_survey_ignores_unknown_gateway():
    gws = {"gw-A": GatewayKey("gw-A", "A", "k", ip="10.0.0.1")}
    heads = [_Head("head-x", "node-x", "gw-ABSENTE")]
    assert tunnel.survey(gws, heads, open_link=lambda gw: _LienParc()) == {}


# --- pure summaries --------------------------------------------------------------------------


def _survey_head(programme, attributs=None):
    return {"attributes": attributs or {"max_setpoint": 24.0}, "schedule": programme, "missing": []}


def test_summarize_head():
    prog = {
        "monday": [{"h": "00:00", "c": 17.0}, {"h": "08:00", "c": 21.0}, {"h": "18:00", "c": 17.0}]
    }
    out = tunnel.summarize_head(_survey_head(prog))
    assert out["comfort"] == 21.0
    assert out["setback"] == 17.0
    assert out["slots"]["monday"] == ["08:00–18:00"]


def test_summarize_head_unreachable():
    assert tunnel.summarize_head({"attributes": {}}) == {"unreachable": True}


def test_comparer_programme_et_reglages():
    ref = {
        "head-1": _survey_head(
            {"monday": [{"h": "00:00", "c": 17.0}]},
            {"max_setpoint": 24.0, "window_detection": True},
        ),
        "head-2": _survey_head({}, {"max_setpoint": 24.0}),
    }
    nouv = {
        "head-1": _survey_head(
            {"monday": [{"h": "00:00", "c": 19.0}]},
            {"max_setpoint": 24.0, "window_detection": False},
        ),
        "head-2": {"attributes": {}},  # devenue injoignable
    }
    d = tunnel.compare(ref, nouv)
    assert d["schedules_changed"] == [
        {
            "head": "head-1",
            "day": "monday",
            "before": [{"h": "00:00", "c": 17.0}],
            "after": [{"h": "00:00", "c": 19.0}],
        }
    ]
    assert {"head": "head-1", "setting": "window_detection", "before": True, "after": False} in (
        d["settings_changed"]
    )
    assert d["newly_unreachable"] == ["head-2"]
    assert d["unreachable"] == ["head-2"]
