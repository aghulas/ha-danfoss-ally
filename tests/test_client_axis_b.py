"""Axis B client reads (holiday, boiler relay, room map): no network, synthetic data only."""

from unittest.mock import patch

from custom_components.danfoss_ally_cloud.api._tuya.http import TuyaApiError
from custom_components.danfoss_ally_cloud.api.client import CloudClient

from .test_client_async import FakeHttp

_HTTP = "custom_components.danfoss_ally_cloud.api.client.TuyaHttpClient"


def _client():
    return CloudClient("u", "p", "33", "sk", "dev", "ck", sid="s", ecode="e")


def _relay_raw(dev_id="relay-1", on=True, online=True):
    return {
        "devId": dev_id,
        "name": "Boiler relay",
        "category": "kg",
        "meshId": "gw-1",
        "moduleMap": {"zigbee": {"isOnline": online}},
        "dps": {"1": on},
    }


async def test_get_vacation_present_and_absent():
    fake = FakeHttp(
        {
            "tuya.m.solution.wkf.vacation.detail": lambda b, _: (
                {"temp": 150} if b["homeId"] == "1" else {}
            )
        }
    )
    with patch(_HTTP, return_value=fake):
        assert await _client().async_get_vacation(1) == {"temp": 150}
        assert await _client().async_get_vacation(2) == {}
    # the request body carries homeId as a string
    assert fake.calls[0][2] == {"homeId": "1"}


async def test_list_holidays_per_home_and_degrades():
    def detail(body, _):
        if body["homeId"] == "2":
            raise TuyaApiError("CLOUD_BOOM", "x", {})
        return {"start": "A", "end": "B"}

    fake = FakeHttp(
        {
            "tuya.m.location.list": [{"groupId": 1, "name": "H1"}, {"groupId": 2, "name": "H2"}],
            "tuya.m.solution.wkf.vacation.detail": detail,
        }
    )
    with patch(_HTTP, return_value=fake):
        hol = await _client().async_list_holidays()
    assert hol[0] == {
        "gid": "1",
        "name": "H1",
        "active": True,
        "detail": {"start": "A", "end": "B"},
    }
    # a per-home failure degrades to inactive, never raises for the whole set
    assert hol[1] == {"gid": "2", "name": "H2", "active": False, "detail": None}


async def test_list_relays_filters_category_kg():
    fake = FakeHttp(
        {
            "tuya.m.my.group.device.list": [
                _relay_raw("relay-1", on=True, online=True),
                {"devId": "head-1", "category": "wk", "dps": {"1": True}},  # a head, not a relay
                _relay_raw("relay-2", on=False, online=False),
            ]
        }
    )
    with patch(_HTTP, return_value=fake):
        relays = await _client().async_list_relays(1)
    assert [r["dev_id"] for r in relays] == ["relay-1", "relay-2"]
    assert relays[0] == {
        "dev_id": "relay-1",
        "name": "Boiler relay",
        "on": True,
        "online": True,
        "mesh_id": "gw-1",
    }
    assert relays[1]["on"] is False and relays[1]["online"] is False


async def test_relay_rooms_linked_rule():
    fake = FakeHttp(
        {
            "m.life.solution.wkf.reference.room": [
                {"roomId": 10, "roomName": "A", "enable": True, "cancel": False},  # linked
                {"roomId": 11, "roomName": "B", "enable": True, "cancel": True},  # unchecked
                {"roomId": 12, "roomName": "C", "enable": False, "cancel": False},  # not eligible
            ]
        }
    )
    with patch(_HTTP, return_value=fake):
        rooms = await _client().async_relay_rooms("relay-1")
    assert [(r["room_id"], r["linked"]) for r in rooms] == [(10, True), (11, False), (12, False)]
    # gwId == devId of the relay
    assert fake.calls[0][2] == {"devId": "relay-1", "gwId": "relay-1"}


async def test_list_rooms_map():
    fake = FakeHttp(
        {"m.life.group.room.map.get": {"rooms": [{"id": 10, "name": "A"}, {"id": 11, "name": "B"}]}}
    )
    with patch(_HTTP, return_value=fake):
        rooms = await _client().async_list_rooms(1)
    assert rooms == [{"room_id": "10", "name": "A"}, {"room_id": "11", "name": "B"}]


async def test_list_rooms_empty_on_unexpected_shape():
    fake = FakeHttp({"m.life.group.room.map.get": []})
    with patch(_HTTP, return_value=fake):
        assert await _client().async_list_rooms(1) == []


async def test_room_id_resolves_by_name_case_insensitive():
    fake = FakeHttp(
        {
            "m.life.group.room.map.get": {
                "rooms": [{"id": 10, "name": "Salle 1"}, {"id": 11, "name": "WC"}]
            }
        }
    )
    with patch(_HTTP, return_value=fake):
        assert await _client().async_room_id(1, " salle 1 ") == "10"
        assert await _client().async_room_id(1, "unknown") is None


async def test_device_homes_maps_each_device_to_its_home():
    def devlist(body, extra):
        gid = extra["gid"]
        if gid == 1:
            return [{"devId": "a"}, {"devId": "b"}]
        if gid == 2:
            return [{"devId": "c"}]
        return []

    fake = FakeHttp(
        {
            "tuya.m.location.list": [{"groupId": 1}, {"groupId": 2}],
            "tuya.m.my.group.device.list": devlist,
        }
    )
    with patch(_HTTP, return_value=fake):
        res = await _client().async_device_homes(["a", "c", "z"])
    # gids as strings; each device -> the list of homes it appears in ([] if none)
    assert res == {"a": ["1"], "c": ["2"], "z": []}
