"""Shared operations tests (services/WebSocket): rooms, validation, write, jobs."""

from datetime import datetime

import pytest

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud.api.local import tunnel
from custom_components.danfoss_ally_cloud.const import (
    DATA_COORDINATOR,
    DATA_JOBS,
    DATA_LOCAL,
    DATA_SCHEDULES,
)
from custom_components.danfoss_ally_cloud.writejob import JobManager

from .common import head

_ROOM = {"type": "room", "id": "13000000"}


@pytest.fixture(autouse=True)
def _no_timer(monkeypatch):
    """Disable the deferred verification (timer): tested separately via verify_job."""
    monkeypatch.setattr(ops, "_defer_verification", lambda *a, **k: None)


class _RoomState:
    def __init__(self, nom, pid, consignes):
        self.name = nom
        self.pid = pid
        self.setpoints = consignes
        self.head_count = 2
        self.online = True
        self.temperature = 20.4
        self.setpoint = 21.0
        self.mode = "at_home"
        self.heating = True


class _FakeClient:
    def __init__(self):
        self.calls = []
        self.schedule_reads = 0

    async def async_get_schedule(self, target):
        self.schedule_reads += 1
        return {"target": target, "days": {"mon": [{"start": "08:30", "end": "17:30"}]}}

    async def async_set_schedule_days(self, target, days):
        self.calls.append(("set", target, days))

    async def async_restore_schedule(self, target):
        self.calls.append(("restore", target))


class _Coord:
    def __init__(self, grouped=True):
        self.client = _FakeClient()
        self.data = {
            "a": head("a", "Salle 1 #2", schedule_active=True),
            "b": head("b", "Salle 1 #3", schedule_active=False, mode="at_home"),
        }
        self.rooms = {
            "13000000": _RoomState("Salle 1", "03wvrwpv", {"comfort": 21.0, "setback": 14.0})
        }
        self._group = {"a": "13000000", "b": "13000000"} if grouped else {}
        self.refreshed = False
        self.commanded: list[str] = []

    def group_of(self, head_id):
        return self._group.get(head_id)

    def note_commanded(self, head_ids):
        self.commanded.extend(head_ids)

    async def async_request_refresh(self):
        self.refreshed = True


def _store(grouped=True):
    coord = _Coord(grouped)
    return {DATA_COORDINATOR: coord, DATA_JOBS: JobManager(), DATA_SCHEDULES: {}}, coord


class _FakeHass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


class _FakeManager:
    gateway_ids = {"gw1", "gw2"}

    def survey_heads(self, heads):
        assert list(heads) == ["dev1-head", "dev2-head", "dev3-head"]  # the heads, iterable
        return {
            "dev1": {"comfort": 21.0, "setback": 14.0},
            "dev2": {"unreachable": True},
            "dev3": {"unreachable": True, "not_read": True},
        }


class _FakeLocal:
    """Shaped like DanfossLocalCoordinator: ``heads`` is a METHOD there. A fake exposing it as a
    plain list hid the service passing the bound method to the manager (get_local_survey failed
    on a real install with "'method' object is not iterable")."""

    manager = _FakeManager()

    def heads(self):
        return ["dev1-head", "dev2-head", "dev3-head"]  # opaque to the fake manager

    def unaddressable(self):
        return {"dev4": "no_node_id", "dev5": "no_gateway_key"}


async def test_local_survey_disabled():
    """Without the local tunnel, local_survey raises the stable code local_disabled."""
    store, _ = _store()
    with pytest.raises(ops.OperationError) as exc:
        await ops.local_survey(_FakeHass(), store)
    assert exc.value.code == "local_disabled"


async def test_local_survey_ok():
    store, _ = _store()
    store[DATA_LOCAL] = _FakeLocal()
    res = await ops.local_survey(_FakeHass(), store)
    # Every head of the account is accounted for (real install: 91 attempted for 99 heads, the
    # eight others nowhere in the response).
    assert res["heads_total"] == 5
    assert res["attempted"] == 3
    assert res["reachable"] == 1  # dev2 did not answer, dev3 was not read in time
    assert res["not_read"] == 1
    assert res["not_addressable"] == {"dev4": "no_node_id", "dev5": "no_gateway_key"}
    assert set(res["heads"]) == {"dev1", "dev2", "dev3"}
    assert res["gateways"] == ["gw1", "gw2"]  # sorted
    assert res["heads"]["dev1"]["comfort"] == 21.0
    assert "surveyed_at" in res


class _FakeManagerW:
    """Write-side fake manager: the heads of _Coord sit on gateway 'gw-1'."""

    def __init__(self, gateways=("gw-1",)):
        self.gateway_ids = set(gateways)
        self.calls: list = []
        self.schedule: dict = {}

    def descale(self, head, day, hour):
        self.calls.append((head.dev_id, day, hour))
        return True

    def set_override(self, head, celsius):
        self.calls.append(("override", head.dev_id, celsius))
        return int(round(celsius * 100))

    def read_schedule(self, head):
        return self.schedule

    def write_window_detection(self, head, enabled):
        self.calls.append(("window", head.dev_id, enabled))
        return enabled


class _FakeLocalW:
    def __init__(self, gateways=("gw-1",)):
        self.manager = _FakeManagerW(gateways)


_DEVICE = {"type": "device", "id": "a"}


async def test_set_descaling_ok():
    store, _ = _store()
    local = _FakeLocalW()
    store[DATA_LOCAL] = local
    res = await ops.set_descaling(_FakeHass(), store, _DEVICE, "wed", "13:00")
    assert res["accepted"] is True and res["day"] == "wed" and res["time"] == "13:00"
    # "wed" mapped to the tunnel weekday name:
    assert local.manager.calls == [("a", "wednesday", "13:00")]


async def test_set_descaling_disabled():
    store, _ = _store()
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_descaling(_FakeHass(), store, _DEVICE, "wed", "13:00")
    assert exc.value.code == "local_disabled"


async def test_set_descaling_device_only():
    store, _ = _store()
    store[DATA_LOCAL] = _FakeLocalW()
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_descaling(_FakeHass(), store, _ROOM, "wed", "13:00")
    assert exc.value.code == "device_only"


async def test_set_descaling_unverified_product():
    store, coord = _store()
    coord.data["a"].product_id = "not-verified"
    store[DATA_LOCAL] = _FakeLocalW()
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_descaling(_FakeHass(), store, _DEVICE, "wed", "13:00")
    assert exc.value.code == "unverified_product"


async def test_set_descaling_unreachable():
    store, _ = _store()
    store[DATA_LOCAL] = _FakeLocalW(gateways=())  # head's gateway not reachable
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_descaling(_FakeHass(), store, _DEVICE, "wed", "13:00")
    assert exc.value.code == "local_unreachable"


async def test_set_descaling_invalid_day():
    store, _ = _store()
    store[DATA_LOCAL] = _FakeLocalW()
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_descaling(_FakeHass(), store, _DEVICE, "funday", "13:00")
    assert exc.value.code == "invalid_day"


async def test_set_descaling_invalid_time():
    store, _ = _store()
    store[DATA_LOCAL] = _FakeLocalW()
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_descaling(_FakeHass(), store, _DEVICE, "wed", "25:00")
    assert exc.value.code == "invalid_time"


async def test_set_descaling_write_refused():
    store, _ = _store()
    local = _FakeLocalW()

    def _boom(head, day, hour):
        raise tunnel.LocalError("refused")

    local.manager.descale = _boom
    store[DATA_LOCAL] = local
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_descaling(_FakeHass(), store, _DEVICE, "wed", "13:00")
    assert exc.value.code == "local_write_failed"


# --- C1: setpoint override ---------------------------------------------------------------------


def test_scheduled_setpoint_now_current_day():
    now = datetime(2026, 11, 16, 12, 0)
    wd = tunnel.WEEKDAYS[now.weekday()]
    days = {wd: [{"h": "06:00", "c": 21.0}, {"h": "22:00", "c": 17.0}]}
    assert ops._scheduled_setpoint_now(days, now) == 21.0
    assert ops._scheduled_setpoint_now(days, now.replace(hour=23)) == 17.0


def test_scheduled_setpoint_now_before_first_uses_prev_day():
    now = datetime(2026, 11, 16, 5, 0)
    wd = tunnel.WEEKDAYS[now.weekday()]
    prev = tunnel.WEEKDAYS[(now.weekday() - 1) % 7]
    days = {
        prev: [{"h": "07:00", "c": 20.0}, {"h": "21:00", "c": 16.0}],
        wd: [{"h": "06:00", "c": 21.0}],
    }
    assert ops._scheduled_setpoint_now(days, now) == 16.0


def test_scheduled_setpoint_now_empty():
    assert ops._scheduled_setpoint_now({}, datetime(2026, 11, 16, 12, 0)) is None


async def test_set_override_ok():
    store, _ = _store()
    local = _FakeLocalW()
    store[DATA_LOCAL] = local
    res = await ops.set_override(_FakeHass(), store, _DEVICE, 20.0)
    assert res["setpoint"] == 20.0 and res["published_raw"] == 2000
    assert local.manager.calls == [("override", "a", 20.0)]
    # R-3 (real hardware 2026-11-19: HA/MQTT took ~3 min): the head reports the tunnel write to
    # the cloud, so it is marked for the per-device read
    assert store[DATA_COORDINATOR].commanded == ["a"]


async def test_set_override_out_of_range():
    store, _ = _store()
    store[DATA_LOCAL] = _FakeLocalW()
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_override(_FakeHass(), store, _DEVICE, 40.0)
    assert exc.value.code == "invalid_setpoint"
    assert store[DATA_COORDINATOR].commanded == []  # nothing written, nothing marked


async def test_set_override_bad_step():
    store, _ = _store()
    store[DATA_LOCAL] = _FakeLocalW()
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_override(_FakeHass(), store, _DEVICE, 20.3)
    assert exc.value.code == "invalid_setpoint"


async def test_clear_override_ok():
    store, _ = _store()
    local = _FakeLocalW()
    now = datetime.now().astimezone()
    wd = tunnel.WEEKDAYS[now.weekday()]
    local.manager.schedule = {wd: [{"h": "00:00", "c": 18.5}]}
    store[DATA_LOCAL] = local
    res = await ops.clear_override(_FakeHass(), store, _DEVICE)
    assert res["restored_setpoint"] == 18.5
    assert local.manager.calls == [("override", "a", 18.5)]
    assert store[DATA_COORDINATOR].commanded == ["a"]  # R-3


async def test_clear_override_no_schedule():
    store, _ = _store()
    store[DATA_LOCAL] = _FakeLocalW()  # schedule = {}
    with pytest.raises(ops.OperationError) as exc:
        await ops.clear_override(_FakeHass(), store, _DEVICE)
    assert exc.value.code == "no_schedule"


# --- C3: window detection (local write) --------------------------------------------------------


async def test_set_window_detection_ok():
    store, _ = _store()
    local = _FakeLocalW()
    store[DATA_LOCAL] = local
    res = await ops.set_window_detection(_FakeHass(), store, _DEVICE, True)
    assert res["window_detection"] is True and res["published"] is True
    assert local.manager.calls == [("window", "a", True)]
    assert store[DATA_COORDINATOR].commanded == ["a"]  # R-3, as the window switch's local path


async def test_set_window_detection_disabled():
    store, _ = _store()
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_window_detection(_FakeHass(), store, _DEVICE, True)
    assert exc.value.code == "local_disabled"


# --- Lecture -----------------------------------------------------------------------------------


def test_rooms_payload_rooms_and_heads():
    store, _ = _store()
    rooms = ops.rooms_payload(store)["rooms"]
    assert len(rooms) == 1
    room = rooms[0]
    assert room["id"] == "13000000" and room["name"] == "Salle 1"
    assert room["comfort"] == 21.0 and room["setback"] == 14.0
    assert {h["device_id"] for h in room["heads"]} == {"a", "b"}
    assert any(h["inconsistent"] for h in room["heads"])  # b : at_home + DP172 0


def test_room_entry_live_climate_fields():
    """Axis D: _room_entry exposes the live climate + write affordances (read only)."""
    store, _ = _store()
    room = ops.rooms_payload(store)["rooms"][0]
    assert room["temperature"] == 20.4 and room["setpoint"] == 21.0
    assert room["mode"] == "at_home" and room["heating"] is True and room["online"] is True
    assert room["writable"] is True  # pid 03wvrwpv is verified
    assert room["climate_entity_id"] is None  # no entity registry in this fake


def test_head_state_carries_status_fields():
    """HeadState now carries battery/valve/window/lock/faults for the UI (all read only)."""
    store, _ = _store()
    head_a = next(h for h in ops.rooms_payload(store)["rooms"][0]["heads"] if h["device_id"] == "a")
    assert head_a["battery"] == 90.0
    assert head_a["valve_opening"] == 30
    assert head_a["window_open"] is False
    assert head_a["window_detection"] is True
    assert head_a["child_lock"] is False
    assert head_a["faults"] == []
    assert "heat_request" in head_a


async def test_get_schedule_cache_puis_refresh():
    store, coord = _store()
    await ops.get_schedule(store, _ROOM)
    await ops.get_schedule(store, _ROOM)
    assert coord.client.schedule_reads == 1  # servi par le cache
    await ops.get_schedule(store, _ROOM, refresh=True)
    assert coord.client.schedule_reads == 2


def test_validate_payload():
    assert ops.validate_payload({"mon": [{"start": "08:30", "end": "17:30"}]})["valid"] is True
    out = ops.validate_payload({"mon": [{"start": "17:30", "end": "08:30"}]})
    assert out["valid"] is False and out["errors"][0]["code"] == "empty_or_reversed"


# --- Write ------------------------------------------------------------------------------------


async def test_set_schedule_invalide_n_appelle_pas_le_client():
    store, coord = _store()
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_schedule(None, store, _ROOM, {"mon": [{"start": "17:30", "end": "08:30"}]})
    assert exc.value.code == "empty_or_reversed"
    assert coord.client.calls == []


async def test_set_schedule_grouped_head_refused():
    store, coord = _store()
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_schedule(None, store, {"type": "device", "id": "a"}, {"mon": []})
    assert exc.value.code == "grouped_device"
    assert coord.client.calls == []


async def test_set_schedule_success_creates_a_job():
    store, coord = _store()
    job = await ops.set_schedule(None, store, _ROOM, {"mon": [{"start": "08:30", "end": "17:30"}]})
    assert job["kind"] == "set_schedule" and job["status"] == "sent"
    assert {h["device_id"] for h in job["heads"]} == {"a", "b"}
    assert coord.client.calls[0][0] == "set"


async def test_restore_creates_a_job():
    store, coord = _store()
    job = await ops.restore_schedule(None, store, _ROOM)
    assert job["kind"] == "restore" and coord.client.calls[0][0] == "restore"


# --- Verification (DP 172, R6) and admin guard ------------------------------------------------


async def test_verify_job_restore_dp172():
    store, coord = _store()
    job = store[DATA_JOBS].create("restore", _ROOM, ["a", "b", "z"])  # z absent = injoignable
    await ops.verify_job(store, job)
    statuts = {h.device_id: h.status for h in job.heads}
    assert (
        statuts["a"] == "applied" and statuts["b"] == "mismatch" and statuts["z"] == "unreachable"
    )
    assert coord.refreshed is True


async def test_verify_job_set_schedule_unverified():
    store, _ = _store()
    job = store[DATA_JOBS].create("set_schedule", _ROOM, ["a"])
    await ops.verify_job(store, job)
    assert job.heads[0].status == "unverified"


async def test_ensure_admin(hass, hass_admin_user, hass_read_only_user):
    await ops.ensure_admin(hass, hass_admin_user.id)
    await ops.ensure_admin(hass, None)
    with pytest.raises(ops.OperationError) as exc:
        await ops.ensure_admin(hass, hass_read_only_user.id)
    assert exc.value.code == "not_admin"


# --- Schedule writes on an ISOLATED head (docs/isolated-head-schedule-writes.md) ----------------

_HEAD = {"type": "device", "id": "iso"}
_ONE_SLOT = {"mon": [{"start": "08:30", "end": "17:30"}]}


class _ModeManager:
    gateway_ids = {"gw-1"}

    def __init__(self, mode=None, error=None):
        self.mode = mode
        self.error = error
        self.reads: list = []

    def read_programming_mode(self, head):
        self.reads.append((head.dev_id, head.node_id, head.gateway_id))
        if self.error is not None:
            raise self.error
        return self.mode


class _ModeLocal:
    def __init__(self, manager):
        self.manager = manager


def _isolated_store(**head_kw):
    """A store with ONE isolated head ``iso``, by default following its schedule."""
    store, coord = _store(grouped=False)
    kw = {"mode": "at_home", "schedule_active": True, **head_kw}
    coord.data["iso"] = head("iso", "Local technique", **kw)
    return store, coord


async def test_set_schedule_isolated_head_following_its_schedule_is_written():
    store, coord = _isolated_store()
    job = await ops.set_schedule(None, store, _HEAD, _ONE_SLOT)  # no tunnel: cloud view only
    assert job["kind"] == "set_schedule"
    assert [h["device_id"] for h in job["heads"]] == ["iso"]
    assert coord.client.calls == [("set", _HEAD, _ONE_SLOT)]


@pytest.mark.parametrize(
    "head_kw",
    [
        {"mode": "manual"},  # the 2026-11-19 case: accepted, then manual at the comfort value
        {"mode": None},
        {"mode": "holiday"},
        {"online": False},
        {"schedule_active": False},  # cloud label says schedule, DP 172 says manual
    ],
)
async def test_set_schedule_isolated_head_not_following_refused(head_kw):
    store, coord = _isolated_store(**head_kw)
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_schedule(None, store, _HEAD, _ONE_SLOT)
    assert exc.value.code == "head_not_following_schedule"
    assert coord.client.calls == []  # nothing sent


async def test_set_schedule_isolated_head_unknown_refused():
    store, coord = _store(grouped=False)
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_schedule(None, store, {"type": "device", "id": "nope"}, _ONE_SLOT)
    assert exc.value.code == "unknown_target"
    assert coord.client.calls == []


async def test_set_schedule_isolated_head_tunnel_says_manual_refused():
    """The cloud's mode can be wrong: the head's own 0x0025 (bit 0 clear) wins when it answers."""
    store, coord = _isolated_store()
    manager = _ModeManager(mode=0x02)  # preheat bit alone: no schedule bit
    store[DATA_LOCAL] = _ModeLocal(manager)
    with pytest.raises(ops.OperationError) as exc:
        await ops.set_schedule(_FakeHass(), store, _HEAD, _ONE_SLOT)
    assert exc.value.code == "head_not_following_schedule"
    assert manager.reads == [("iso", "node-1", "gw-1")]
    assert coord.client.calls == []


@pytest.mark.parametrize(
    "manager",
    [
        _ModeManager(mode=0x03),  # schedule + preheat
        _ModeManager(mode=0x01),
        _ModeManager(mode=None),  # no answer: judged on the cloud alone
        _ModeManager(error=tunnel.LocalUnavailable("gateway down")),
        _ModeManager(error=tunnel.LocalError("bad frame")),
    ],
)
async def test_set_schedule_isolated_head_tunnel_lets_through(manager):
    store, coord = _isolated_store()
    store[DATA_LOCAL] = _ModeLocal(manager)
    await ops.set_schedule(_FakeHass(), store, _HEAD, _ONE_SLOT)
    assert coord.client.calls == [("set", _HEAD, _ONE_SLOT)]


async def test_set_schedule_isolated_head_not_addressable_skips_the_tunnel():
    store, coord = _isolated_store(mesh_id="gw-other")
    manager = _ModeManager(mode=0x00)
    store[DATA_LOCAL] = _ModeLocal(manager)
    await ops.set_schedule(_FakeHass(), store, _HEAD, _ONE_SLOT)
    assert manager.reads == []
    assert coord.client.calls == [("set", _HEAD, _ONE_SLOT)]


async def test_set_schedule_room_target_has_no_head_guard():
    """A room is written through its group whatever the mode of its heads (R4 handles manual)."""
    store, coord = _store()
    coord.data["a"].mode = "manual"
    manager = _ModeManager(mode=0x00)
    store[DATA_LOCAL] = _ModeLocal(manager)
    await ops.set_schedule(_FakeHass(), store, _ROOM, _ONE_SLOT)
    assert manager.reads == []
    assert coord.client.calls[0][0] == "set"


async def test_set_schedule_checked_skips_the_guard():
    store, coord = _isolated_store(mode="manual")
    await ops.set_schedule(None, store, _HEAD, _ONE_SLOT, checked=True)
    assert coord.client.calls == [("set", _HEAD, _ONE_SLOT)]


async def test_restore_schedule_isolated_head_refused():
    store, coord = _isolated_store()  # even a head following its schedule
    with pytest.raises(ops.OperationError) as exc:
        await ops.restore_schedule(None, store, _HEAD)
    assert exc.value.code == "isolated_restore_unproven"
    assert coord.client.calls == []


async def test_restore_schedule_grouped_head_keeps_its_own_refusal():
    store, coord = _store()
    with pytest.raises(ops.OperationError) as exc:
        await ops.restore_schedule(None, store, {"type": "device", "id": "a"})
    assert exc.value.code == "grouped_device"


async def test_restore_schedule_room_still_written():
    store, coord = _store()
    job = await ops.restore_schedule(None, store, _ROOM)
    assert job["kind"] == "restore" and coord.client.calls == [("restore", _ROOM)]
