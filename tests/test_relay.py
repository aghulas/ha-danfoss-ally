"""Axis B — boiler relay read: decode, entities, coordinator link cache. Synthetic data only."""

from types import SimpleNamespace

from homeassistant.core import HomeAssistant

from custom_components.danfoss_ally_cloud import binary_sensor, sensor
from custom_components.danfoss_ally_cloud.api.client import CloudError
from custom_components.danfoss_ally_cloud.api.decode import decode_device
from custom_components.danfoss_ally_cloud.binary_sensor import DanfossRelay
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR, DOMAIN
from custom_components.danfoss_ally_cloud.coordinator import DanfossCoordinator
from custom_components.danfoss_ally_cloud.sensor import DanfossRelayRooms

from .common import FakeCloudClient, head, relay


def test_decode_relay_on_off():
    dev = decode_device({"devId": "r1", "category": "kg", "dps": {"1": True}})
    assert dev.is_relay and dev.relay_on is True
    off = decode_device({"devId": "r2", "category": "kg", "dps": {"1": False}})
    assert off.relay_on is False
    # a head's DP 1 is preheat, not a relay state
    h = decode_device({"devId": "h1", "category": "wk", "dps": {"1": True}})
    assert h.is_relay is False and h.relay_on is None


class _FakeCoord:
    def __init__(self, data, relay_rooms=None):
        self.data = data
        self.relay_rooms = relay_rooms or {}
        self.holidays: dict = {}
        self.last_update_success = True

    def async_add_listener(self, *_a, **_k):
        return lambda: None

    def group_of(self, _):
        return None


def _hass(coord):
    return SimpleNamespace(data={DOMAIN: {"e1": {DATA_COORDINATOR: coord}}})


async def test_binary_sensor_adds_relay_and_reads_state():
    coord = _FakeCoord({"relay-1": relay(on=True), "dev-1": head()})
    added: list = []
    await binary_sensor.async_setup_entry(
        _hass(coord), SimpleNamespace(entry_id="e1"), added.extend
    )
    relays = [e for e in added if isinstance(e, DanfossRelay)]
    assert len(relays) == 1
    assert relays[0].is_on is True
    assert relays[0].unique_id == "relay-1_boiler_relay"


def test_offline_relay_is_unavailable_not_off():
    """Regression (real install, 2026-11-19): an offline relay showed ``off`` (the cloud keeps its
    last DP 1) while its availability said offline. Unavailable rather than a stale state."""
    coord = _FakeCoord({"relay-1": relay(on=False, online=False)})
    ent = DanfossRelay(coord, "relay-1")
    assert ent.available is False
    coord.data = {"relay-1": relay(on=True, online=True)}  # back online: state served again
    assert ent.available is True and ent.is_on is True
    coord.data = {}  # relay gone from the account
    assert ent.available is False


def test_relay_rooms_stay_available_while_the_relay_is_offline():
    """The linkage is an account configuration, not a reading of the relay: still true offline."""
    rooms = [{"room_id": 1, "name": "A", "linked": True}]
    coord = _FakeCoord({"relay-1": relay(online=False)}, relay_rooms={"relay-1": rooms})
    ent = DanfossRelayRooms(coord, "relay-1")
    assert ent.available is True
    assert ent.native_value == 1


async def test_sensor_relay_rooms_counts_linked():
    rooms = [
        {"room_id": 1, "name": "A", "linked": True},
        {"room_id": 2, "name": "B", "linked": False},
        {"room_id": 3, "name": "C", "linked": True},
    ]
    coord = _FakeCoord({"relay-1": relay()}, relay_rooms={"relay-1": rooms})
    added: list = []
    await sensor.async_setup_entry(_hass(coord), SimpleNamespace(entry_id="e1"), added.extend)
    rr = [e for e in added if isinstance(e, DanfossRelayRooms)]
    assert len(rr) == 1
    assert rr[0].native_value == 2
    assert rr[0].extra_state_attributes == {"rooms": ["A", "C"]}


def test_relay_rooms_empty_when_unknown():
    ent = DanfossRelayRooms(_FakeCoord({"relay-1": relay()}), "relay-1")
    assert ent.native_value == 0
    assert ent.extra_state_attributes == {"rooms": []}


async def test_coordinator_refreshes_relay_rooms(hass: HomeAssistant):
    raw_relay = {"devId": "relay-1", "name": "R", "category": "kg", "dps": {"1": True}}
    fake = FakeCloudClient(
        devices=[head("h1"), decode_device(raw_relay)],
        relay_rooms={"relay-1": [{"room_id": 1, "name": "A", "linked": True}]},
    )
    coord = DanfossCoordinator(hass, fake, 90)
    await coord._async_update_data()
    assert coord.relay_rooms["relay-1"][0]["name"] == "A"


async def test_coordinator_keeps_relay_rooms_on_failure(hass: HomeAssistant):
    class _Boom(FakeCloudClient):
        async def async_relay_rooms(self, dev_id):
            raise CloudError("boom")

    raw = {"devId": "relay-1", "category": "kg", "dps": {"1": True}}
    fake = _Boom(devices=[decode_device(raw)])
    coord = DanfossCoordinator(hass, fake, 90)
    coord.relay_rooms = {"relay-1": [{"room_id": 9, "name": "old", "linked": True}]}
    await coord._async_update_data()
    assert coord.relay_rooms["relay-1"][0]["name"] == "old"
