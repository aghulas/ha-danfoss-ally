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

from .api import (
    ScheduleValidationError,
    UnknownTargetError,
    encode_setpoint,
    head_state,
    write_allowed,
)
from .api import schedule as sch
from .api.client import CloudError
from .api.local import tunnel
from .api.local.manager import Head
from .const import (
    DATA_COORDINATOR,
    DATA_HEAD_UNBIND,
    DATA_JOBS,
    DATA_LOCAL,
    DATA_SCHEDULES,
    DATA_VACATION_WRITE,
    DOMAIN,
    SETPOINT_MAX,
    SETPOINT_MIN,
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
    from .api import DanfossDevice
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


async def ensure_admin(
    hass: HomeAssistant, user_id: str | None, *, allow_internal: bool = True
) -> None:
    """Refuse a non-admin user (contract §5.2). None = internal call, allowed by default.

    ``allow_internal=False`` additionally refuses a user-less call (``user_id is None``): used by
    ``disconnect_head``, the most destructive write, so that an unattended automation/script cannot
    unbind a head without a real administrator in context (opt-in + confirm are not enough there).
    """
    if user_id is None:
        if allow_internal:
            return
        raise OperationError("not_admin", "this action requires an administrator user")
    user = await hass.auth.async_get_user(user_id)
    if user is None or not user.is_admin:
        raise OperationError("not_admin", "write reserved for administrators")


def _require_verified_head(
    coordinator: DanfossCoordinator, target: dict, *, not_found_code: str = "unknown_head"
):
    """Resolve a ``{type:"device", id}`` target to a known, write-verified head, or raise.

    The target-safety sequence shared by writes that address a single head (contract write-safety):
    the target must be ``type=device``, a known head, of a write-verified product. The
    ``not_found_code`` arg lets each caller keep its own stable code for an unknown target
    (``unknown_head`` for the
    head writes, ``unknown_target`` for the local tunnel) — observable behaviour unchanged. Returns
    the resolved ``DanfossDevice``.
    """
    if target.get("type") != "device":
        raise OperationError("device_only", "this write targets a head (type=device)")
    dev = coordinator.data.get(str(target.get("id")))
    if dev is None or not dev.is_head:
        raise OperationError(not_found_code, f"head not found: {target.get('id')}")
    if not write_allowed(dev):
        raise OperationError("unverified_product", "write not verified for this product")
    return dev


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
        "kind": "group",
        "head_count": rs.head_count,
        "online": rs.online,
        "offline": sum(1 for h in heads if not h["online"]),
        "low_battery": sum(1 for h in heads if _low_battery_head(h)),
        "heating": bool(rs.heating) or any(h.get("heat_request") for h in heads),
        "window_open": any(h.get("window_open") for h in heads),
        "inconsistent": sum(1 for h in heads if h["inconsistent"]),
        "faults": sum(1 for h in heads if h["faults"]),
        "temperature": rs.temperature,
        "setpoint": rs.setpoint,
    }


def _single_head_overview(dev: DanfossDevice, room: dict | None) -> dict[str, Any]:
    """A single-head room (a head with no schedule-group) for the fleet overview (contract §3.6).

    Same health fields as a grouped room, over its one head. ``room`` is the app room (type 4)
    matched by name, or None: the name then falls back to the head's own name
    (``name_source: "head"``).
    """
    h = head_state(dev)
    return {
        "id": dev.id,
        "name": room["name"] if room else dev.name,
        "kind": "single_head",
        "name_source": "room" if room else "head",
        "room_id": room["room_id"] if room else None,
        "head_id": dev.id,
        "head_name": dev.name,
        "head_count": 1,
        "online": bool(dev.online),
        "offline": 0 if dev.online else 1,
        "low_battery": 1 if _low_battery_head(h) else 0,
        "heating": bool(dev.online and dev.heating) or bool(h.get("heat_request")),
        "window_open": bool(h.get("window_open")),
        "inconsistent": 1 if h["inconsistent"] else 0,
        "faults": 1 if h["faults"] else 0,
        "temperature": dev.temperature if dev.online else None,
        "setpoint": dev.setpoint,
    }


def _single_head_rooms(
    coordinator: DanfossCoordinator, home_gids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """Single-head rooms per home gid: every head that belongs to no schedule-group.

    A room of the app with one head has no schedule-group (type 5), so it is absent from
    ``coordinator.rooms``. Its home is exact (the per-home device list). Its app room cannot be read
    from the cloud (the room membership is empty, contract §3.6), so it is matched **by name**: a
    room of the same home whose normalised name equals the head's, not already claimed by a
    schedule-group nor by another single head. Otherwise the head's name is used, flagged.
    A head of unknown home goes to the first home (kept visible and counted rather than dropped).
    """
    singles = [
        dev
        for dev in coordinator.data.values()
        if dev.is_head and coordinator.group_of(dev.id) is None
    ]
    by_home: dict[str, list[DanfossDevice]] = {}
    for dev in singles:
        home = coordinator.head_home(dev.id)
        if home not in home_gids:
            home = home_gids[0] if home_gids else None
        if home is not None:
            by_home.setdefault(home, []).append(dev)

    out: dict[str, list[dict[str, Any]]] = {}
    for home, devs in by_home.items():
        # A room already named by a schedule-group of this home (with or without the " Group"
        # label Tuya adds to an API-created room, §4.7) is not a single head's room.
        claimed = {
            key
            for group_id, rs in coordinator.rooms.items()
            if coordinator.home_of(group_id) == home
            for key in (_norm_name(rs.name), _norm_name(rs.name.removesuffix(" Group")))
        }
        candidates: dict[str, list[dict]] = {}
        for app_room in coordinator.home_rooms.get(home, []):
            key = _norm_name(app_room.get("name"))
            if key and key not in claimed:
                candidates.setdefault(key, []).append(app_room)
        wanted: dict[str, int] = {}
        for dev in devs:
            key = _norm_name(dev.name)
            wanted[key] = wanted.get(key, 0) + 1
        entries = []
        for dev in devs:
            key = _norm_name(dev.name)
            match = candidates.get(key, [])
            # Unambiguous only: one room of that name, wanted by this head alone.
            room: dict | None = None
            if len(match) == 1 and wanted[key] == 1:
                room = {"room_id": str(match[0]["room_id"]), "name": match[0]["name"]}
            entries.append(_single_head_overview(dev, room))
        out[home] = entries
    return out


def _home_gids(coordinator: DanfossCoordinator) -> list[str]:
    """Home gids present, from the room topology, the holiday reads, then the heads' homes."""
    gids: list[str] = []
    for gid in coordinator.rooms:
        home = coordinator.home_of(gid)
        if home and home not in gids:
            gids.append(home)
    for gid in coordinator.holidays:
        if gid not in gids:
            gids.append(gid)
    for dev in coordinator.data.values():
        home = coordinator.head_home(dev.id) if dev.is_head else None
        if home and home not in gids:
            gids.append(home)
    return gids


def _norm_name(name: Any) -> str:
    """Room name key for matching: case-folded, alphanumerics only ("D-0 Hall" = "D0 Hall")."""
    return "".join(ch for ch in str(name or "").casefold() if ch.isalnum())


def _home_by_room_name(coordinator: DanfossCoordinator) -> dict[str, str | None]:
    """Normalised room name -> home gid, from the schedule-group topology.

    A name found in several homes maps to None (ambiguous: it must not vote).
    """
    out: dict[str, str | None] = {}
    for group_id, room in coordinator.rooms.items():
        key = _norm_name(room.name)
        home = coordinator.home_of(group_id)
        if not key or not home:
            continue
        out[key] = home if out.get(key, home) == home else None
    return out


def _relay_home_gid(
    coordinator: DanfossCoordinator,
    relay,
    home_gids: list[str],
    home_by_name: dict[str, str | None],
) -> str | None:
    """Home of a boiler relay, by majority vote of the rooms that drive it.

    The relay -> room link (``relay_rooms``) carries Tuya *room* ids (type 4), a different id space
    from the schedule *groups* (type 5) that ``home_of`` knows, so rooms are matched by name (the
    same rule as group <-> room elsewhere). Names do not always match exactly ("D0" / "D-0", typos),
    hence a vote over all the linked rooms rather than the first one. Linked rooms vote; if none is
    linked, all listed rooms do. With a single home every relay belongs to it. Unresolvable: first
    home (kept visible rather than dropped).
    """
    if len(home_gids) == 1:
        return home_gids[0]
    listed = coordinator.relay_rooms.get(relay.id, [])
    voters = [r for r in listed if r.get("linked")] or listed
    votes: dict[str, int] = {}
    for room in voters:
        home = coordinator.home_of(str(room.get("room_id"))) or home_by_name.get(
            _norm_name(room.get("name"))
        )
        if home:
            votes[home] = votes.get(home, 0) + 1
    if votes:
        # Highest vote wins; ties go to the earlier home (stable, deterministic).
        order = {gid: i for i, gid in enumerate(home_gids)}
        return min(votes, key=lambda gid: (-votes[gid], order.get(gid, len(order))))
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
    home_by_name = _home_by_room_name(coordinator)
    singles = _single_head_rooms(coordinator, home_gids)
    homes: list[dict[str, Any]] = []
    for gid in home_gids:
        rooms = [
            _room_overview(coordinator, group_id)
            for group_id in coordinator.rooms
            if coordinator.home_of(group_id) == gid
        ] + singles.get(gid, [])
        rooms.sort(key=lambda r: (str(r["name"]).casefold(), r["id"]))
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
            if _relay_home_gid(coordinator, d, home_gids, home_by_name) == gid
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
        # An offline relay's on/off is its last known (stale) state: not counted as on.
        "relays_on": sum(1 for d in relays if d.relay_on and d.online),
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
                "active": h.get("active"),
                "scheduled": h.get("scheduled"),
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
    """Tuya room ids (type 4) the vacation applies to.

    ``rooms`` is an optional list of room targets ({type:"room", id:group_id}); each is resolved to
    its Tuya room id (``_resolve_room_id``). When omitted, the vacation covers EVERY room of the
    home (what the app does). Raises ``empty_rooms`` if the home has none.
    """
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
    """Schedule-group ids the at-home Saturday pre-check must inspect.

    Explicit ``rooms`` (group targets) are validated against the home; omitted = every room the
    integration tracks in that home. These are the ids whose *weekly schedule* is read (an at-home
    vacation makes a head follow its Saturday program), distinct from the Tuya room ids sent in the
    request body (``_resolve_vacation_rooms``).
    """
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
    """Reproduce the app's client-side guard for at-home vacations (field-confirmed 2026-11).

    An at-home vacation makes each head follow its **Saturday** schedule; when NO targeted room has
    a Saturday slot the cloud answers a bare, cryptic ``REMOTE_API_RUN_UNKNOW_FAILED`` ("the server
    is busy"). We pre-read each target room's weekly schedule (``tuya.m.custom.wkf.week.timer.list``
    via ``get_schedule``) and refuse with a clear error BEFORE any send if none has a Saturday
    window.
    """
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
    """Set / edit an *at-home* vacation (contract §4.5, ``vacation.plan.athome``). GATED.

    No temperature: each head follows its Saturday schedule. A client-side pre-check refuses with
    ``at_home_no_saturday`` when no targeted room has a Saturday slot (the cloud otherwise answers a
    cryptic ``REMOTE_API_RUN_UNKNOW_FAILED``), mirroring the app's own guard.
    """
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


# --- Sub-device UNBIND / "disconnect" (contract write-safety). The most DESTRUCTIVE cloud write:
# the device leaves the Zigbee network and disappears from the account; re-pairing needs a physical
# action on site. Scope (widened 2026-11-18, mirroring the MCP connector PR #7): ANY sub-device —
# head, sensor, relay or other — but a GATEWAY is REFUSED (unbinding it would drop all its heads at
# once). Unbind is a Tuya-generic call keyed on the category, NOT on a verified product, so the
# head-only ``write_allowed`` gate does not apply here; the safety is the category check plus the
# triple gate: opt-in (DATA_HEAD_UNBIND, OFF by default), admin with allow_internal=False (caller),
# AND an explicit ``confirm`` flag — no one-click path. Captured/validated on real hardware via the
# MCP connector (2026-11-18); validation THROUGH this integration is still pending. ----------------


def _require_unbind(store: dict) -> None:
    if not store.get(DATA_HEAD_UNBIND):
        raise OperationError(
            "unbind_disabled",
            "head unbind is disabled; enable it in the integration options "
            "(for a supervised real-hardware validation session)",
        )


def _require_unbindable_device(coordinator: DanfossCoordinator, target: dict):
    """Resolve a ``{type:"device", id}`` target to a known, UNBINDABLE sub-device, or raise.

    Mirrors the MCP connector: the target must be ``type=device`` (``device_only``) and a known
    device (``unknown_target``); a GATEWAY is refused (``gateway_target``) because unbinding it
    would drop every head it carries. Any other category — head, sensor, relay, or other
    sub-device — is accepted. No verified-product gate: unbind is a Tuya-generic call keyed on the
    category, so the head-only ``write_allowed`` check (local-tunnel writes) must NOT block a
    legitimate sensor/relay. Returns the resolved ``DanfossDevice``.
    """
    if target.get("type") != "device":
        raise OperationError("device_only", "disconnect_head targets a sub-device (type=device)")
    dev = coordinator.data.get(str(target.get("id")))
    if dev is None:
        raise OperationError("unknown_target", f"device not found: {target.get('id')}")
    if dev.category == "gateway":
        raise OperationError(
            "gateway_target",
            "refused: this is a gateway — unbinding it would drop all its heads; "
            "unbind targets a sub-device (head, sensor, relay)",
        )
    return dev


async def disconnect_head(
    hass: HomeAssistant,
    store: dict,
    target: dict,
    wipe_data: bool = False,
    confirm: bool = False,
) -> dict:
    """Unbind (disconnect) a sub-device via ``smartlife.m.device.reset``. ⚠ DESTRUCTIVE.

    Scope: any sub-device — head, sensor, relay or other — but a GATEWAY is refused. The name
    ``disconnect_head`` is kept for backward compatibility (the service shipped head-only); it now
    covers every detachable sub-device, mirroring the MCP connector.

    Gates, in order: opt-in flag (``unbind_disabled``), target is a known non-gateway sub-device
    (``device_only`` / ``unknown_target`` / ``gateway_target``), and an explicit ``confirm=True``
    (``confirmation_required``) so it can never fire by accident. The caller also enforces admin
    (``allow_internal=False``). No verified-product gate (category-generic call).

    ``wipe_data`` (= ``resetFactory``): ``False`` = "disconnect" (identity kept; re-added on its own
    gateway without a wipe, the device returns with the SAME devId); ``True`` = "disconnect and wipe
    data" (factory reset — a NEW devId, identity/name LOST, IRREVERSIBLE on the identity). In both
    cases re-pairing needs a physical action on site (permit-join is MQTT, not path 1a).
    """
    _require_unbind(store)
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    dev = _require_unbindable_device(coordinator, target)
    dev_id = dev.id
    if not confirm:
        raise OperationError(
            "confirmation_required",
            "destructive action: pass confirm=true to unbind this device",
        )
    wipe = bool(wipe_data)
    await _run_cloud_write(coordinator.client.async_device_reset, dev_id, wipe)
    await _refresh_after_structural_write(coordinator)
    return {
        "device_id": dev_id,
        "name": dev.name,
        "category": dev.category,
        "mode": "disconnect_and_wipe" if wipe else "disconnect",
        "wipe_data": wipe,
        "irreversible": wipe,
        "consequences": [
            "the device left the Zigbee network and is gone from the account",
            "re-pairing requires a physical action on the device, on site (not drivable from here)",
            (
                "data wiped: it will return with a NEW devId — identity and name LOST "
                "(irreversible)"
                if wipe
                else "identity kept: re-added on its gateway without a wipe, it returns with the "
                "same devId and name (rediscovery)"
            ),
            "a head's room membership is lost and must be reassigned after re-pairing",
        ],
    }


async def local_survey(hass: HomeAssistant, store: dict) -> dict:
    """Read-only multi-gateway survey through the local Zigbee tunnel (contract §4.4, C4).

    Returns, per reachable head, the tunnel reading summarized (comfort slots, comfort/setback
    setpoints, decoded attributes). Read-only: it never writes to a head. Raises
    ``local_disabled`` if the local tunnel is not enabled on this entry.
    """
    local = store.get(DATA_LOCAL)
    if local is None:
        raise OperationError("local_disabled", "local tunnel not enabled on this account")
    heads = local.heads()  # a method of DanfossLocalCoordinator, not an attribute
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
