"""Operations shared between the actions (services) and the WebSocket commands.

One implementation per operation (contract §5.3): rooms (with head states), schedule read / write,
back to schedule. Built on the room model of PR #12 (`coordinator.rooms` = RoomState,
`coordinator.group_of`) and on the schedule editing of the `api/` layer (R1 validation). Writes
create a `WriteJob` tracked by `jobs/subscribe` and verified in a deferred way (never blocking).
Errors = stable contract codes (§5.4).

The durable room setpoint is NOT here: it is carried by the room thermostat (PR #12,
`climate.async_set_temperature` -> `async_set_group_setpoint`).
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from .api import ScheduleValidationError, UnknownTargetError, head_state, write_allowed
from .api import schedule as sch
from .api.client import CloudError
from .api.local import tunnel
from .api.local.manager import Head
from .const import DATA_COORDINATOR, DATA_JOBS, DATA_LOCAL, DATA_SCHEDULES
from .writejob import (
    HEAD_APPLIED,
    HEAD_MISMATCH,
    HEAD_UNREACHABLE,
    HEAD_UNVERIFIED,
    JobManager,
    WriteJob,
)

if TYPE_CHECKING:
    from .coordinator import DanfossCoordinator

_LOGGER = logging.getLogger(__name__)

VERIFY_DELAY = 300  # deferred verification 5 min later (R7); never blocks
SCHEDULE_TTL = 3600  # per-target schedule cache (read on demand)


class OperationError(Exception):
    """Error carrying a stable contract code (§5.4), translated by the wrappers."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        errors: list[dict] | None = None,
        day: str | None = None,
    ) -> None:
        self.code = code
        self.errors = errors
        self.day = day
        super().__init__(message or code)


async def ensure_admin(hass: HomeAssistant, user_id: str | None) -> None:
    """Refuse a non-admin user (contract §5.2). None = internal call, allowed."""
    if user_id is None:
        return
    user = await hass.auth.async_get_user(user_id)
    if user is None or not user.is_admin:
        raise OperationError("not_admin", "write reserved for administrators")


def _heads_of_room(coordinator: DanfossCoordinator, group_id: str) -> list[dict]:
    return [
        head_state(dev, group_id)
        for dev in coordinator.data.values()
        if dev.is_head and coordinator.group_of(dev.id) == group_id
    ]


def rooms_payload(store: dict) -> dict:
    """Rooms (contract §3.4): RoomState from #12 + member head states (HeadState §3.3)."""
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    rooms = [
        {
            "id": gid,
            "name": rs.name,
            "product_id": rs.pid,
            "comfort": rs.setpoints.get("comfort"),
            "setback": rs.setpoints.get("setback"),
            "heads": _heads_of_room(coordinator, gid),
        }
        for gid, rs in coordinator.rooms.items()
    ]
    return {"rooms": rooms}


async def local_survey(hass: HomeAssistant, store: dict) -> dict:
    """Read-only multi-gateway survey through the local Zigbee tunnel (contract §4.4, C4).

    Returns, per reachable head, the tunnel reading summarized (comfort slots, comfort/setback
    setpoints, decoded attributes). Read-only: it never writes to a head. Raises
    ``local_disabled`` if the local tunnel is not enabled on this entry.
    """
    local = store.get(DATA_LOCAL)
    if local is None:
        raise OperationError("local_disabled", "local tunnel not enabled on this account")
    heads = local.heads
    summaries = await hass.async_add_executor_job(local.manager.survey_heads, heads)
    reachable = sum(1 for s in summaries.values() if not s.get("unreachable"))
    return {
        "surveyed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "gateways": sorted(local.manager.gateway_ids),
        "attempted": len(summaries),
        "reachable": reachable,
        "heads": summaries,
    }


def _tunnel_head(coordinator: DanfossCoordinator, local, target: dict) -> Head:
    """Resolve a {type:"device", id} target to a tunnel-addressable Head, or raise.

    Guards shared by every local-tunnel write (contract write-safety): the target must be an
    isolated head (type=device), of a write-verified product, with a known Zigbee node and a
    gateway the local manager can reach. Errors are stable contract codes.
    """
    if target.get("type") != "device":
        raise OperationError("device_only", "a local tunnel write targets a head (type=device)")
    dev = coordinator.data.get(str(target.get("id")))
    if dev is None or not dev.is_head:
        raise OperationError("unknown_target", f"head not found: {target.get('id')}")
    if not write_allowed(dev):
        raise OperationError("unverified_product", "write not verified for this product")
    if not dev.node_id or not dev.mesh_id or dev.mesh_id not in local.manager.gateway_ids:
        raise OperationError("local_unreachable", "head not reachable through the local tunnel")
    return Head(dev.id, dev.node_id, dev.mesh_id)


def _require_local(store: dict):
    local = store.get(DATA_LOCAL)
    if local is None:
        raise OperationError("local_disabled", "local tunnel not enabled on this account")
    return local


async def _run_tunnel(hass: HomeAssistant, func, *args) -> Any:
    """Run a blocking tunnel read/write off-thread, mapping tunnel errors to contract codes."""
    try:
        return await hass.async_add_executor_job(func, *args)
    except tunnel.LocalUnavailable as err:
        raise OperationError("local_unreachable", str(err)) from err
    except tunnel.LocalError as err:
        raise OperationError("local_write_failed", str(err)) from err


def _scheduled_setpoint_now(schedule_days: dict[str, list[dict]], now: datetime) -> float | None:
    """The setpoint the weekly schedule prescribes at ``now`` (used to end an override).

    ``schedule_days``: ``{tunnel-weekday: [{"h": "HH:MM", "c": float}]}`` (tunnel.read_schedule);
    the weekday index matches ``datetime.weekday()``, Monday = 0. Within the current day the active
    transition is the last whose time <= now; before the first transition of the day, the most
    recent prior day's last transition applies (contract R1). None if the schedule is empty.
    """
    order = tunnel.WEEKDAYS  # monday .. sunday (index 0 = Monday, as datetime.weekday())
    idx = now.weekday()
    hhmm = now.strftime("%H:%M")
    today = schedule_days.get(order[idx]) or []
    active = [t for t in today if t["h"] <= hhmm]
    if active:
        return float(active[-1]["c"])
    for back in range(1, 8):  # walk back to the most recent day that has a transition
        prev = schedule_days.get(order[(idx - back) % 7]) or []
        if prev:
            return float(prev[-1]["c"])
    return None


async def set_override(hass: HomeAssistant, store: dict, target: dict, temperature: float) -> dict:
    """C1 — set a one-off "now" setpoint override on a head via the tunnel (DP 171).

    Outside the schedule: an override until the head's next scheduled change (not a durable
    setpoint; see contract R3/R5). Value validated against the head's own bounds.
    """
    local = _require_local(store)
    coordinator = store[DATA_COORDINATOR]
    head = _tunnel_head(coordinator, local, target)
    dev = coordinator.data[head.dev_id]
    low = dev.min_setpoint if dev.min_setpoint is not None else 5.0
    high = dev.max_setpoint if dev.max_setpoint is not None else 35.0
    temp = float(temperature)
    if not (low <= temp <= high) or round(temp * 2) != temp * 2:
        raise OperationError("invalid_setpoint", f"setpoint out of range ({low}-{high} °C, by 0.5)")
    raw = await _run_tunnel(hass, local.manager.set_override, head, temp)
    return {"target": target, "setpoint": temp, "published_raw": raw}


async def clear_override(hass: HomeAssistant, store: dict, target: dict) -> dict:
    """C1 — end a one-off override by re-applying the setpoint the schedule prescribes now.

    Reads the head's schedule through the tunnel and writes (DP 171) the value active at this
    moment, so the head immediately shows its scheduled temperature (the override then matches the
    schedule and lapses at the next scheduled change — the lever used to restore in the C0 trial).
    """
    local = _require_local(store)
    head = _tunnel_head(store[DATA_COORDINATOR], local, target)
    days = await _run_tunnel(hass, local.manager.read_schedule, head)
    setpoint = _scheduled_setpoint_now(days, datetime.now().astimezone())
    if setpoint is None:
        raise OperationError(
            "no_schedule", "no schedule to return to; the override lapses at the next change"
        )
    raw = await _run_tunnel(hass, local.manager.set_override, head, setpoint)
    return {"target": target, "restored_setpoint": setpoint, "published_raw": raw}


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


async def set_descaling(
    hass: HomeAssistant, store: dict, target: dict, day: str, hour: str
) -> dict:
    """C2 — set the head's weekly valve-descaling day/time via the local tunnel (contract §4.4).

    ``day`` is a 3-letter key ("mon".."sun", as the schedule services use); ``hour`` is "HH:MM".
    """
    local = _require_local(store)
    head = _tunnel_head(store[DATA_COORDINATOR], local, target)
    if day not in sch.DAYS:
        raise OperationError("invalid_day", f"unknown day: {day}")
    if not _HHMM.match(hour or ""):
        raise OperationError("invalid_time", f"invalid time: {hour}")
    tunnel_day = tunnel.WEEKDAYS[sch.DAYS.index(day)]
    accepted = await _run_tunnel(hass, local.manager.descale, head, tunnel_day, hour)
    return {"target": target, "day": day, "time": hour, "accepted": accepted}


def validate_payload(days: dict) -> dict:
    errors = sch.validate_days(days)
    return {
        "valid": not errors,
        "errors": errors,
        "transitions": sch.transitions_per_day(days),
    }


def _key(target: dict) -> str:
    return f"{target.get('type')}:{target.get('id')}"


async def get_schedule(store: dict, target: dict, refresh: bool = False) -> dict:
    """A target's schedule: cache (<= 1 h) or cloud if `refresh` / cache stale."""
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    cache: dict = store[DATA_SCHEDULES]
    key = _key(target)
    cached = cache.get(key)
    if not refresh and cached is not None and (time.monotonic() - cached[1]) < SCHEDULE_TTL:
        return cached[0]
    try:
        schedule = await coordinator.client.async_get_schedule(target)
    except UnknownTargetError as err:
        raise OperationError("unknown_target", str(err)) from err
    except CloudError as err:
        raise OperationError("cloud_refused", str(err)) from err
    cache[key] = (schedule, time.monotonic())
    return schedule


def _invalidate(store: dict, target: dict) -> None:
    store[DATA_SCHEDULES].pop(_key(target), None)


def _head_ids(store: dict, target: dict) -> list[str]:
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    if target.get("type") == "room":
        gid = str(target.get("id"))
        return [
            dev.id
            for dev in coordinator.data.values()
            if dev.is_head and coordinator.group_of(dev.id) == gid
        ]
    return [str(target.get("id"))]


def _check_not_grouped(store: dict, target: dict) -> None:
    """A grouped head targeted directly is refused: target its room (contract §5.4)."""
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    if target.get("type") == "device" and coordinator.group_of(str(target.get("id"))) is not None:
        raise OperationError("grouped_device", "grouped head: target its room")


async def set_schedule(hass: HomeAssistant, store: dict, target: dict, days: dict) -> dict:
    jobs: JobManager = store[DATA_JOBS]
    _check_not_grouped(store, target)
    errors = sch.validate_days(days)
    if errors:
        raise OperationError(errors[0]["code"], errors[0]["message"], errors, errors[0].get("day"))
    await _run_write(store[DATA_COORDINATOR].client.async_set_schedule_days, target, days)
    _invalidate(store, target)
    job = jobs.create("set_schedule", target, _head_ids(store, target))
    _defer_verification(hass, store, job)
    return job.to_dict()


async def restore_schedule(hass: HomeAssistant, store: dict, target: dict) -> dict:
    jobs: JobManager = store[DATA_JOBS]
    _check_not_grouped(store, target)
    await _run_write(store[DATA_COORDINATOR].client.async_restore_schedule, target)
    _invalidate(store, target)
    job = jobs.create("restore", target, _head_ids(store, target))
    _defer_verification(hass, store, job)
    return job.to_dict()


async def _run_write(func, *args) -> None:
    try:
        await func(*args)
    except ScheduleValidationError as err:
        first = err.errors[0]
        raise OperationError(first["code"], first["message"], err.errors, first.get("day")) from err
    except UnknownTargetError as err:
        raise OperationError("unknown_target", str(err)) from err
    except CloudError as err:
        raise OperationError("cloud_refused", str(err)) from err


def _defer_verification(hass: HomeAssistant, store: dict, job: WriteJob) -> None:
    """Schedule the verification 5 min later (R7). Never blocks the call."""

    async def _run(_now) -> None:
        try:
            await verify_job(store, job)
        except Exception as err:  # noqa: BLE001 - verification must never propagate
            _LOGGER.debug("verification of job %s: %s", job.job_id, err)

    async_call_later(hass, VERIFY_DELAY, _run)


async def verify_job(store: dict, job: WriteJob) -> None:
    """Verify a job: DP 172 for the mode (R6); schedule = `unverified`.

    The local re-read of the schedule (via the tunnel) is a separate follow-up, proven at the real
    validation of writes: we never claim `applied` without having observed it.
    """
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    jobs: JobManager = store[DATA_JOBS]
    await coordinator.async_request_refresh()
    devices = coordinator.data
    for head in job.heads:
        dev = devices.get(head.device_id)
        if dev is None or not dev.online:
            jobs.set_head(job, head.device_id, HEAD_UNREACHABLE)
            continue
        if job.kind == "restore":
            ok = dev.schedule_active is True
            jobs.set_head(job, head.device_id, HEAD_APPLIED if ok else HEAD_MISMATCH)
        else:  # set_schedule: schedule re-read not done in cloud-only
            jobs.set_head(
                job, head.device_id, HEAD_UNVERIFIED, "schedule not re-read (local tunnel required)"
            )
