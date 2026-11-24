"""Room management writes, boiler relay room binding, and sub-device unbind (contract §4.6–§4.7)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

from .api import write_allowed
from .const import DATA_COORDINATOR, DATA_HEAD_UNBIND
from .ops_common import (
    OperationError,
    _refresh_after_structural_write,
    _require_cloud_client,
    _room_target,
    _run_cloud_write,
)

if TYPE_CHECKING:
    from .coordinator import DanfossCoordinator


# --- Room management writes (contract §4.7, §5.2). Admin-gated by the callers; structural writes
# on the live account -> gated on real-hardware validation. ------------------------------------


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


def _require_room_cloud_client(store: dict):
    return _require_cloud_client(store, "room_management_companion_unsupported", "room management")


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
    client = _require_room_cloud_client(store)
    coordinator = store[DATA_COORDINATOR]
    _validate_heads(coordinator, devices, require_verified=True)
    gid = await _resolve_devices_home(coordinator, list(devices), home)
    room_id = await _run_cloud_write(client.async_room_add, gid, name)
    await _run_cloud_write(client.async_room_set_devices, room_id, list(devices))
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
    client = _require_room_cloud_client(store)
    coordinator = store[DATA_COORDINATOR]
    room_id = await _resolve_room_id(coordinator, _room_target(target))
    await _run_cloud_write(client.async_room_update, room_id, name)
    await _refresh_after_structural_write(coordinator)
    return {"room_id": str(room_id)}


async def delete_room(hass: HomeAssistant, store: dict, target: dict) -> dict:
    client = _require_room_cloud_client(store)
    coordinator = store[DATA_COORDINATOR]
    room_id = await _resolve_room_id(coordinator, _room_target(target))
    await _run_cloud_write(client.async_room_dismiss, room_id)
    await _refresh_after_structural_write(coordinator)
    return {"room_id": str(room_id)}


async def attach_heads(hass: HomeAssistant, store: dict, target: dict, devices: list[str]) -> dict:
    """Add heads to a room (contract §4.7). REPLACES the member list with current ∪ given."""
    client = _require_room_cloud_client(store)
    coordinator = store[DATA_COORDINATOR]
    group_id = _room_target(target)
    _validate_heads(coordinator, devices, require_verified=True)
    room_id = await _resolve_room_id(coordinator, group_id)
    members = _current_members(coordinator, group_id)
    final = list(dict.fromkeys(members + list(devices)))
    await _run_cloud_write(client.async_room_set_devices, room_id, final)
    await _refresh_after_structural_write(coordinator)
    return {"room_id": str(room_id), "heads": final, "previous_heads": members}


async def detach_heads(hass: HomeAssistant, store: dict, target: dict, devices: list[str]) -> dict:
    """Remove heads from a room (contract §4.7). Refuses to empty a room (use delete_room)."""
    client = _require_room_cloud_client(store)
    coordinator = store[DATA_COORDINATOR]
    group_id = _room_target(target)
    _validate_heads(coordinator, devices, require_verified=False)  # removal: any known head
    room_id = await _resolve_room_id(coordinator, group_id)
    members = _current_members(coordinator, group_id)
    if not any(d in members for d in devices):
        raise OperationError("unknown_head", "none of these heads are in the room")
    final = [d for d in members if d not in devices]
    if not final:
        raise OperationError("no_members_left", "detaching every head: use delete_room instead")
    await _run_cloud_write(client.async_room_set_devices, room_id, final)
    await _refresh_after_structural_write(coordinator)
    return {"room_id": str(room_id), "heads": final, "previous_heads": members}


async def set_relay_room(
    hass: HomeAssistant, store: dict, relay: str, target: dict, linked: bool
) -> dict:
    """Link / unlink a room to a boiler relay (contract §4.6). ⚠ Gated on real-hardware validation.

    The room is matched by name against the relay's eligible rooms (``relay_rooms`` cache), so its
    cloud ``roomId`` is used for the edit. Admin-gated by the caller.
    """
    client = _require_cloud_client(store, "relay_companion_unsupported", "boiler relay binding")
    coordinator = store[DATA_COORDINATOR]
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
    await _run_cloud_write(client.async_relay_bind, relay, match["room_id"], bool(linked))
    await _refresh_after_structural_write(coordinator)
    return {"relay": relay, "room_id": str(match["room_id"]), "linked": bool(linked)}


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
    client = _require_cloud_client(store, "unbind_companion_unsupported", "device unbind")
    coordinator = store[DATA_COORDINATOR]
    dev = _require_unbindable_device(coordinator, target)
    dev_id = dev.id
    if not confirm:
        raise OperationError(
            "confirmation_required",
            "destructive action: pass confirm=true to unbind this device",
        )
    wipe = bool(wipe_data)
    await _run_cloud_write(client.async_device_reset, dev_id, wipe)
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
