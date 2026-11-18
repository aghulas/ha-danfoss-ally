"""Axis B — room management writes (B5). Fakes only, no network, synthetic data."""

from unittest.mock import patch

import pytest

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud.api.client import CloudClient
from custom_components.danfoss_ally_cloud.api.rooms import RoomState
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR

from .common import head
from .test_client_async import FakeHttp

_HTTP = "custom_components.danfoss_ally_cloud.api.client.TuyaHttpClient"
_ROOM = {"type": "room", "id": "g1"}


# --- client payloads ---------------------------------------------------------------------------


def _client():
    return CloudClient("u", "p", "33", "sk", "dev", "ck", sid="s", ecode="e")


async def test_room_add_returns_id():
    fake = FakeHttp({"smartlife.m.room.add": {"id": 4242}})
    with patch(_HTTP, return_value=fake):
        assert await _client().async_room_add(1, "Classroom") == "4242"
    assert fake.calls[0][2] == {"gid": 1, "name": "Classroom"}


async def test_room_set_devices_replaces_list():
    fake = FakeHttp({"smartlife.m.custom.wkf.device.relations.selected.save": {"ok": True}})
    with patch(_HTTP, return_value=fake):
        await _client().async_room_set_devices(10, ["a", "b"])
    body = fake.calls[0][2]
    assert body["parentId"] == 10 and body["parentType"] == 4
    assert body["bizs"] == [{"id": "a", "type": 6}, {"id": "b", "type": 6}]


# --- operations --------------------------------------------------------------------------------


class _FakeClient:
    def __init__(self, homes=None, room_id="r1", room_map=None):
        self.calls: list = []
        self._homes = homes or [{"gid": "home-1", "name": "H"}]
        self._room_id = room_id
        # Room map (type-4 rooms); default: one room named "Salle" (matches _FakeCoord's group).
        self._rooms = room_map if room_map is not None else [{"room_id": room_id, "name": "Salle"}]

    async def async_get_homes(self):
        return list(self._homes)

    async def async_list_rooms(self, home):
        self.calls.append(("list_rooms", home))
        return list(self._rooms)

    async def async_room_add(self, gid, name):
        self.calls.append(("add", gid, name))
        return "new-room"

    async def async_room_update(self, room_id, name):
        self.calls.append(("update", room_id, name))

    async def async_room_dismiss(self, room_id):
        self.calls.append(("dismiss", room_id))

    async def async_room_set_devices(self, room_id, dev_ids):
        self.calls.append(("set", room_id, list(dev_ids)))


class _FakeCoord:
    def __init__(self, client, members=("a", "b")):
        self.client = client
        self.data = {d: head(d, d) for d in members}
        self.rooms = {"g1": RoomState(group_id="g1", name="Salle", pid="03wvrwpv", head_count=2)}
        self._members = {m: "g1" for m in members}
        self.refreshed = 0

    def group_of(self, dev_id):
        return self._members.get(dev_id)

    def home_of(self, group_id):
        return "home-1" if group_id == "g1" else None

    async def async_request_refresh(self):
        self.refreshed += 1


def _store(coord):
    return {DATA_COORDINATOR: coord}


async def test_create_room_adds_then_sets_devices():
    client = _FakeClient()
    coord = _FakeCoord(client, members=("a", "b"))
    res = await ops.create_room(None, _store(coord), "Classroom", ["a", "b"])
    assert res == {"room_id": "new-room"}
    assert client.calls == [
        ("add", "home-1", "Classroom"),
        ("set", "new-room", ["a", "b"]),
    ]
    assert coord.refreshed == 1


async def test_create_room_rejects_empty_and_unknown():
    coord = _FakeCoord(_FakeClient())
    with pytest.raises(ops.OperationError) as e1:
        await ops.create_room(None, _store(coord), "X", [])
    assert e1.value.code == "empty_devices"
    with pytest.raises(ops.OperationError) as e2:
        await ops.create_room(None, _store(coord), "X", ["ghost"])
    assert e2.value.code == "unknown_head"


async def test_create_room_rejects_unverified_product():
    client = _FakeClient()
    coord = _FakeCoord(client, members=("a",))
    coord.data["a"] = head("a", "A", product_id="other")  # not a verified product
    with pytest.raises(ops.OperationError) as e:
        await ops.create_room(None, _store(coord), "X", ["a"])
    assert e.value.code == "unverified_product"


async def test_rename_and_delete_resolve_room_id():
    client = _FakeClient(room_id="r9")
    coord = _FakeCoord(client)
    await ops.rename_room(None, _store(coord), _ROOM, "New")
    await ops.delete_room(None, _store(coord), _ROOM)
    assert ("update", "r9", "New") in client.calls
    assert ("dismiss", "r9") in client.calls


async def test_attach_unions_current_and_new():
    client = _FakeClient(room_id="r1")
    coord = _FakeCoord(client, members=("a", "b"))
    coord.data["c"] = head("c", "C")  # a known head not yet in the room
    coord._members.pop("c", None)
    res = await ops.attach_heads(None, _store(coord), _ROOM, ["c"])
    assert ("set", "r1", ["a", "b", "c"]) in client.calls
    assert res["previous_heads"] == ["a", "b"] and res["heads"] == ["a", "b", "c"]


async def test_detach_removes_and_refuses_emptying():
    client = _FakeClient(room_id="r1")
    coord = _FakeCoord(client, members=("a", "b"))
    res = await ops.detach_heads(None, _store(coord), _ROOM, ["b"])
    assert ("set", "r1", ["a"]) in client.calls and res["heads"] == ["a"]
    # removing every member is refused: delete_room instead
    with pytest.raises(ops.OperationError) as e:
        await ops.detach_heads(None, _store(coord), _ROOM, ["a", "b"])
    assert e.value.code == "no_members_left"


async def test_detach_unknown_head_in_room():
    coord = _FakeCoord(_FakeClient(), members=("a", "b"))
    coord.data["z"] = head("z", "Z")
    coord._members.pop("z", None)
    with pytest.raises(ops.OperationError) as e:
        await ops.detach_heads(None, _store(coord), _ROOM, ["z"])
    assert e.value.code == "unknown_head"


async def test_room_action_refuses_non_room_target():
    coord = _FakeCoord(_FakeClient())
    with pytest.raises(ops.OperationError) as e:
        await ops.rename_room(None, _store(coord), {"type": "device", "id": "a"}, "X")
    assert e.value.code == "unknown_room"


# --- room(type 4) vs implicit schedule-group(type 5) name duality (2026-11-18 field finding) ----


def test_room_name_candidates_strips_group_suffix():
    assert ops._room_name_candidates("Salle") == ["Salle"]
    assert ops._room_name_candidates("Salle 1 Group") == ["Salle 1 Group", "Salle 1"]
    assert ops._room_name_candidates("  Classroom Group ") == ["Classroom Group", "Classroom"]


async def test_resolve_room_tolerates_group_suffix():
    # The schedule-group the integration shows is auto-labelled "<room> Group"; the room map keeps
    # the base name. Resolution must still find the room and address its type-4 id on the write.
    client = _FakeClient(room_map=[{"room_id": "r-base", "name": "Salle"}])
    coord = _FakeCoord(client)
    coord.rooms["g1"] = RoomState(group_id="g1", name="Salle Group", pid="03wvrwpv", head_count=2)
    await ops.rename_room(None, _store(coord), _ROOM, "New")
    assert ("update", "r-base", "New") in client.calls


async def test_resolve_room_unknown_when_no_name_match():
    client = _FakeClient(room_map=[{"room_id": "x", "name": "Other"}])
    coord = _FakeCoord(client)
    with pytest.raises(ops.OperationError) as e:
        await ops.delete_room(None, _store(coord), _ROOM)
    assert e.value.code == "unknown_room"
