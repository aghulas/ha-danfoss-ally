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
    """Read-only multi-gateway survey through the local Zigbee tunnel (contract §4.4, C4).

    Returns, per head, the tunnel reading summarized (comfort slots, comfort/setback setpoints,
    decoded attributes). Read-only: it never writes to a head. Raises ``local_disabled`` if the
    local tunnel is not enabled on this entry.

    Every head of the account is accounted for: ``heads_total`` = ``attempted`` (addressable
    through the tunnel, each one present in ``heads``) + the heads listed in ``not_addressable``
    (head id -> ``no_node_id`` / ``no_gateway_key``). Among the attempted ones, ``reachable``
    answered and ``not_read`` were not asked because the survey ran out of time (flagged
    ``not_read`` in ``heads``); the others did not answer.
    """
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
    """Resolve a {type:"device", id} target to a tunnel-addressable Head, or raise.

    Guards shared by every local-tunnel write (contract write-safety): the target must be an
    isolated head (type=device), of a write-verified product, with a known Zigbee node and a
    gateway the local manager can reach. Errors are stable contract codes.
    """
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
    """R-3 after a local-tunnel write that the head then reports to the cloud.

    The write itself does not go through the cloud, but the head reports the new value (DP 171
    setpoint, DP 116 window detection) to the cloud in under a minute, where the per-device route
    sees it while the bulk route lags: on real hardware (2026-11-19) HA and MQTT took ~2.5-3 min to
    follow. Marking the head makes the next polls (90 s) read it per device for the R-3 window, so
    the change shows up one poll after the cloud has it. Cost: a few per-device reads of one head.
    No-op unless the post-command refresh option is on; never optimistic.
    """
    coordinator.note_commanded([head.dev_id])


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
    _note_tunnel_write(coordinator, head)
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
    _note_tunnel_write(store[DATA_COORDINATOR], head)
    return {"target": target, "restored_setpoint": setpoint, "published_raw": raw}


async def set_window_detection(
    hass: HomeAssistant, store: dict, target: dict, enabled: bool
) -> dict:
    """C3 — write a head's open-window detection (DP 116) through the local tunnel.

    The cloud switch already reads/sets DP 116 via the cloud; this is the LOCAL write path (the
    authoritative read is attribute 0x4051, via the local survey).
    """
    local = _require_local(store)
    head = _tunnel_head(store[DATA_COORDINATOR], local, target)
    published = await _run_tunnel(hass, local.manager.write_window_detection, head, bool(enabled))
    _note_tunnel_write(store[DATA_COORDINATOR], head)
    return {"target": target, "window_detection": bool(enabled), "published": published}


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
