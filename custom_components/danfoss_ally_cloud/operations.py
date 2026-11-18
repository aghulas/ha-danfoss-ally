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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later

from .api import ScheduleValidationError, UnknownTargetError, head_state, write_allowed
from .api import schedule as sch
from .api.client import CloudError
from .api.local import tunnel
from .api.local.manager import Head
from .const import (
    DATA_COORDINATOR,
    DATA_JOBS,
    DATA_LOCAL,
    DATA_SCHEDULES,
    DOMAIN,
    WRITE_VERIFIED_PRODUCTS,
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


def _room_climate_entity_id(coordinator: DanfossCoordinator, group_id: str) -> str | None:
    """Entity id of the room thermostat (unique_id = group_id), or None if not registered.

    Lets the room card reuse the existing, already-validated ``climate.set_temperature`` instead of
    any new write path (contract §8.1). Best-effort: a missing registry just yields None.
    """
    try:
        registry = er.async_get(coordinator.hass)
    except Exception:  # noqa: BLE001 - never block a read on the registry
        return None
    return registry.async_get_entity_id("climate", DOMAIN, group_id)


def _room_entry(coordinator: DanfossCoordinator, group_id: str) -> dict:
    """One room payload (contract §3.4) from the aggregated RoomState + member head states."""
    rs = coordinator.rooms[group_id]
    return {
        "id": group_id,
        "name": rs.name,
        "product_id": rs.pid,
        "comfort": rs.setpoints.get("comfort"),
        "setback": rs.setpoints.get("setback"),
        "heads": _heads_of_room(coordinator, group_id),
        # Live climate (same values as the room thermostat) + the write affordances, read-only
        # (contract §3.4, axis D). No extra cloud call: all from the aggregated RoomState.
        "temperature": rs.temperature,
        "setpoint": rs.setpoint,
        "mode": rs.mode,
        "heating": rs.heating,
        "online": rs.online,
        "writable": rs.pid in WRITE_VERIFIED_PRODUCTS,
        "climate_entity_id": _room_climate_entity_id(coordinator, group_id),
    }


def rooms_payload(store: dict) -> dict:
    """Rooms (contract §3.4): RoomState from #12 + member head states (HeadState §3.3)."""
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    return {"rooms": [_room_entry(coordinator, gid) for gid in coordinator.rooms]}


def _low_battery_head(head: dict) -> bool:
    """A head is low on battery if a battery fault (E14/E15) is set, or battery <= 10 %."""
    codes = {str(f.get("code")) for f in head.get("faults", [])}
    if codes & {"E14", "E15"}:
        return True
    battery = head.get("battery")
    return battery is not None and battery <= 10


def _room_overview(coordinator: DanfossCoordinator, group_id: str) -> dict[str, Any]:
    """Per-room health counts for the fleet overview (contract §3.6)."""
    rs = coordinator.rooms[group_id]
    heads = _heads_of_room(coordinator, group_id)
    return {
        "id": group_id,
        "name": rs.name,
        "head_count": rs.head_count,
        "offline": sum(1 for h in heads if not h["online"]),
        "low_battery": sum(1 for h in heads if _low_battery_head(h)),
        "heating": bool(rs.heating) or any(h.get("heat_request") for h in heads),
        "window_open": any(h.get("window_open") for h in heads),
        "inconsistent": sum(1 for h in heads if h["inconsistent"]),
        "faults": sum(1 for h in heads if h["faults"]),
    }


def _home_gids(coordinator: DanfossCoordinator) -> list[str]:
    """Home gids present, from the room topology then the holiday reads (stable order)."""
    gids: list[str] = []
    for gid in coordinator.rooms:
        home = coordinator.home_of(gid)
        if home and home not in gids:
            gids.append(home)
    for gid in coordinator.holidays:
        if gid not in gids:
            gids.append(gid)
    return gids


def _relay_home_gid(coordinator: DanfossCoordinator, relay, home_gids: list[str]) -> str | None:
    """Best-effort home of a boiler relay. Exact for a single-home account (the common case).

    The cloud exposes no relay -> home link directly; with one home every relay belongs to it. With
    several, fall back to the home of a linked room when resolvable, else the first home.
    """
    if len(home_gids) == 1:
        return home_gids[0]
    for room in coordinator.relay_rooms.get(relay.id, []):
        home = coordinator.home_of(str(room.get("room_id")))
        if home:
            return home
    return home_gids[0] if home_gids else None


def overview_payload(store: dict) -> dict:
    """Building / fleet overview (contract §3.6). Read-only, from the coordinator cache only.

    No extra cloud call: homes, gateways, rooms and relays all come from the already-polled state.
    """
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    home_gids = _home_gids(coordinator)
    names = {gid: (h.get("name") or f"Home {gid}") for gid, h in coordinator.holidays.items()}
    gateways = [d for d in coordinator.data.values() if d.category == "gateway"]
    relays = [d for d in coordinator.data.values() if d.is_relay]

    primary = home_gids[0] if home_gids else None
    homes: list[dict[str, Any]] = []
    for gid in home_gids:
        rooms = [
            _room_overview(coordinator, group_id)
            for group_id in coordinator.rooms
            if coordinator.home_of(group_id) == gid
        ]
        home_relays = [
            {
                "device_id": d.id,
                "name": d.name,
                "on": d.relay_on,
                "online": d.online,
                "linked_rooms": sum(
                    1 for r in coordinator.relay_rooms.get(d.id, []) if r.get("linked")
                ),
            }
            for d in relays
            if _relay_home_gid(coordinator, d, home_gids) == gid
        ]
        # Gateways have no per-home link; attribute them to the primary home (exact for a
        # single-home account, the common case), none to the others.
        home_gateways = (
            [{"device_id": g.id, "name": g.name, "online": g.online} for g in gateways]
            if gid == primary
            else []
        )
        homes.append(
            {
                "gid": gid,
                "name": names.get(gid, f"Home {gid}"),
                "holiday_active": bool((coordinator.holidays.get(gid) or {}).get("active")),
                "gateways": home_gateways,
                "rooms": rooms,
                "relays": home_relays,
            }
        )

    totals = {
        "homes": len(homes),
        "gateways": len(gateways),
        "rooms": sum(len(h["rooms"]) for h in homes),
        "heads": sum(r["head_count"] for h in homes for r in h["rooms"]),
        "offline": sum(r["offline"] for h in homes for r in h["rooms"]),
        "low_battery": sum(r["low_battery"] for h in homes for r in h["rooms"]),
        "heating": sum(1 for h in homes for r in h["rooms"] if r["heating"]),
        "faults": sum(r["faults"] for h in homes for r in h["rooms"]),
        "relays_on": sum(1 for d in relays if d.relay_on),
    }
    return {"homes": homes, "totals": totals}


def holidays_payload(store: dict) -> dict:
    """Per-home holiday state (contract §3.4b/§5.2 ``get_holiday``). Read-only."""
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    return {
        "holidays": [
            {
                "home": h.get("name"),
                "gid": gid,
                "active": bool(h.get("active")),
                "detail": h.get("detail"),
            }
            for gid, h in coordinator.holidays.items()
        ]
    }


def relays_payload(store: dict) -> dict:
    """Boiler relays + their room linkage (contract §3.4c/§5.2 ``get_relays``). Read-only."""
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    return {
        "relays": [
            {
                "device_id": dev.id,
                "name": dev.name,
                "on": dev.relay_on,
                "online": dev.online,
                "rooms": coordinator.relay_rooms.get(dev.id, []),
            }
            for dev in coordinator.data.values()
            if dev.is_relay
        ]
    }


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


# --- Room management writes (contract §4.7, §5.2). Admin-gated by the callers; structural writes
# on the live account -> gated on real-hardware validation. ------------------------------------


async def _run_cloud_write(func, *args) -> Any:
    try:
        return await func(*args)
    except CloudError as err:
        raise OperationError("cloud_refused", str(err)) from err


async def _refresh_after_structural_write(coordinator) -> None:
    """Make a structural change visible now: drop the topology cache, then refresh.

    ``async_request_refresh`` alone re-reads device state but keeps the hourly-cached room topology,
    so a new/changed/removed room would stay invisible to ``get_rooms`` and the resolver until the
    next poll. Invalidating the topology first forces it to be re-read on this refresh.
    """
    coordinator.invalidate_topology()
    await coordinator.async_request_refresh()


def _room_target(target: dict) -> str:
    if target.get("type") != "room":
        raise OperationError("unknown_room", "this action targets a room")
    return str(target.get("id"))


def _validate_heads(coordinator, devices: list[str], *, require_verified: bool) -> None:
    if not devices:
        raise OperationError("empty_devices", "give at least one head")
    for dev_id in devices:
        dev = coordinator.data.get(dev_id)
        if dev is None or not dev.is_head:
            raise OperationError("unknown_head", f"head not found: {dev_id}")
        if require_verified and not write_allowed(dev):
            raise OperationError("unverified_product", f"write not verified for {dev_id}")


def _current_members(coordinator, group_id: str) -> list[str]:
    return [
        dev.id
        for dev in coordinator.data.values()
        if dev.is_head and coordinator.group_of(dev.id) == group_id
    ]


def _room_name_candidates(group_name: str) -> list[str]:
    """Room (type-4) name candidates for a schedule-group (type-5) name.

    Tuya auto-labels the implicit program-group ``"<room> Group"`` when a room is created through
    the API (observed on real hardware 2026-11-18): the schedule-group the integration tracks can
    carry that suffix while the room keeps the base name. We therefore match the room on the group
    name as read, and, failing that, on the group name with a trailing " Group" removed. Rooms
    created in the app keep identical names, so the first candidate already matches there.
    """
    name = (group_name or "").strip()
    candidates = [name]
    low = name.lower()
    if low.endswith(" group"):
        stripped = name[: -len(" group")].strip()
        if stripped and stripped not in candidates:
            candidates.append(stripped)
    return candidates


async def _resolve_room_id(coordinator, group_id: str) -> str:
    """Resolve the Tuya room id (type 4) for a schedule-group (type 5) the integration shows.

    By name (the only link the API exposes, contract §4.7), tolerant of the ``"<room> Group"``
    auto-label (``_room_name_candidates``). One room-map read.
    """
    rs = coordinator.rooms.get(group_id)
    home = coordinator.home_of(group_id)
    if rs is None or home is None:
        raise OperationError("unknown_room", f"room not found: {group_id}")
    rooms = await _run_cloud_write(coordinator.client.async_list_rooms, home)
    by_name = {(r.get("name") or "").strip().lower(): r["room_id"] for r in rooms}
    for candidate in _room_name_candidates(rs.name or ""):
        room_id = by_name.get(candidate.lower())
        if room_id is not None:
            return room_id
    raise OperationError("unknown_room", f"no Tuya room matching {rs.name!r}")


async def create_room(
    hass: HomeAssistant,
    store: dict,
    name: str,
    devices: list[str],
    home: str | None = None,
) -> dict:
    """Create a room and attach the given heads (contract §4.7). Verified products only.

    The room MUST be created in the home the heads belong to, otherwise the heads cannot join it and
    the room is left empty. ``home`` (a gid) selects it explicitly (the reliable path on a
    multi-home account, mirroring the app, which creates in the current home); when omitted the home
    is **inferred from the devices** and a single shared home must resolve, else ``ambiguous_home``
    (pass ``home``) or ``unknown_home``.
    """
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    _validate_heads(coordinator, devices, require_verified=True)
    gid = await _resolve_devices_home(coordinator, list(devices), home)
    room_id = await _run_cloud_write(coordinator.client.async_room_add, gid, name)
    await _run_cloud_write(coordinator.client.async_room_set_devices, room_id, list(devices))
    await _refresh_after_structural_write(coordinator)
    return {"room_id": str(room_id)}


async def _resolve_devices_home(
    coordinator, devices: list[str], explicit_home: str | None = None
) -> str:
    """The home gid to create the room in: explicit if given (validated), else inferred.

    Inference: the single home that contains ALL the devices. Raises ``unknown_home`` if a device is
    in no home (or the explicit gid is unknown) and ``ambiguous_home`` if no single home holds them
    all (heads span homes, or the backend did not filter the device list by gid) — never a silent
    guess, which would create the room in the wrong home.
    """
    homes = await _run_cloud_write(coordinator.client.async_get_homes)
    valid = {str(h["gid"]) for h in homes}
    if explicit_home is not None:
        gid = str(explicit_home)
        if gid not in valid:
            raise OperationError("unknown_home", f"home {explicit_home!r} not found in the account")
        return gid
    homes_of = await _run_cloud_write(coordinator.client.async_device_homes, devices)
    missing = [d for d, gids in homes_of.items() if not gids]
    if missing:
        raise OperationError("unknown_home", f"devices not found in any home: {missing}")
    common = set.intersection(*(set(gids) for gids in homes_of.values()))
    if len(common) == 1:
        return next(iter(common))
    raise OperationError(
        "ambiguous_home",
        "cannot determine a single home for these heads; pass 'home' (the gid) explicitly",
    )


async def rename_room(hass: HomeAssistant, store: dict, target: dict, name: str) -> dict:
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    room_id = await _resolve_room_id(coordinator, _room_target(target))
    await _run_cloud_write(coordinator.client.async_room_update, room_id, name)
    await _refresh_after_structural_write(coordinator)
    return {"room_id": str(room_id)}


async def delete_room(hass: HomeAssistant, store: dict, target: dict) -> dict:
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    room_id = await _resolve_room_id(coordinator, _room_target(target))
    await _run_cloud_write(coordinator.client.async_room_dismiss, room_id)
    await _refresh_after_structural_write(coordinator)
    return {"room_id": str(room_id)}


async def attach_heads(hass: HomeAssistant, store: dict, target: dict, devices: list[str]) -> dict:
    """Add heads to a room (contract §4.7). REPLACES the member list with current ∪ given."""
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    group_id = _room_target(target)
    _validate_heads(coordinator, devices, require_verified=True)
    room_id = await _resolve_room_id(coordinator, group_id)
    members = _current_members(coordinator, group_id)
    final = list(dict.fromkeys(members + list(devices)))
    await _run_cloud_write(coordinator.client.async_room_set_devices, room_id, final)
    await _refresh_after_structural_write(coordinator)
    return {"room_id": str(room_id), "heads": final, "previous_heads": members}


async def detach_heads(hass: HomeAssistant, store: dict, target: dict, devices: list[str]) -> dict:
    """Remove heads from a room (contract §4.7). Refuses to empty a room (use delete_room)."""
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    group_id = _room_target(target)
    _validate_heads(coordinator, devices, require_verified=False)  # removal: any known head
    room_id = await _resolve_room_id(coordinator, group_id)
    members = _current_members(coordinator, group_id)
    if not any(d in members for d in devices):
        raise OperationError("unknown_head", "none of these heads are in the room")
    final = [d for d in members if d not in devices]
    if not final:
        raise OperationError("no_members_left", "detaching every head: use delete_room instead")
    await _run_cloud_write(coordinator.client.async_room_set_devices, room_id, final)
    await _refresh_after_structural_write(coordinator)
    return {"room_id": str(room_id), "heads": final, "previous_heads": members}


async def set_relay_room(
    hass: HomeAssistant, store: dict, relay: str, target: dict, linked: bool
) -> dict:
    """Link / unlink a room to a boiler relay (contract §4.6). ⚠ Gated on real-hardware validation.

    The room is matched by name against the relay's eligible rooms (``relay_rooms`` cache), so its
    cloud ``roomId`` is used for the edit. Admin-gated by the caller.
    """
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    dev = coordinator.data.get(relay)
    if dev is None or not dev.is_relay:
        raise OperationError("unknown_relay", f"relay not found: {relay}")
    group_id = _room_target(target)
    rs = coordinator.rooms.get(group_id)
    if rs is None:
        raise OperationError("unknown_room", f"room not found: {group_id}")
    wanted = (rs.name or "").strip().lower()
    match = next(
        (
            r
            for r in (coordinator.relay_rooms.get(relay) or [])
            if (r.get("name") or "").strip().lower() == wanted
        ),
        None,
    )
    if match is None:
        raise OperationError("unknown_room", f"room {rs.name!r} is not eligible for this relay")
    await _run_cloud_write(
        coordinator.client.async_relay_bind, relay, match["room_id"], bool(linked)
    )
    await _refresh_after_structural_write(coordinator)
    return {"relay": relay, "room_id": str(match["room_id"]), "linked": bool(linked)}


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
    return {"target": target, "window_detection": bool(enabled), "published": published}


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
