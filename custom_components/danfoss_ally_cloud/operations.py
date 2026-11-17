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
import time
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from .api import ScheduleValidationError, UnknownTargetError, head_state
from .api import schedule as sch
from .api.client import CloudError
from .const import DATA_COORDINATOR, DATA_JOBS, DATA_SCHEDULES
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
