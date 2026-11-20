"""Operations shared between the actions (services) and the WebSocket commands.

One implementation per operation (contract §5.3): rooms (with head states), schedule read / write,
back to schedule, room management, vacation writes, and local-tunnel commands. Split into domain
sub-modules (``ops_common``, ``ops_views``, ``ops_rooms``, ``ops_local``) and re-exported here.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from .api import (
    ScheduleValidationError,
    UnknownTargetError,
    encode_setpoint,
)
from .api import schedule as sch
from .api.client import CloudError
from .const import (
    DATA_COORDINATOR,
    DATA_JOBS,
    DATA_SCHEDULES,
    DATA_VACATION_WRITE,
    SETPOINT_MAX,
    SETPOINT_MIN,
)
from .ops_common import (  # noqa: F401
    _HHMM,
    OperationError,
    _refresh_after_structural_write,
    _require_verified_head,
    _room_target,
    _run_cloud_write,
    ensure_admin,
)
from .ops_local import (  # noqa: F401
    _note_tunnel_write,
    _require_local,
    _run_tunnel,
    _scheduled_setpoint_now,
    _tunnel_head,
    clear_override,
    local_survey,
    set_descaling,
    set_override,
    set_window_detection,
)
from .ops_rooms import (  # noqa: F401
    _current_members,
    _require_unbind,
    _require_unbindable_device,
    _resolve_devices_home,
    _resolve_room_id,
    _room_name_candidates,
    _validate_heads,
    attach_heads,
    create_room,
    delete_room,
    detach_heads,
    disconnect_head,
    rename_room,
    set_relay_room,
)
from .ops_views import (  # noqa: F401
    _gateway_carried,
    _gateway_home_gid,
    _gateway_overview,
    _heads_of_room,
    _home_by_room_name,
    _home_gids,
    _low_battery_head,
    _norm_name,
    _relay_home_gid,
    _room_climate_entity_id,
    _room_entry,
    _room_overview,
    _single_head_overview,
    _single_head_rooms,
    holidays_payload,
    overview_payload,
    relays_payload,
    rooms_payload,
)
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


async def get_room(store: dict, target: dict) -> dict:
    """One room's detail + its weekly schedule (contract §5.2 ``get_room``). Read-only."""
    if target.get("type") != "room":
        raise OperationError("unknown_room", "get_room targets a room")
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    group_id = str(target.get("id"))
    if group_id not in coordinator.rooms:
        raise OperationError("unknown_room", f"room not found: {group_id}")
    schedule = await get_schedule(store, target)
    return {"room": _room_entry(coordinator, group_id), "schedule": schedule}


# --- Vacation (holiday) writes (contract §4.5, §5.2). GATED: a vacation write acts on the live
# heating and its exact request shape is pending a real-hardware validation. Admin-gated by the
# callers AND behind the opt-in ``DATA_VACATION_WRITE`` flag (CONF_ENABLE_VACATION_WRITE). --------

_DATE_RE = re.compile(r"^\d{8}$")  # YYYYMMDD


def _require_vacation_write(store: dict) -> None:
    if not store.get(DATA_VACATION_WRITE):
        raise OperationError(
            "vacation_disabled",
            "vacation writes are disabled; enable them in the integration options "
            "(for a real-hardware validation session)",
        )


def _check_date(value: str, field: str) -> str:
    if not _DATE_RE.match(value or ""):
        raise OperationError("invalid_date", f"{field} must be YYYYMMDD")
    return value


def _check_time(value: str, field: str) -> str:
    if not _HHMM.match(value or ""):
        raise OperationError("invalid_time", f"{field} must be HH:MM")
    return value


def _vacation_temperature_tenths(temperature: float) -> int:
    """°C -> tenths, validated against the product bounds (reuses the setpoint encoder)."""
    try:
        return encode_setpoint(temperature, SETPOINT_MIN, SETPOINT_MAX)
    except Exception as err:  # noqa: BLE001 - map any value error to a stable contract code
        raise OperationError("invalid_setpoint", str(err)) from err


async def _resolve_vacation_rooms(coordinator, gid: str, rooms: list[dict] | None) -> list[str]:
    """Tuya room ids (type 4) the vacation applies to."""
    if rooms:
        out: list[str] = []
        for target in rooms:
            group_id = _room_target(target)
            if coordinator.home_of(group_id) != gid:
                raise OperationError("unknown_room", f"room {group_id} is not in home {gid}")
            out.append(await _resolve_room_id(coordinator, group_id))
        return out
    all_rooms = await _run_cloud_write(coordinator.client.async_list_rooms, gid)
    ids = [str(r["room_id"]) for r in all_rooms if r.get("room_id") is not None]
    if not ids:
        raise OperationError("empty_rooms", f"home {gid} has no room for a vacation")
    return ids


async def _resolve_home(coordinator, home: str) -> str:
    homes = await _run_cloud_write(coordinator.client.async_get_homes)
    valid = {str(h["gid"]) for h in homes}
    gid = str(home)
    if gid not in valid:
        raise OperationError("unknown_home", f"home {home!r} not found in the account")
    return gid


def _at_home_target_groups(coordinator, gid: str, rooms: list[dict] | None) -> list[str]:
    """Schedule-group ids the at-home Saturday pre-check must inspect."""
    if rooms:
        groups: list[str] = []
        for target in rooms:
            group_id = _room_target(target)
            if group_id not in coordinator.rooms or coordinator.home_of(group_id) != gid:
                raise OperationError("unknown_room", f"room {group_id} is not in home {gid}")
            groups.append(group_id)
        return groups
    return [g for g in coordinator.rooms if coordinator.home_of(g) == gid]


async def _ensure_saturday_program(store: dict, group_ids: list[str]) -> None:
    """Reproduce the app's client-side guard for at-home vacations (field-confirmed 2026-11)."""
    for group_id in group_ids:
        schedule = await get_schedule(store, {"type": "room", "id": group_id})
        if schedule.get("days", {}).get("sat"):
            return
    raise OperationError(
        "at_home_no_saturday",
        "the at-home option makes heads follow the Saturday schedule, but no targeted room has a "
        "Saturday slot; add a Saturday slot or use a fixed setpoint (away)",
    )


async def set_vacation(
    hass: HomeAssistant,
    store: dict,
    home: str,
    start_date: str,
    start_time: str,
    end_date: str,
    end_time: str,
    temperature: float,
    rooms: list[dict] | None = None,
    time_zone: str = "Europe/Paris",
) -> dict:
    """Set / edit an *away* vacation on a home (contract §4.5, ``vacation.plan.leave``). GATED."""
    _require_vacation_write(store)
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    gid = await _resolve_home(coordinator, home)
    _check_date(start_date, "start_date")
    _check_time(start_time, "start_time")
    _check_date(end_date, "end_date")
    _check_time(end_time, "end_time")
    if (end_date, end_time) <= (start_date, start_time):
        raise OperationError("invalid_vacation_period", "the end must be after the start")
    tenths = _vacation_temperature_tenths(temperature)
    room_ids = await _resolve_vacation_rooms(coordinator, gid, rooms)
    await _run_cloud_write(
        coordinator.client.async_vacation_leave,
        gid,
        start_date,
        start_time,
        end_date,
        end_time,
        tenths,
        room_ids,
        time_zone,
    )
    await _refresh_after_structural_write(coordinator)
    return {
        "home": gid,
        "mode": "away",
        "start": f"{start_date} {start_time}",
        "end": f"{end_date} {end_time}",
        "temperature": tenths / 10,
        "rooms": room_ids,
    }


async def set_vacation_at_home(
    hass: HomeAssistant,
    store: dict,
    home: str,
    start_date: str,
    end_date: str,
    rooms: list[dict] | None = None,
    time_zone: str = "Europe/Paris",
) -> dict:
    """Set / edit an *at-home* vacation (contract §4.5, ``vacation.plan.athome``). GATED."""
    _require_vacation_write(store)
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    gid = await _resolve_home(coordinator, home)
    _check_date(start_date, "start_date")
    _check_date(end_date, "end_date")
    if end_date < start_date:
        raise OperationError("invalid_vacation_period", "the end must not be before the start")
    await _ensure_saturday_program(store, _at_home_target_groups(coordinator, gid, rooms))
    room_ids = await _resolve_vacation_rooms(coordinator, gid, rooms)
    await _run_cloud_write(
        coordinator.client.async_vacation_athome, gid, start_date, end_date, room_ids, time_zone
    )
    await _refresh_after_structural_write(coordinator)
    return {"home": gid, "mode": "at_home", "start": start_date, "end": end_date, "rooms": room_ids}


async def cancel_vacation(
    hass: HomeAssistant, store: dict, home: str, time_zone: str = "Europe/Paris"
) -> dict:
    """Cancel a *planned* vacation before it starts (contract §4.5, ``vacation.cancel``). GATED."""
    _require_vacation_write(store)
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    gid = await _resolve_home(coordinator, home)
    await _run_cloud_write(coordinator.client.async_vacation_cancel, gid, time_zone)
    await _refresh_after_structural_write(coordinator)
    return {"home": gid, "cancelled": True}


async def end_vacation(
    hass: HomeAssistant,
    store: dict,
    home: str,
    temperature: float,
    rooms: list[dict] | None = None,
    time_zone: str = "Europe/Paris",
) -> dict:
    """End an *in-progress* vacation now (contract §4.5, ``vacation.leave.now``). GATED."""
    _require_vacation_write(store)
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    gid = await _resolve_home(coordinator, home)
    tenths = _vacation_temperature_tenths(temperature)
    room_ids = await _resolve_vacation_rooms(coordinator, gid, rooms)
    await _run_cloud_write(
        coordinator.client.async_vacation_leave_now, gid, room_ids, tenths, time_zone
    )
    await _refresh_after_structural_write(coordinator)
    return {"home": gid, "ended": True, "temperature": tenths / 10, "rooms": room_ids}


# --- Weekly schedule read / validate / write / job verification ----------------------------------


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
    head_ids = _head_ids(store, target)
    store[DATA_COORDINATOR].note_commanded(head_ids)  # R-3: freshen these heads post-command
    job = jobs.create("set_schedule", target, head_ids)
    _defer_verification(hass, store, job)
    return job.to_dict()


async def restore_schedule(hass: HomeAssistant, store: dict, target: dict) -> dict:
    jobs: JobManager = store[DATA_JOBS]
    _check_not_grouped(store, target)
    await _run_write(store[DATA_COORDINATOR].client.async_restore_schedule, target)
    _invalidate(store, target)
    head_ids = _head_ids(store, target)
    store[DATA_COORDINATOR].note_commanded(head_ids)  # R-3: freshen these heads post-command
    job = jobs.create("restore", target, head_ids)
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
    """Verify a job: DP 172 for the mode (R6); schedule = `unverified`."""
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
