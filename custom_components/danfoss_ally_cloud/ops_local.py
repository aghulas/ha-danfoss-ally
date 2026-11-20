"""Local Zigbee tunnel operations: survey, setpoint override, window detection, descaling."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from .api import schedule as sch
from .api.local import tunnel
from .api.local.manager import Head
from .const import DATA_COORDINATOR, DATA_LOCAL
from .ops_common import _HHMM, OperationError, _require_verified_head

if TYPE_CHECKING:
    from .coordinator import DanfossCoordinator


async def local_survey(hass: HomeAssistant, store: dict) -> dict:
    """Read-only multi-gateway survey through the local Zigbee tunnel (contract §4.4, C4)."""
    local = store.get(DATA_LOCAL)
    if local is None:
        raise OperationError("local_disabled", "local tunnel not enabled on this account")
    heads = local.heads()  # a method of DanfossLocalCoordinator, not an attribute
    not_addressable = local.unaddressable()
    summaries = await hass.async_add_executor_job(local.manager.survey_heads, heads)
    reachable = sum(1 for s in summaries.values() if not s.get("unreachable"))
    return {
        "surveyed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "gateways": sorted(local.manager.gateway_ids),
        "heads_total": len(summaries) + len(not_addressable),
        "attempted": len(summaries),
        "reachable": reachable,
        "not_read": sum(1 for s in summaries.values() if s.get("not_read")),
        "not_addressable": not_addressable,
        "heads": summaries,
    }


def _tunnel_head(coordinator: DanfossCoordinator, local, target: dict) -> Head:
    """Resolve a {type:"device", id} target to a tunnel-addressable Head, or raise."""
    dev = _require_verified_head(coordinator, target, not_found_code="unknown_target")
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


def _note_tunnel_write(coordinator: DanfossCoordinator, head: Head) -> None:
    """R-3 after a local-tunnel write that the head then reports to the cloud."""
    coordinator.note_commanded([head.dev_id])


def _scheduled_setpoint_now(schedule_days: dict[str, list[dict]], now: datetime) -> float | None:
    """The setpoint the weekly schedule prescribes at ``now`` (used to end an override)."""
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
    """C1 — set a one-off "now" setpoint override on a head via the tunnel (DP 171)."""
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
    _note_tunnel_write(coordinator, head)
    return {"target": target, "setpoint": temp, "published_raw": raw}


async def clear_override(hass: HomeAssistant, store: dict, target: dict) -> dict:
    """C1 — end a one-off override by re-applying the setpoint the schedule prescribes now."""
    local = _require_local(store)
    head = _tunnel_head(store[DATA_COORDINATOR], local, target)
    days = await _run_tunnel(hass, local.manager.read_schedule, head)
    setpoint = _scheduled_setpoint_now(days, datetime.now().astimezone())
    if setpoint is None:
        raise OperationError(
            "no_schedule", "no schedule to return to; the override lapses at the next change"
        )
    raw = await _run_tunnel(hass, local.manager.set_override, head, setpoint)
    _note_tunnel_write(store[DATA_COORDINATOR], head)
    return {"target": target, "restored_setpoint": setpoint, "published_raw": raw}


async def set_window_detection(
    hass: HomeAssistant, store: dict, target: dict, enabled: bool
) -> dict:
    """C3 — write a head's open-window detection (DP 116) through the local tunnel."""
    local = _require_local(store)
    head = _tunnel_head(store[DATA_COORDINATOR], local, target)
    published = await _run_tunnel(hass, local.manager.write_window_detection, head, bool(enabled))
    _note_tunnel_write(store[DATA_COORDINATOR], head)
    return {"target": target, "window_detection": bool(enabled), "published": published}


async def set_descaling(
    hass: HomeAssistant, store: dict, target: dict, day: str, hour: str
) -> dict:
    """C2 — set the head's weekly valve-descaling day/time via the local tunnel (contract §4.4)."""
    local = _require_local(store)
    head = _tunnel_head(store[DATA_COORDINATOR], local, target)
    if day not in sch.DAYS:
        raise OperationError("invalid_day", f"unknown day: {day}")
    if not _HHMM.match(hour or ""):
        raise OperationError("invalid_time", f"invalid time: {hour}")
    tunnel_day = tunnel.WEEKDAYS[sch.DAYS.index(day)]
    accepted = await _run_tunnel(hass, local.manager.descale, head, tunnel_day, hour)
    return {"target": target, "day": day, "time": hour, "accepted": accepted}
