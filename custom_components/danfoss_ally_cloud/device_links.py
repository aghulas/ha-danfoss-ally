"""Link each grouped head's device to its room device in the device registry.

A head that belongs to a Danfoss room shows up in HA as a sub-device of the room thermostat. This
used to be declared with ``DeviceInfo(via_device=(DOMAIN, "group_<id>"))``, deprecated in HA 2026
(removed in 2027.8); its replacement ``via_device_id`` takes the parent's *registry id*, which an
entity cannot know before the room device exists. So the link is set here, on the registry itself,
with ``async_update_device(via_device_id=...)`` - available on every supported HA version.

It runs once the platforms are set up (all devices exist) and again on each coordinator update, so
a head attached to / detached from a room follows. It only touches heads of this integration and
only clears a link that points to one of our room devices (a link set by the user or another
integration is left alone). Cheap: two indexed registry lookups per head.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import DanfossCoordinator

ROOM_PREFIX = "group_"


def _is_our_room(device: Any) -> bool:
    # Any: HA 2026 may return a ChildDeviceEntry (absent from older HA); only `identifiers` is read.
    return device is not None and any(
        domain == DOMAIN and ident.startswith(ROOM_PREFIX) for domain, ident in device.identifiers
    )


def find_device(registry: dr.DeviceRegistry, entry_id: str, ident: str) -> Any:
    """Our device with this identifier. HA 2026 scopes identifiers per config entry and
    deprecates ``async_get_device(identifiers=...)`` (removed 2027.8) for
    ``async_get_device_by_identifier``; older HA only has the former."""
    by_identifier = getattr(registry, "async_get_device_by_identifier", None)
    if by_identifier is not None:
        return by_identifier((DOMAIN, ident), entry_id)
    return registry.async_get_device(identifiers={(DOMAIN, ident)})


@callback
def async_link_heads_to_rooms(
    hass: HomeAssistant, coordinator: DanfossCoordinator, entry_id: str
) -> int:
    """Set (or clear) ``via_device_id`` of every head device. Returns the number of updates."""
    registry = dr.async_get(hass)
    updates = 0
    for head_id, dev in (coordinator.data or {}).items():
        if not dev.is_head:
            continue
        child = find_device(registry, entry_id, head_id)
        if child is None:
            continue
        group_id = coordinator.group_of(head_id)
        parent = (
            find_device(registry, entry_id, f"{ROOM_PREFIX}{group_id}")
            if group_id is not None
            else None
        )
        if group_id is not None and parent is None:
            continue  # room device not created yet: link on a later update, never unlink
        wanted = parent.id if parent is not None else None
        if child.via_device_id == wanted:
            continue
        if wanted is None:
            # Head no longer in a room: clear only a link that points to one of our rooms.
            current = registry.async_get(child.via_device_id) if child.via_device_id else None
            if not _is_our_room(current):
                continue
        registry.async_update_device(child.id, via_device_id=wanted)
        updates += 1
    return updates
