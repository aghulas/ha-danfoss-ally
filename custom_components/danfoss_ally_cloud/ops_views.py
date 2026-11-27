"""Read-only fleet and room payloads for services and WebSocket commands (contract §3.4–§3.6)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers import entity_registry as er

from .api import head_state
from .const import DATA_COORDINATOR, DOMAIN, WRITE_VERIFIED_PRODUCTS

if TYPE_CHECKING:
    from .api import DanfossDevice
    from .coordinator import DanfossCoordinator


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
    companion = getattr(coordinator, "companion", None)
    writable = rs.pid in WRITE_VERIFIED_PRODUCTS or (
        companion is not None and companion.is_coordinator_room(group_id)
    )
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
        "writable": writable,
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
    """Home of a boiler relay: its own home when known, else a vote of the rooms that drive it.

    The per-home device list (``head_home``) is exact and wins: the direct-cloud coordinator reads
    it from the account, and ``danfoss2mqtt`` publishes it per device (``danfoss.home_id``). It is
    the only source under the v2 Companion while no bridge has published ``bridge/relays`` (its
    ``relay_rooms`` is then empty): without it every relay fell back to the first home. The vote
    below is the fallback when that home is unknown.

    The relay -> room link (``relay_rooms``) carries Tuya *room* ids (type 4), a different id space
    from the schedule *groups* (type 5) that ``home_of`` knows, so rooms are matched by name (the
    same rule as group <-> room elsewhere). Names do not always match exactly ("D0" / "D-0", typos),
    hence a vote over all the linked rooms rather than the first one. Linked rooms vote; if none is
    linked, all listed rooms do. With a single home every relay belongs to it. Unresolvable: first
    home (kept visible rather than dropped).
    """
    if len(home_gids) == 1:
        return home_gids[0]
    own = coordinator.head_home(relay.id)
    if own in home_gids:
        return own
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


def _gateway_carried(coordinator: DanfossCoordinator, gateway) -> list[DanfossDevice]:
    """Sub-devices a gateway carries (``mesh_id`` = the gateway): heads, relays, sensors."""
    return [
        dev
        for dev in coordinator.data.values()
        if dev.mesh_id == gateway.id and dev.id != gateway.id
    ]


def _gateway_home_gid(coordinator: DanfossCoordinator, gateway, home_gids: list[str]) -> str | None:
    """Home of a gateway: the home of the sub-devices it carries (``mesh_id`` = the gateway).

    Each sub-device's home is exact (per-home device list); they all vote (heads, relays, sensors:
    a gateway may carry a boiler relay and no head), a tie going to the earlier home. A gateway
    carrying nothing of a known home falls back to its own entry in the per-home device lists,
    then to the first home (kept visible rather than dropped).
    """
    order = {gid: i for i, gid in enumerate(home_gids)}
    votes: dict[str, int] = {}
    for dev in _gateway_carried(coordinator, gateway):
        home = coordinator.head_home(dev.id)
        if home in order:
            votes[home] = votes.get(home, 0) + 1
    if votes:
        return min(votes, key=lambda gid: (-votes[gid], order[gid]))
    own = coordinator.head_home(gateway.id)
    if own in order:
        return own
    return home_gids[0] if home_gids else None


def _gateway_overview(coordinator: DanfossCoordinator, gateway) -> dict[str, Any]:
    carried = _gateway_carried(coordinator, gateway)
    return {
        "device_id": gateway.id,
        "name": gateway.name,
        "online": gateway.online,
        # What the gateway carries: tells why it sits under a home (e.g. no head, one relay).
        "head_count": sum(1 for d in carried if d.is_head),
        "relay_count": sum(1 for d in carried if d.is_relay),
    }


def _sensor_rooms(coordinator: DanfossCoordinator) -> dict[str, str]:
    """Room sensor id -> group id of its room, where the coordinator knows the link.

    Only the v2 Companion view does (``sensor_rooms``): the direct-cloud coordinator reads no
    sensor -> room link, so its sensors are listed with ``room_id`` None rather than guessed.
    """
    lookup = getattr(coordinator, "sensor_rooms", None)
    return dict(lookup()) if callable(lookup) else {}


def _sensor_home_gid(
    coordinator: DanfossCoordinator, sensor, room_id: str | None, home_gids: list[str]
) -> str | None:
    """Home of a room sensor: its own home, else its room's, else the first (kept visible)."""
    own = coordinator.head_home(sensor.id)
    if own in home_gids:
        return own
    via_room = coordinator.home_of(room_id) if room_id else None
    if via_room in home_gids:
        return via_room
    return home_gids[0] if home_gids else None


def _sensor_overview(sensor, room_id: str | None) -> dict[str, Any]:
    """A room sensor for the fleet overview (contract §3.6). Read only.

    Offline, the cloud keeps the last readings: temperature and humidity are then None (stale, not
    shown), like a head's temperature. The battery is kept: it does not go stale within hours.
    """
    return {
        "device_id": sensor.id,
        "name": sensor.name,
        "online": bool(sensor.online),
        "room_id": room_id,
        "temperature": sensor.temperature if sensor.online else None,
        "humidity": sensor.humidity if sensor.online else None,
        "battery": sensor.battery,
    }


def overview_payload(store: dict) -> dict:
    """Building / fleet overview (contract §3.6). Read-only, from the coordinator cache only.

    No extra cloud call: homes, gateways, rooms and relays all come from the already-polled state.
    """
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    home_gids = _home_gids(coordinator)
    names = {gid: (h.get("name") or f"Home {gid}") for gid, h in coordinator.holidays.items()}
    gateways = [d for d in coordinator.data.values() if d.category == "gateway"]
    relays = [d for d in coordinator.data.values() if d.is_relay]
    sensors = [d for d in coordinator.data.values() if d.is_sensor]
    sensor_rooms = _sensor_rooms(coordinator)
    sensor_home = {
        s.id: _sensor_home_gid(coordinator, s, sensor_rooms.get(s.id), home_gids) for s in sensors
    }

    home_by_name = _home_by_room_name(coordinator)
    gateway_home = {g.id: _gateway_home_gid(coordinator, g, home_gids) for g in gateways}
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
                # Names of the rooms that drive the relay, for its page (contract §3.6). These are
                # Tuya *room* names, not schedule-group ids: shown as text, never used as targets.
                "linked_room_names": sorted(
                    (
                        str(r.get("name"))
                        for r in coordinator.relay_rooms.get(d.id, [])
                        if r.get("linked") and r.get("name")
                    ),
                    key=str.casefold,
                ),
            }
            for d in relays
            if _relay_home_gid(coordinator, d, home_gids, home_by_name) == gid
        ]
        home_gateways = [
            _gateway_overview(coordinator, g) for g in gateways if gateway_home[g.id] == gid
        ]
        homes.append(
            {
                "gid": gid,
                "name": names.get(gid, f"Home {gid}"),
                "holiday_active": bool((coordinator.holidays.get(gid) or {}).get("active")),
                "gateways": home_gateways,
                "rooms": rooms,
                "relays": home_relays,
                "sensors": [
                    _sensor_overview(s, sensor_rooms.get(s.id))
                    for s in sensors
                    if sensor_home[s.id] == gid
                ],
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
        "sensors": len(sensors),
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
