"""Single-head rooms (contract §3.6): head -> home and per-home room map caches. Synthetic data."""

from homeassistant.core import HomeAssistant

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud.api.client import CloudError
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR
from custom_components.danfoss_ally_cloud.coordinator import DanfossCoordinator

from .common import FakeCloudClient, head


async def test_coordinator_caches_head_home_and_room_maps(hass: HomeAssistant):
    fake = FakeCloudClient(devices=[head("h1", "Office")])
    coord = DanfossCoordinator(hass, fake, 90)
    await coord._async_update_data()
    assert coord.head_home("h1") == "1" and coord.head_home("nope") is None
    assert coord.home_rooms == {"1": [{"room_id": "room-5", "name": "Salle 1"}]}


async def test_coordinator_keeps_room_maps_and_homes_on_failure(hass: HomeAssistant):
    class _Boom(FakeCloudClient):
        async def async_list_rooms(self, home_gid):
            raise CloudError("boom")

    coord = DanfossCoordinator(hass, _Boom(devices=[head("h1")]), 90)
    coord.home_rooms = {"1": [{"room_id": "9", "name": "old"}]}
    coord.device_home = {"gone": "2"}  # a device of a home that did not answer: kept
    await coord._async_update_data()
    assert coord.home_rooms == {"1": [{"room_id": "9", "name": "old"}]}
    assert coord.device_home == {"gone": "2", "h1": "1"}


async def test_coordinator_room_maps_skip_when_homes_fail(hass: HomeAssistant):
    class _NoHomes(FakeCloudClient):
        async def async_get_homes(self):
            raise CloudError("boom")

    coord = DanfossCoordinator(hass, _NoHomes(devices=[head("h1")]), 90)
    coord.home_rooms = {"1": []}
    await coord._refresh_home_rooms()
    assert coord.home_rooms == {"1": []}


async def test_overview_end_to_end_single_head_named_after_its_room(hass: HomeAssistant):
    # No schedule-group: the head is a single-head room, named after the app room "Salle 1".
    fake = FakeCloudClient(devices=[head("h1", "salle 1")])
    coord = DanfossCoordinator(hass, fake, 90)
    coord.async_set_updated_data(await coord._async_update_data())
    data = ops.overview_payload({DATA_COORDINATOR: coord})
    [room] = data["homes"][0]["rooms"]
    assert room["kind"] == "single_head" and room["name"] == "Salle 1"
    assert room["room_id"] == "room-5" and room["name_source"] == "room"
    assert data["totals"]["heads"] == 1 and data["totals"]["rooms"] == 1
