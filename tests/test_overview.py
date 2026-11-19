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


class _TwoHomeCoord(_Coord):
    """Two homes, one relay each; the relay -> room link carries Tuya *room* ids (type 4)."""

    def __init__(self):
        super().__init__()
        d = head("d", "Kitchen #1", online=True)
        e = head("e", "Hall #1", online=True)
        r2 = relay("r2", "Hc2 Relay", on=True, online=False)  # offline: stale "on"
        self.data.update({d.id: d, e.id: e, r2.id: r2})
        self.rooms.update(
            {
                "g3": aggregate_room(Room("g3", "D0 Kitchen", "03wvrwpv", "h2", ("d",)), [d]),
                "g4": aggregate_room(Room("g4", "E-0 Hall", "03wvrwpv", "h2", ("e",)), [e]),
            }
        )
        self._group.update({"d": "g3", "e": "g4"})
        self._home.update({"g3": "h2", "g4": "h2"})
        self.holidays["h2"] = {"gid": "h2", "name": "Building 2", "active": False}
        # Real relays list Tuya room ids, unknown to home_of(): matching must go by name.
        self.relay_rooms = {
            "r": [
                {"room_id": 9001, "name": "Salle 1", "linked": True},
                {"room_id": 9002, "name": "Salle 2", "linked": True},
            ],
            "r2": [
                {"room_id": 9101, "name": "E-0 Hall", "linked": True},
                {"room_id": 9102, "name": "D-0 Kitchen", "linked": True},  # "D0" vs "D-0"
                {"room_id": 9103, "name": "Salle 1", "linked": False},  # not linked: no vote
                {"room_id": 9104, "name": "Unknown room", "linked": True},  # unresolvable
            ],
        }


def test_overview_relays_attached_to_their_own_home():
    data = ops.overview_payload({DATA_COORDINATOR: _TwoHomeCoord()})
    by_home = {h["gid"]: [r["device_id"] for r in h["relays"]] for h in data["homes"]}
    assert by_home == {"h1": ["r"], "h2": ["r2"]}
    r2 = data["homes"][1]["relays"][0]
    assert r2["linked_rooms"] == 3 and r2["online"] is False


def test_overview_offline_relay_not_counted_on():
    data = ops.overview_payload({DATA_COORDINATOR: _TwoHomeCoord()})
    assert data["totals"]["relays_on"] == 1  # r2 is on but offline


def test_relay_home_majority_vote_and_ambiguity():
    coord = _TwoHomeCoord()
    homes = ["h1", "h2"]
    by_name = ops._home_by_room_name(coord)
    assert by_name["d0kitchen"] == "h2"
    # Majority wins over a minority room of the other home.
    coord.relay_rooms["r2"].append({"room_id": 9105, "name": "Salle 2", "linked": True})
    assert ops._relay_home_gid(coord, coord.data["r2"], homes, by_name) == "h2"
    # A name present in both homes is ambiguous and must not vote.
    coord.rooms["g5"] = aggregate_room(Room("g5", "E-0 Hall", "03wvrwpv", "h1", ()), [])
    coord._home["g5"] = "h1"
    assert ops._home_by_room_name(coord)["e0hall"] is None
    # No linked room at all: the listed rooms vote; nothing resolvable: first home.
    coord.relay_rooms["r3"] = [{"room_id": 1, "name": "Hall? no", "linked": False}]
    assert ops._relay_home_gid(coord, relay("r3"), homes, by_name) == "h1"
