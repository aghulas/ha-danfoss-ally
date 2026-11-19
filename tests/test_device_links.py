"""Head -> room device links on the registry (via_device_id), replacing DeviceInfo.via_device.

Synthetic data only.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud.const import DOMAIN
from custom_components.danfoss_ally_cloud.device_links import async_link_heads_to_rooms

from .common import head, relay


class _Coord:
    """Minimal coordinator: heads (data) and head -> room membership."""

    def __init__(self, data, groups):
        self.data = data
        self._groups = groups

    def group_of(self, head_id):
        return self._groups.get(head_id)


def _setup(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    reg = dr.async_get(hass)

    def device(ident: str):
        return reg.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={(DOMAIN, ident)}
        )

    return entry, reg, device


async def test_grouped_head_is_linked_to_its_room(hass: HomeAssistant):
    entry, reg, device = _setup(hass)
    room = device("group_g1")
    child = device("h1")
    coord = _Coord({"h1": head("h1")}, {"h1": "g1"})

    assert async_link_heads_to_rooms(hass, coord, entry.entry_id) == 1
    assert reg.async_get(child.id).via_device_id == room.id
    # Idempotent: a second pass writes nothing.
    assert async_link_heads_to_rooms(hass, coord, entry.entry_id) == 0


async def test_head_leaving_its_room_is_unlinked(hass: HomeAssistant):
    entry, reg, device = _setup(hass)
    room = device("group_g1")
    child = device("h1")
    reg.async_update_device(child.id, via_device_id=room.id)
    coord = _Coord({"h1": head("h1")}, {})  # no longer in a room

    assert async_link_heads_to_rooms(hass, coord, entry.entry_id) == 1
    assert reg.async_get(child.id).via_device_id is None


async def test_moving_to_another_room_relinks(hass: HomeAssistant):
    entry, reg, device = _setup(hass)
    room1, room2 = device("group_g1"), device("group_g2")
    child = device("h1")
    reg.async_update_device(child.id, via_device_id=room1.id)

    async_link_heads_to_rooms(hass, _Coord({"h1": head("h1")}, {"h1": "g2"}), entry.entry_id)
    assert reg.async_get(child.id).via_device_id == room2.id


async def test_foreign_link_is_left_alone(hass: HomeAssistant):
    entry, reg, device = _setup(hass)
    other = reg.async_get_or_create(config_entry_id=entry.entry_id, identifiers={("other", "hub")})
    child = device("h1")
    reg.async_update_device(child.id, via_device_id=other.id)

    assert async_link_heads_to_rooms(hass, _Coord({"h1": head("h1")}, {}), entry.entry_id) == 0
    assert reg.async_get(child.id).via_device_id == other.id


async def test_room_device_not_created_yet_waits(hass: HomeAssistant):
    entry, reg, device = _setup(hass)
    room1 = device("group_g1")
    child = device("h1")
    reg.async_update_device(child.id, via_device_id=room1.id)
    # Head now in g2, whose device does not exist yet: keep the current link, never unlink.
    assert (
        async_link_heads_to_rooms(hass, _Coord({"h1": head("h1")}, {"h1": "g2"}), entry.entry_id)
        == 0
    )
    assert reg.async_get(child.id).via_device_id == room1.id


async def test_non_heads_and_unknown_devices_are_skipped(hass: HomeAssistant):
    entry, reg, device = _setup(hass)
    device("group_g1")
    r = device("r1")
    coord = _Coord({"r1": relay("r1"), "h9": head("h9")}, {"r1": "g1", "h9": "g1"})
    # The relay is not a head; h9 has no device in the registry: nothing to do.
    assert async_link_heads_to_rooms(hass, coord, entry.entry_id) == 0
    assert reg.async_get(r.id).via_device_id is None
