"""Axis B — relay <-> room link write (B6, gated). Fakes + hass harness. Synthetic data."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud import websocket_api as ws
from custom_components.danfoss_ally_cloud.api.client import CloudClient
from custom_components.danfoss_ally_cloud.api.decode import decode_device
from custom_components.danfoss_ally_cloud.api.rooms import RoomState
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR, DOMAIN

from .common import ENTRY_DATA, FakeCloudClient, head
from .test_client_async import FakeHttp

_HTTP = "custom_components.danfoss_ally_cloud.api.client.TuyaHttpClient"
_ROOM = {"type": "room", "id": "g1"}


async def test_client_relay_bind_payload():
    fake = FakeHttp({"m.life.solution.wkf.reference.edit": {"ok": True}})
    with patch(_HTTP, return_value=fake):
        c = CloudClient("u", "p", "33", "sk", "dev", "ck", sid="s", ecode="e")
        await c.async_relay_bind("relay-1", 10, True)
        await c.async_relay_bind("relay-1", 10, False)
    assert fake.calls[0][2] == {
        "devId": "relay-1",
        "gwId": "relay-1",
        "roomId": 10,
        "status": "bind",
    }
    assert fake.calls[1][2]["status"] == "unbind"


class _FakeClient:
    def __init__(self):
        self.calls: list = []

    async def async_relay_bind(self, dev_id, room_id, linked):
        self.calls.append((dev_id, room_id, bool(linked)))
        return {"ok": True}


class _FakeCoord:
    def __init__(self, client, relay_rooms):
        self.client = client
        self.data = {"relay-1": _relay_dev(), "a": head("a", "A")}
        self.rooms = {"g1": RoomState(group_id="g1", name="Salle", pid="03wvrwpv", head_count=1)}
        self.relay_rooms = relay_rooms
        self.refreshed = 0
        self.invalidated = 0

    def invalidate_topology(self):
        self.invalidated += 1

    async def async_request_refresh(self):
        self.refreshed += 1


def _relay_dev():
    return decode_device({"devId": "relay-1", "name": "R", "category": "kg", "dps": {"1": True}})


def _store(coord):
    return {DATA_COORDINATOR: coord}


async def test_set_relay_room_binds_matched_room():
    client = _FakeClient()
    coord = _FakeCoord(client, {"relay-1": [{"room_id": 55, "name": "Salle", "linked": False}]})
    res = await ops.set_relay_room(None, _store(coord), "relay-1", _ROOM, True)
    assert client.calls == [("relay-1", 55, True)]
    assert res == {"relay": "relay-1", "room_id": "55", "linked": True}


async def test_set_relay_room_unknown_relay():
    coord = _FakeCoord(_FakeClient(), {})
    with pytest.raises(ops.OperationError) as e:
        await ops.set_relay_room(None, _store(coord), "ghost", _ROOM, True)
    assert e.value.code == "unknown_relay"


async def test_set_relay_room_not_eligible():
    coord = _FakeCoord(_FakeClient(), {"relay-1": []})  # the room is not an eligible candidate
    with pytest.raises(ops.OperationError) as e:
        await ops.set_relay_room(None, _store(coord), "relay-1", _ROOM, True)
    assert e.value.code == "unknown_room"


async def test_ws_relay_set_room_e2e(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr")
    entry.add_to_hass(hass)
    fake = FakeCloudClient(
        devices=[head("a", "Salle 1 #2"), head("b", "Salle 1 #3"), _relay_dev()],
        groups=[{"group_id": "13000000", "name": "Salle 1", "pid": "03wvrwpv", "head_count": 2}],
        members={"13000000": ["a", "b"]},
        relay_rooms={"relay-1": [{"room_id": 77, "name": "Salle 1", "linked": False}]},
    )
    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    class _Conn:
        def __init__(self):
            self.user = SimpleNamespace(is_admin=True)
            self.results: dict = {}
            self.errors: list = []

        def send_result(self, mid, result=None):
            self.results[mid] = result

        def send_error(self, mid, code, msg):
            self.errors.append((code, msg))

    conn = _Conn()
    ws.ws_relay_set_room(
        hass,
        conn,
        {"id": 1, "relay": "relay-1", "target": {"type": "room", "id": "13000000"}, "linked": True},
    )
    await hass.async_block_till_done()
    assert conn.results[1]["linked"] is True
    assert ("relay_bind", "relay-1", 77, True) in fake.writes
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
