"""Local-tunnel writes of head settings under supervised trial (radiator covered 0x4016, setpoint
offset 0x404B, regulation speed 0x4020, valve exercise 0x4010 / 0x4011).

Closed by default, opened on one designated head only, values validated before sending, the head
read back through the tunnel after each write. Doubles only, synthetic data.
"""

import asyncio
import base64
import dataclasses
import math
from datetime import time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.danfoss_ally_cloud as integration
from custom_components.danfoss_ally_cloud.api import GatewayKey
from custom_components.danfoss_ally_cloud.api.local import tunnel
from custom_components.danfoss_ally_cloud.api.local.manager import Head, LocalTunnelManager
from custom_components.danfoss_ally_cloud.const import (
    CONF_ENABLE_LOCAL,
    CONF_LOCAL_SUPERVISED_HEAD,
    CONF_LOCAL_SUPERVISED_SETTINGS,
    DATA_LOCAL,
    DATA_LOCAL_SUPERVISED_HEAD,
    DATA_LOCAL_SUPERVISED_SETTINGS,
    DOMAIN,
)
from custom_components.danfoss_ally_cloud.coordinator import DanfossLocalCoordinator
from custom_components.danfoss_ally_cloud.local_write import (
    LocalWriteNotConfirmed,
    LocalWriteRefused,
    LocalWriteRejected,
    async_local_write_setting,
    async_local_write_valve_exercise,
    local_setting_armed,
    local_trial_for,
)
from custom_components.danfoss_ally_cloud.number import DanfossLocalSettingNumber
from custom_components.danfoss_ally_cloud.select import DanfossValveExerciseDay
from custom_components.danfoss_ally_cloud.switch import DanfossLocalSettingSwitch
from custom_components.danfoss_ally_cloud.time import DanfossValveExerciseTime

from .common import ENTRY_DATA, FakeCloudClient, head
from .test_coordinator_local import FakeManager

HEAD = Head("trial-head-id", "n1", "gw-1")
ALL = [
    "radiator_covered",
    "setpoint_offset",
    "regulation_speed",
    "valve_exercise",
    "external_room_sensor",
    "window_open_external",
    "load_balancing",
    "adaptation_run_settings",
]

# --- pure layer: validation and frames ----------------------------------------------------------


@pytest.mark.parametrize(
    ("setting", "value", "raw"),
    [
        ("radiator_covered", True, 1),
        ("radiator_covered", False, 0),
        ("control_speed", 1, 1),
        ("control_speed", 10.0, 10),
        ("setpoint_offset", -2.5, -25),
        ("setpoint_offset", 0.3, 3),
        ("setpoint_offset", 0.1 + 0.2, 3),  # float noise is not a step error
        ("setpoint_offset", 2.5, 25),
        ("setpoint_offset", 0, 0),
        ("window_open_external", True, 1),
        ("window_open_external", False, 0),
        ("load_balancing", True, 1),
        ("load_balancing", False, 0),
        ("external_room_sensor", 21, 2100),
        ("external_room_sensor", 21.5, 2150),
        ("external_room_sensor", 0, 0),
        ("external_room_sensor", 35, 3500),  # max
        ("external_room_sensor", -80, -8000),  # the disable sentinel
        ("adaptation_setting", True, 1),
        ("adaptation_setting", False, 0),
    ],
)
def test_setting_raw_accepts(setting, value, raw):
    assert tunnel.setting_raw(setting, value) == raw


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("radiator_covered", 1),
        ("radiator_covered", "on"),
        ("control_speed", 0),
        ("control_speed", 11),
        ("control_speed", 2.5),
        ("control_speed", True),
        ("setpoint_offset", 2.6),
        ("setpoint_offset", -2.51),
        ("setpoint_offset", 0.15),
        ("setpoint_offset", math.nan),
        ("setpoint_offset", "1"),
        ("window_open_external", 1),  # not a bool
        ("window_open_external", "on"),
        ("load_balancing", 1),  # not a bool
        ("external_room_sensor", 35.1),  # above max
        ("external_room_sensor", -80.1),  # below the disable sentinel
        ("external_room_sensor", True),  # not a number
        ("external_room_sensor", "21"),
        ("adaptation_setting", 1),  # not a bool
        ("adaptation_setting", "on"),
        ("orientation", True),  # out of scope: other channel
    ],
)
def test_setting_raw_refuses(setting, value):
    with pytest.raises(tunnel.LocalError):
        tunnel.setting_raw(setting, value)


def test_records_and_frame_types():
    assert tunnel.setting_records("radiator_covered", True) == [(0x4016, 0x10, 1)]
    assert tunnel.setting_records("control_speed", 5) == [(0x4020, 0x20, 5)]
    assert tunnel.setting_records("setpoint_offset", -1.2) == [(0x404B, 0x28, -12)]
    assert tunnel.setting_records("window_open_external", True) == [(0x4003, 0x10, 1)]
    assert tunnel.setting_records("load_balancing", False) == [(0x4032, 0x10, 0)]
    assert tunnel.setting_records("external_room_sensor", 21) == [(0x4015, 0x29, 2100)]
    assert tunnel.setting_records("adaptation_setting", True) == [(0x404E, 0x18, 1)]
    assert tunnel.setting_records("adaptation_setting", False) == [(0x404E, 0x18, 0)]
    # int16, signed: the -8000 disable sentinel round-trips through the frame as two LE bytes.
    frame = tunnel.frame_write_attributes(tunnel.setting_records("external_room_sensor", -80), True)
    assert frame[13:] == bytes([0x15, 0x40, 0x29]) + (-8000).to_bytes(2, "little", signed=True)
    frame = tunnel.frame_write_attributes(tunnel.setting_records("setpoint_offset", -1.2), True)
    # manufacturer-specific write (cmd 0x02) carrying attribute 0x404B, int8, signed -12
    assert frame[8:13] == bytes([0x04, 0x46, 0x12, 0x40, 0x02])
    assert frame[13:] == bytes([0x4B, 0x40, 0x28, 0xF4])


# --- manager, with a link double that answers like a head ---------------------------------------


def _response(command: int, payload: bytes) -> str:
    frame = (
        tunnel.header(tunnel.CLUSTER_THERMOSTAT)
        + bytes([0x04])
        + tunnel.MANUFACTURER.to_bytes(2, "little")
        + bytes([0x40, command])
        + payload
    )
    return base64.b64encode(frame).decode()


class _HeadLink:
    """A head behind the tunnel: answers manufacturer reads from ``attrs`` and writes with
    ``write_status`` (None: no answer), applying an accepted write."""

    def __init__(self, attrs: dict[int, tuple[int, int]], write_status: int | None = 0) -> None:
        self.attrs = attrs  # attribute -> (ZCL type, raw)
        self.write_status = write_status
        self.sent: list[bytes] = []
        self._pending: list[str] = []
        self.closed = False

    def send(self, dev_id, node_id, frame):
        self.sent.append(frame)
        f = tunnel.decode_frame(frame)
        assert f is not None and f["manufacturer"] == tunnel.MANUFACTURER
        body = f["payload"]
        if f["command"] == 0x00:  # read
            out = b""
            for i in range(0, len(body), 2):
                a = int.from_bytes(body[i : i + 2], "little")
                if a in self.attrs:
                    typ, raw = self.attrs[a]
                    n = tunnel._LENGTH[typ]
                    out += a.to_bytes(2, "little") + bytes([0x00, typ])
                    out += raw.to_bytes(n, "little", signed=typ in tunnel._SIGNED)
                else:
                    out += a.to_bytes(2, "little") + bytes([0x86])
            self._pending.append(_response(0x01, out))
        elif f["command"] == 0x02 and self.write_status is not None:
            i = 0
            while i < len(body):
                a, typ = int.from_bytes(body[i : i + 2], "little"), body[i + 2]
                n = tunnel._LENGTH[typ]
                raw = int.from_bytes(
                    body[i + 3 : i + 3 + n], "little", signed=typ in tunnel._SIGNED
                )
                if self.write_status == 0:
                    self.attrs[a] = (typ, raw)
                i += 3 + n
            self._pending.append(_response(0x04, bytes([self.write_status])))

    def receive(self):
        if self._pending:
            return ("n1", {"199": self._pending.pop(0)})
        return None

    def close(self):
        self.closed = True


@pytest.fixture
def fast_tunnel(monkeypatch):
    """A head that does not answer costs no real waiting."""
    real = tunnel.request

    def quick(link, dev_id, node_id, frame, accept, duration=12, attempts=2):
        return real(link, dev_id, node_id, frame, accept, duration=0.05, attempts=1)

    monkeypatch.setattr(tunnel, "request", quick)


def _manager(link):
    gws = {"gw-1": GatewayKey("gw-1", "GW", "synthetic-key", ip="10.0.0.1")}
    return LocalTunnelManager(gws, open_link=lambda g: link)


def test_manager_write_setting_sends_one_attribute(fast_tunnel):
    link = _HeadLink({0x404B: (0x28, 0)})
    assert _manager(link).write_setting(HEAD, "setpoint_offset", -0.5) == 0
    assert link.attrs[0x404B] == (0x28, -5)
    assert link.closed


def test_manager_write_setting_validates_before_opening_a_link():
    opened = []
    mgr = LocalTunnelManager({}, open_link=lambda g: opened.append(g))
    with pytest.raises(tunnel.LocalError):
        mgr.write_setting(HEAD, "control_speed", 42)
    with pytest.raises(tunnel.LocalUnavailable):
        mgr.write_setting(HEAD, "control_speed", 4)  # gateway unknown
    assert opened == []


def test_manager_valve_exercise_keeps_the_other_half(fast_tunnel):
    link = _HeadLink({0x4010: (0x30, 3), 0x4011: (0x21, 13 * 60)})  # wednesday 13:00
    assert _manager(link).write_valve_exercise(HEAD, day="friday") == (0, "friday", "13:00")
    assert link.attrs[0x4010] == (0x30, 5) and link.attrs[0x4011] == (0x21, 780)
    assert _manager(link).write_valve_exercise(HEAD, hour="07:30") == (0, "friday", "07:30")
    assert link.attrs[0x4011] == (0x21, 450)


def test_manager_valve_exercise_refusals(fast_tunnel):
    mgr = _manager(_HeadLink({0x4010: (0x30, 7), 0x4011: (0x21, 0)}))  # day undefined
    with pytest.raises(tunnel.LocalError, match="set the day first"):
        mgr.write_valve_exercise(HEAD, hour="10:00")
    with pytest.raises(tunnel.LocalError, match="one at a time"):
        mgr.write_valve_exercise(HEAD, day="monday", hour="10:00")
    with pytest.raises(tunnel.LocalError, match="one at a time"):
        mgr.write_valve_exercise(HEAD)
    with pytest.raises(tunnel.LocalError):
        mgr.write_valve_exercise(HEAD, day="someday")
    with pytest.raises(tunnel.LocalError):
        mgr.write_valve_exercise(HEAD, hour="25:00")
    unsupported = _manager(_HeadLink({}))  # answers, without the two values
    with pytest.raises(tunnel.LocalError, match="unreadable"):
        unsupported.write_valve_exercise(HEAD, day="monday")
    silent = _manager(_HeadLink({0x4010: (0x30, 1), 0x4011: (0x21, 0)}, write_status=None))
    # a head that answers the read but not the write: status None, the caller reads back
    assert silent.write_valve_exercise(HEAD, day="monday") == (None, "monday", "00:00")
    with pytest.raises(tunnel.LocalUnavailable):
        LocalTunnelManager({}).write_valve_exercise(HEAD, day="monday")


# --- local_write: write, read back, judge -------------------------------------------------------


class _Local:
    """Double of the local coordinator: a manager double and the read-back of one head."""

    def __init__(self, status=0, read=None, exc=None, valve=(0, "monday", "08:00")):
        self.manager = MagicMock()
        self.manager.gateway_ids = {"gw-1"}
        self.manager.write_setting = MagicMock(side_effect=exc, return_value=status)
        self.manager.write_valve_exercise = MagicMock(side_effect=exc, return_value=valve)
        self.async_refresh_settings = AsyncMock(return_value=read)


async def test_write_confirmed_returns_the_read_back(hass: HomeAssistant):
    local = _Local(read={"setpoint_offset": -5, "radiator_covered": False})
    read = await async_local_write_setting(hass, local, HEAD, "setpoint_offset", -0.5)
    assert read["setpoint_offset"] == -5
    local.manager.write_setting.assert_called_once_with(HEAD, "setpoint_offset", -0.5)
    local.async_refresh_settings.assert_awaited_once_with(HEAD)


async def test_write_with_no_answer_to_the_write_is_judged_by_the_read_back(hass: HomeAssistant):
    local = _Local(status=None, read={"radiator_covered": True})
    await async_local_write_setting(hass, local, HEAD, "radiator_covered", True)


async def test_invalid_value_sends_nothing(hass: HomeAssistant):
    local = _Local()
    with pytest.raises(LocalWriteRefused):
        await async_local_write_setting(hass, local, HEAD, "regulation_speed", 11)
    local.manager.write_setting.assert_not_called()
    local.async_refresh_settings.assert_not_awaited()


async def test_rejected_by_the_head(hass: HomeAssistant):
    local = _Local(status=0x87, read={"control_speed": 5})
    with pytest.raises(LocalWriteRejected, match="0x87"):
        await async_local_write_setting(hass, local, HEAD, "regulation_speed", 6)


async def test_read_back_disagrees(hass: HomeAssistant):
    local = _Local(read={"control_speed": 5})
    with pytest.raises(LocalWriteRejected, match="disagrees"):
        await async_local_write_setting(hass, local, HEAD, "regulation_speed", 6)


async def test_no_read_back(hass: HomeAssistant):
    local = _Local(read=None)
    with pytest.raises(LocalWriteNotConfirmed):
        await async_local_write_setting(hass, local, HEAD, "radiator_covered", True)


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (tunnel.LocalUnavailable("gateway down"), LocalWriteRefused),
        (tunnel.LocalError("bad"), LocalWriteRefused),
        (OSError("socket closed mid-write"), LocalWriteNotConfirmed),
    ],
)
async def test_tunnel_failures(hass: HomeAssistant, exc, kind):
    local = _Local(exc=exc)
    with pytest.raises(kind):
        await async_local_write_setting(hass, local, HEAD, "radiator_covered", True)
    local.async_refresh_settings.assert_not_awaited()


async def test_valve_exercise_write_and_read_back(hass: HomeAssistant):
    local = _Local(read={"descale_day": "monday", "descale_time": "08:00"})
    read = await async_local_write_valve_exercise(hass, local, HEAD, day="monday")
    assert read["descale_day"] == "monday"
    local.manager.write_valve_exercise.assert_called_once_with(HEAD, "monday", None)
    local.async_refresh_settings.return_value = {"descale_day": "monday", "descale_time": "09:00"}
    with pytest.raises(LocalWriteRejected):
        await async_local_write_valve_exercise(hass, local, HEAD, day="monday")


# --- gate ---------------------------------------------------------------------------------------


def test_trial_is_confined_to_the_designated_head():
    data = {
        DATA_LOCAL_SUPERVISED_SETTINGS: frozenset({"radiator_covered"}),
        DATA_LOCAL_SUPERVISED_HEAD: "trial-head-id",
    }
    assert local_trial_for(data, "trial-head-id") == {"radiator_covered"}
    assert local_trial_for(data, "other") == frozenset()
    assert local_trial_for({**data, DATA_LOCAL_SUPERVISED_HEAD: None}, "trial-head-id") == set()
    local = _Local()
    dev = head("trial-head-id", node_id="n1")
    assert local_setting_armed(data, local, dev, "radiator_covered")
    assert not local_setting_armed(data, local, dev, "setpoint_offset")
    assert not local_setting_armed(data, None, dev, "radiator_covered")
    assert not local_setting_armed(
        data, local, head("trial-head-id", node_id=None), "radiator_covered"
    )
    assert not local_setting_armed(
        data, local, head("trial-head-id", node_id="n1", mesh_id="gw-x"), "radiator_covered"
    )
    assert not local_setting_armed(
        data, local, head("trial-head-id", node_id="n1", product_id="other"), "radiator_covered"
    )


def test_options_are_parsed_and_unknown_keys_dropped(caplog):
    entry = MagicMock()
    entry.options = {
        CONF_ENABLE_LOCAL: True,
        CONF_LOCAL_SUPERVISED_SETTINGS: ["radiator_covered", "no_such_setting"],
        CONF_LOCAL_SUPERVISED_HEAD: "trial-head-id",
    }
    trial = integration._local_trial(entry)
    assert trial[DATA_LOCAL_SUPERVISED_SETTINGS] == {"radiator_covered"}
    assert trial[DATA_LOCAL_SUPERVISED_HEAD] == "trial-head-id"
    assert "radiator_covered" in caplog.text and "trial-head-id" not in caplog.text
    entry.options = {**entry.options, CONF_LOCAL_SUPERVISED_HEAD: ""}
    assert integration._local_trial(entry)[DATA_LOCAL_SUPERVISED_HEAD] is None
    assert "no trial head is designated" in caplog.text


# --- entities, on a real entry ------------------------------------------------------------------

_GW = {"gw-1": GatewayKey("gw-1", "GW", "0123456789abcdef", ip="10.0.0.1")}
_SETTINGS = {
    "radiator_covered": False,
    "control_speed": 5,
    "setpoint_offset": -3,
    "descale_day": "wednesday",
    "descale_time": "13:00",
    "adaptation_setting": False,
}


class _TrialManager(FakeManager):
    """FakeManager with the single-head settings read and the trial writes, applied as written."""

    def __init__(self):
        super().__init__()
        self.settings = {"trial-head-id": dict(_SETTINGS), "other-head-id": dict(_SETTINGS)}
        self.writes: list = []
        self.apply = True
        self.read_exc: Exception | None = None

    def read_settings(self, head_):
        if self.read_exc is not None:
            raise self.read_exc
        return dict(self.settings[head_.dev_id])

    def write_setting(self, head_, setting, value):
        self.writes.append((head_.dev_id, setting, value))
        raw = tunnel.setting_raw(setting, value)
        if self.apply:
            self.settings[head_.dev_id][setting] = bool(raw) if setting in tunnel._BOOLEANS else raw
        return 0

    def write_valve_exercise(self, head_, day=None, hour=None):
        self.writes.append((head_.dev_id, "valve_exercise", day, hour))
        s = self.settings[head_.dev_id]
        new_day, new_hour = day or s["descale_day"], hour or s["descale_time"]
        if self.apply:
            s["descale_day"], s["descale_time"] = new_day, new_hour
        return 0, new_day, new_hour


def _fleet():
    return FakeCloudClient(
        devices=[
            head("trial-head-id", "Test head", node_id="n1"),
            head("other-head-id", "Other head", node_id="n2"),
        ]
    )


async def _setup(hass: HomeAssistant, options, manager=None, entry=None):
    if entry is None:
        entry = MockConfigEntry(
            domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr", options=options
        )
        entry.add_to_hass(hass)
    manager = manager or _TrialManager()
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=_fleet()),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value=_GW),
        ),
        patch("custom_components.danfoss_ally_cloud.LocalTunnelManager", return_value=manager),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    return entry


_ARMED = {
    CONF_ENABLE_LOCAL: True,
    CONF_LOCAL_SUPERVISED_SETTINGS: ALL,
    CONF_LOCAL_SUPERVISED_HEAD: "trial-head-id",
}
_CLASSES = {
    "switch": DanfossLocalSettingSwitch,
    "number": DanfossLocalSettingNumber,
    "select": DanfossValveExerciseDay,
    "time": DanfossValveExerciseTime,
}


def _entities(hass, domain):
    component = hass.data["entity_components"].get(domain)
    cls = _CLASSES[domain]
    return [] if component is None else [e for e in component.entities if isinstance(e, cls)]


def _one(hass, domain, key=None):
    ents = [e for e in _entities(hass, domain) if key is None or e.unique_id.endswith(key)]
    assert len(ents) == 1
    return ents[0]


async def test_entities_only_on_the_armed_head(hass: HomeAssistant):
    await _setup(hass, _ARMED)
    # switch: radiator covered, external window open, load balancing, automatic adaptation run (4).
    # number: setpoint offset, regulation speed, external room sensor (3). select / time: the valve
    # exercise pair (1 each).
    for domain, count in (("switch", 4), ("number", 3), ("select", 1), ("time", 1)):
        ents = _entities(hass, domain)
        assert len(ents) == count
        assert {e._device_id for e in ents} == {"trial-head-id"}


@pytest.mark.parametrize(
    "options",
    [
        {},  # the default: closed
        {CONF_ENABLE_LOCAL: True},
        {**_ARMED, CONF_ENABLE_LOCAL: False},
        {**_ARMED, CONF_LOCAL_SUPERVISED_HEAD: ""},
        {**_ARMED, CONF_LOCAL_SUPERVISED_SETTINGS: []},
    ],
)
async def test_no_entity_unless_armed(hass: HomeAssistant, options):
    await _setup(hass, options)
    for domain in _CLASSES:
        assert _entities(hass, domain) == []


async def test_one_setting_opens_one_entity(hass: HomeAssistant):
    await _setup(hass, {**_ARMED, CONF_LOCAL_SUPERVISED_SETTINGS: ["setpoint_offset"]})
    assert [e.unique_id for e in _entities(hass, "number")] == [
        "trial-head-id_setpoint_offset_setting"
    ]
    for domain in ("switch", "select", "time"):
        assert _entities(hass, domain) == []


async def test_disarming_removes_the_registry_entries(hass: HomeAssistant):
    entry = await _setup(hass, _ARMED)
    registry = er.async_get(hass)
    uids = {
        "switch": "trial-head-id_radiator_covered_setting",
        "number": "trial-head-id_regulation_speed_setting",
        "select": "trial-head-id_valve_exercise_day",
        "time": "trial-head-id_valve_exercise_time",
    }
    for domain, uid in uids.items():
        assert registry.async_get_entity_id(domain, DOMAIN, uid)
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.config_entries.async_update_entry(
        entry, options={**_ARMED, CONF_LOCAL_SUPERVISED_HEAD: ""}
    )
    await _setup(hass, {}, entry=entry)
    for domain, uid in uids.items():
        assert registry.async_get_entity_id(domain, DOMAIN, uid) is None


async def test_states_come_from_the_head(hass: HomeAssistant):
    await _setup(hass, _ARMED)
    switch = _one(hass, "switch", "radiator_covered_setting")
    assert switch.available and switch.is_on is False
    offset = _one(hass, "number", "setpoint_offset_setting")
    assert offset.native_value == -0.3
    assert offset.native_min_value == -2.5 and offset.native_max_value == 2.5
    assert _one(hass, "number", "regulation_speed_setting").native_value == 5
    assert _one(hass, "select").current_option == "wednesday"
    assert _one(hass, "time").native_value == time(13, 0)
    attrs = switch.extra_state_attributes
    assert attrs["write_path"] == "local" and attrs["write_trial"] is True
    assert attrs["write_scope"] == "head" and attrs["read_at"] is not None


async def test_writes_show_the_read_back(hass: HomeAssistant):
    manager = _TrialManager()
    await _setup(hass, _ARMED, manager=manager)
    await _one(hass, "switch", "radiator_covered_setting").async_turn_on()
    await _one(hass, "number", "setpoint_offset_setting").async_set_native_value(1.2)
    await _one(hass, "number", "regulation_speed_setting").async_set_native_value(7.0)
    await _one(hass, "select").async_select_option("friday")
    await _one(hass, "time").async_set_value(time(6, 45))
    assert manager.writes == [
        ("trial-head-id", "radiator_covered", True),
        ("trial-head-id", "setpoint_offset", 1.2),
        ("trial-head-id", "control_speed", 7),
        ("trial-head-id", "valve_exercise", "friday", None),
        ("trial-head-id", "valve_exercise", None, "06:45"),
    ]
    switch = _one(hass, "switch", "radiator_covered_setting")
    assert switch.is_on is True
    assert switch.extra_state_attributes["trial_result"] == "confirmed_by_tunnel"
    assert _one(hass, "number", "setpoint_offset_setting").native_value == 1.2
    assert _one(hass, "number", "regulation_speed_setting").native_value == 7
    assert _one(hass, "select").current_option == "friday"
    assert _one(hass, "time").native_value == time(6, 45)
    assert manager.settings["other-head-id"] == _SETTINGS  # nothing else touched


async def test_a_write_the_head_does_not_apply_shows_the_head(hass: HomeAssistant):
    manager = _TrialManager()
    await _setup(hass, _ARMED, manager=manager)
    manager.apply = False
    switch = _one(hass, "switch", "radiator_covered_setting")
    with pytest.raises(HomeAssistantError, match="disagrees"):
        await switch.async_turn_on()
    assert switch.is_on is False  # what the head says, not what was written
    assert switch.extra_state_attributes["trial_result"] == "rejected"


async def test_no_read_back_makes_the_entity_unavailable(hass: HomeAssistant):
    manager = _TrialManager()
    entry = await _setup(hass, _ARMED, manager=manager)
    manager.read_exc = OSError("no answer")
    offset = _one(hass, "number", "setpoint_offset_setting")
    with pytest.raises(LocalWriteNotConfirmed):
        await offset.async_set_native_value(0.5)
    assert offset.extra_state_attributes["trial_result"] == "not_confirmed"
    assert not offset.available  # the value read before the write can no longer be trusted
    # A later read of the head (here: the read-back of another write) makes it available again.
    manager.read_exc = None
    local: DanfossLocalCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_LOCAL]
    later = dt_util.utcnow() + timedelta(seconds=1)
    with patch(
        "custom_components.danfoss_ally_cloud.coordinator.dt_util.utcnow", return_value=later
    ):
        await local.async_refresh_settings(HEAD)
    assert offset.available and offset.native_value == 0.5


async def test_entity_refuses_out_of_range_before_sending(hass: HomeAssistant):
    manager = _TrialManager()
    await _setup(hass, _ARMED, manager=manager)
    speed = _one(hass, "number", "regulation_speed_setting")
    with pytest.raises(LocalWriteRefused):
        await speed.async_set_native_value(5.5)
    with pytest.raises(HomeAssistantError, match="unknown day"):
        await _one(hass, "select").async_select_option("someday")
    assert manager.writes == []


async def test_unreachable_head_is_unavailable_and_not_written(hass: HomeAssistant):
    manager = _TrialManager()
    entry = await _setup(hass, _ARMED, manager=manager)
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    dev = coordinator.data["trial-head-id"]
    coordinator.data["trial-head-id"] = dataclasses.replace(dev, mesh_id="gw-unknown")
    for domain in _CLASSES:
        for ent in _entities(hass, domain):
            assert not ent.available
    with pytest.raises(HomeAssistantError, match="cannot reach"):
        await _one(hass, "switch", "radiator_covered_setting").async_turn_on()
    with pytest.raises(HomeAssistantError, match="cannot reach"):
        await _one(hass, "number", "regulation_speed_setting").async_set_native_value(3)
    with pytest.raises(HomeAssistantError, match="cannot reach"):
        await _one(hass, "select").async_select_option("monday")
    with pytest.raises(HomeAssistantError, match="cannot reach"):
        await _one(hass, "time").async_set_value(time(1, 0))
    assert manager.writes == []


async def test_undefined_or_odd_values_read_unknown(hass: HomeAssistant):
    manager = _TrialManager()
    manager.settings["trial-head-id"].update(
        descale_day="undefined", descale_time="??", setpoint_offset=True
    )
    await _setup(hass, _ARMED, manager=manager)
    assert _one(hass, "select").current_option is None
    assert _one(hass, "time").native_value is None
    assert _one(hass, "number", "setpoint_offset_setting").native_value is None


async def test_settings_pass_does_not_overwrite_a_read_back(hass: HomeAssistant):
    """A head read back after a write while the daily pass runs keeps that fresher read, also
    in the pass's final merge."""
    cloud = MagicMock()
    cloud.data = {"trial-head-id": head("trial-head-id", node_id="n1")}
    manager = _TrialManager()
    local = DanfossLocalCoordinator(hass, manager, cloud, 900)

    def survey_settings(heads, on_result=None, stop=None):  # worker thread
        stale = dict(_SETTINGS)
        manager.settings["trial-head-id"]["control_speed"] = 9  # a write lands meanwhile...
        asyncio.run_coroutine_threadsafe(  # ...and is read back while the pass runs
            local.async_refresh_settings(HEAD), hass.loop
        ).result()
        on_result("trial-head-id", stale)
        return {"trial-head-id": stale}

    manager.survey_settings = survey_settings
    await local._async_update_data()
    await hass.async_block_till_done()
    assert local.settings["trial-head-id"]["control_speed"] == 9


async def test_switch_turn_off_writes_false(hass: HomeAssistant):
    manager = _TrialManager()
    manager.settings["trial-head-id"]["radiator_covered"] = True
    await _setup(hass, _ARMED, manager=manager)
    switch = _one(hass, "switch", "radiator_covered_setting")
    await switch.async_turn_off()
    assert manager.writes == [("trial-head-id", "radiator_covered", False)]
    assert switch.is_on is False


async def test_external_window_and_load_balancing_switches(hass: HomeAssistant):
    manager = _TrialManager()
    await _setup(hass, _ARMED, manager=manager)
    window = _one(hass, "switch", "window_open_external_setting")
    load = _one(hass, "switch", "load_balancing_setting")
    await window.async_turn_on()
    await load.async_turn_off()
    assert manager.writes == [
        ("trial-head-id", "window_open_external", True),
        ("trial-head-id", "load_balancing", False),
    ]
    assert window.is_on is True and load.is_on is False


async def test_adaptation_run_settings_switch(hass: HomeAssistant):
    """0x404E ``adaptation_run_settings`` is a boolean (on/off), exposed as a switch and written
    through the local tunnel; the state shown is the head's own read-back."""
    manager = _TrialManager()
    await _setup(hass, _ARMED, manager=manager)
    switch = _one(hass, "switch", "adaptation_run_settings_setting")
    assert switch.available and switch.is_on is False
    await switch.async_turn_on()
    # the manager is called with the tunnel attribute name (``adaptation_setting``), not the trial
    # key, just as ``regulation_speed`` is written as ``control_speed``.
    assert manager.writes == [("trial-head-id", "adaptation_setting", True)]
    # written as attribute 0x404E, read back as a bool from the tunnel
    assert manager.settings["trial-head-id"]["adaptation_setting"] is True
    assert switch.is_on is True
    assert switch.extra_state_attributes["trial_result"] == "confirmed_by_tunnel"
    await switch.async_turn_off()
    assert manager.writes[-1] == ("trial-head-id", "adaptation_setting", False)
    assert switch.is_on is False
    assert manager.settings["other-head-id"] == _SETTINGS  # nothing else touched


async def test_external_room_sensor_number_writes_and_disables(hass: HomeAssistant):
    manager = _TrialManager()
    await _setup(hass, _ARMED, manager=manager)
    number = _one(hass, "number", "external_room_sensor_setting")
    assert number.native_min_value == -80 and number.native_max_value == 35
    await number.async_set_native_value(19.5)
    assert manager.writes == [("trial-head-id", "external_room_sensor", 19.5)]
    assert number.native_value == 19.5  # read back in °C from raw 1950 hundredths
    # -80 °C (raw -8000) is the Danfoss disable sentinel, and must be accepted.
    await number.async_set_native_value(-80.0)
    assert manager.settings["trial-head-id"]["external_room_sensor"] == -8000
    assert number.native_value == -80


async def test_options_form_offers_the_local_trial(hass: HomeAssistant):
    """Every head of a verified model with a node id may be designated (grouped or isolated), by
    name; a stored head that is no longer offered stays selectable; every setting is listed."""
    entry = await _setup(hass, {CONF_ENABLE_LOCAL: True, CONF_LOCAL_SUPERVISED_HEAD: "gone-id"})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    head_field = next(k for k in schema if str(k) == CONF_LOCAL_SUPERVISED_HEAD)
    assert schema[head_field].container == {
        "": "—",
        "trial-head-id": "Test head",
        "other-head-id": "Other head",
        "gone-id": "(head not available)",
    }
    settings_field = next(k for k in schema if str(k) == CONF_LOCAL_SUPERVISED_SETTINGS)
    assert set(schema[settings_field].options) == set(ALL)


async def test_partial_read_back_is_not_confirmed_not_rejected(hass: HomeAssistant):
    """The offset (0x404B) is in the second settings frame: a read-back where the head answered
    the first frame only does not say what it holds for the offset. Unknown, not a rejection."""
    local = _Local(read={"radiator_covered": False, "control_speed": 5})  # frame A only
    with pytest.raises(LocalWriteNotConfirmed, match="setpoint_offset"):
        await async_local_write_setting(hass, local, HEAD, "setpoint_offset", 0.5)
    local.async_refresh_settings.return_value = {"setpoint_offset": None}
    with pytest.raises(LocalWriteNotConfirmed):
        await async_local_write_setting(hass, local, HEAD, "setpoint_offset", 0.5)
    # A non-zero ZCL status stays a rejection, even with a partial read-back.
    local = _Local(status=0x86, read={"radiator_covered": False})
    with pytest.raises(LocalWriteRejected, match="0x86"):
        await async_local_write_setting(hass, local, HEAD, "setpoint_offset", 0.5)


def test_read_settings_without_frame_b_lacks_the_offset(fast_tunnel):
    """What the manager's single-head read gives when the head answers frame A and not frame B."""

    class _ALink(_HeadLink):
        def send(self, dev_id, node_id, frame):
            body = tunnel.decode_frame(frame)["payload"]
            if int.from_bytes(body[:2], "little") == 0x404B:  # frame B: no answer
                self.sent.append(frame)
                return
            super().send(dev_id, node_id, frame)

    link = _ALink({0x4016: (0x10, 0), 0x4020: (0x20, 5), 0x404B: (0x28, 5)})
    read = _manager(link).read_settings(HEAD)
    assert read is not None and read["control_speed"] == 5 and "setpoint_offset" not in read


async def test_entity_after_a_partial_read_back(hass: HomeAssistant):
    class _FrameAOnly(_TrialManager):
        def __init__(self):
            super().__init__()
            self.frame_a_only = False

        def read_settings(self, head_):
            read = super().read_settings(head_)
            if self.frame_a_only:
                for name in ("setpoint_offset", "window_state"):
                    read.pop(name, None)
            return read

    manager = _FrameAOnly()
    await _setup(hass, _ARMED, manager=manager)
    offset = _one(hass, "number", "setpoint_offset_setting")
    assert offset.available
    manager.frame_a_only = True
    with pytest.raises(LocalWriteNotConfirmed):
        await offset.async_set_native_value(0.5)
    assert offset.extra_state_attributes["trial_result"] == "not_confirmed"
    assert not offset.available
