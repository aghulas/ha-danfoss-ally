"""Fleet overview (contract §3.6, axis D): read-only aggregation from the coordinator cache."""

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud.api import DanfossDevice
from custom_components.danfoss_ally_cloud.api.rooms import Room, aggregate_room
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR

from .common import head, relay


def _gateway(dev_id="gw-1", name="Gateway", online=True) -> DanfossDevice:
    return DanfossDevice(id=dev_id, name=name, category="gateway", online=online)


class _Coord:
    """Minimal coordinator with a two-room, one-gateway, one-relay single home."""

    def __init__(self):
        a = head("a", "Salle 1 #1", online=True, battery=90.0)
        b = head("b", "Salle 1 #2", online=False)  # offline
        c = head(
            "c",
            "Salle 2 #1",
            online=True,
            battery=95.0,
            heat_request=True,
            window_open=True,
            faults=[{"code": "E14", "bit": 13, "label": "low battery"}],
        )
        gw = _gateway()
        r = relay("r", "Boiler relay", on=True)
        self.data = {d.id: d for d in (a, b, c, gw, r)}
        self.rooms = {
            "g1": aggregate_room(Room("g1", "Salle 1", "03wvrwpv", "h1", ("a", "b")), [a, b]),
            "g2": aggregate_room(Room("g2", "Salle 2", "03wvrwpv", "h1", ("c",)), [c]),
        }
        self._group = {"a": "g1", "b": "g1", "c": "g2"}
        self._home = {"g1": "h1", "g2": "h1"}
        self.holidays = {"h1": {"gid": "h1", "name": "School", "active": True}}
        self.relay_rooms = {
            "r": [
                {"room_id": "g1", "name": "Salle 1", "linked": True},
                {"room_id": "g2", "name": "Salle 2", "linked": False},
            ]
        }
        self.hass = None  # no entity registry -> climate ids resolve to None

    def group_of(self, head_id):
        return self._group.get(head_id)

    def home_of(self, group_id):
        return self._home.get(group_id)


def _store():
    coord = _Coord()
    return {DATA_COORDINATOR: coord}, coord


def test_low_battery_head():
    assert ops._low_battery_head({"faults": [{"code": "E14"}]}) is True
    assert ops._low_battery_head({"faults": [{"code": "E15"}]}) is True
    assert ops._low_battery_head({"battery": 8}) is True
    assert ops._low_battery_head({"battery": 90, "faults": []}) is False
    assert ops._low_battery_head({"battery": None, "faults": []}) is False


def test_overview_shape_and_homes():
    store, _ = _store()
    data = ops.overview_payload(store)
    assert len(data["homes"]) == 1
    home = data["homes"][0]
    assert home["gid"] == "h1" and home["name"] == "School"
    assert home["holiday_active"] is True
    assert [g["device_id"] for g in home["gateways"]] == ["gw-1"]
    assert home["gateways"][0]["online"] is True


def test_overview_room_health_counts():
    store, _ = _store()
    rooms = {r["id"]: r for r in ops.overview_payload(store)["homes"][0]["rooms"]}
    assert rooms["g1"]["offline"] == 1 and rooms["g1"]["low_battery"] == 0
    assert rooms["g2"]["low_battery"] == 1  # E14
    assert rooms["g2"]["heating"] is True and rooms["g2"]["window_open"] is True
    assert rooms["g2"]["faults"] == 1


def test_overview_relays_and_totals():
    store, _ = _store()
    data = ops.overview_payload(store)
    relays = data["homes"][0]["relays"]
    assert len(relays) == 1 and relays[0]["on"] is True
    assert relays[0]["linked_rooms"] == 1  # only g1 is linked
    totals = data["totals"]
    assert totals == {
        "homes": 1,
        "gateways": 1,
        "rooms": 2,
        "heads": 3,
        "offline": 1,
        "low_battery": 1,
        "heating": 2,
        "faults": 1,
        "relays_on": 1,
    }
