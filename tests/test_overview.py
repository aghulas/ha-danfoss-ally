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
        self.device_home = {"a": "h1", "b": "h1", "c": "h1"}
        self.home_rooms: dict = {}

    def group_of(self, head_id):
        return self._group.get(head_id)

    def head_home(self, dev_id):
        return self.device_home.get(dev_id)

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
        self.device_home.update({"d": "h2", "e": "h2"})
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


def _gateways_by_home(data):
    return {h["gid"]: [g["device_id"] for g in h["gateways"]] for h in data["homes"]}


def test_overview_gateways_listed_under_the_home_of_their_heads():
    """Regression (real two-home install, 2026-11-19): every gateway was listed under the first
    home, none under the second, whatever the heads they carry."""
    coord = _TwoHomeCoord()
    # gw-1 carries the heads of h1 (a, b, c: the fixture default); gw-2 those of h2.
    for dev_id in ("d", "e"):
        coord.data[dev_id] = head(dev_id, coord.data[dev_id].name, mesh_id="gw-2")
    coord.data["gw-2"] = _gateway("gw-2", "Gateway 2", online=False)
    data = ops.overview_payload({DATA_COORDINATOR: coord})
    assert _gateways_by_home(data) == {"h1": ["gw-1"], "h2": ["gw-2"]}
    assert data["homes"][1]["gateways"][0] == {
        "device_id": "gw-2",
        "name": "Gateway 2",
        "online": False,
    }
    assert data["totals"]["gateways"] == 2


def test_overview_gateway_home_vote_and_fallbacks():
    coord = _TwoHomeCoord()
    homes = ["h1", "h2"]
    for dev_id in ("d", "e"):
        coord.data[dev_id] = head(dev_id, coord.data[dev_id].name, mesh_id="gw-2")
    gw2 = _gateway("gw-2", "Gateway 2")
    assert ops._gateway_home_gid(coord, gw2, homes) == "h2"
    # Mixed gateway: the majority of its heads wins; a tie goes to the earlier home.
    coord.data["c"] = head("c", "Salle 2 #1", mesh_id="gw-2")
    assert ops._gateway_home_gid(coord, gw2, homes) == "h2"
    coord.data["a"] = head("a", "Salle 1 #1", mesh_id="gw-2")
    assert ops._gateway_home_gid(coord, gw2, homes) == "h1"
    # A head of unknown home does not vote.
    coord.data["z"] = head("z", "Nowhere", mesh_id="gw-3")
    gw3 = _gateway("gw-3", "Gateway 3")
    # No head with a known home: the gateway's own entry in the per-home device lists...
    coord.device_home["gw-3"] = "h2"
    assert ops._gateway_home_gid(coord, gw3, homes) == "h2"
    # ...and without it, the first home (kept visible, as before).
    del coord.device_home["gw-3"]
    assert ops._gateway_home_gid(coord, gw3, homes) == "h1"
    assert ops._gateway_home_gid(coord, gw3, []) is None
    # Every gateway is listed exactly once, so the total stays the gateway count.
    coord.data.update({"gw-2": gw2, "gw-3": gw3})
    data = ops.overview_payload({DATA_COORDINATOR: coord})
    listed = [g for ids in _gateways_by_home(data).values() for g in ids]
    assert sorted(listed) == ["gw-1", "gw-2", "gw-3"]
    assert data["totals"]["gateways"] == 3


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


# --- Single-head rooms (a head with no schedule-group): listed and counted (§3.6) --------------


class _FleetCoord(_Coord):
    """Two homes, each with grouped rooms and single heads (synthetic names and ids only).

    h1: group g1 (a, b) + single heads s1 (room "A-1 Office"), s2 (no matching room: fallback).
    h2: group g7 (x, y) + single heads s3 (low battery, room "C-1 Lab"), s4 (fault, offline).
    """

    def __init__(self):
        super().__init__()
        x = head("x", "B-0 Hall #1", online=True, valve_opening=0)
        y = head("y", "B-0 Hall #2", online=True, valve_opening=0)
        s1 = head("s1", "A-1 Office", valve_opening=0, temperature=19.5, setpoint=20.0)
        s2 = head("s2", "A-1 Sas", valve_opening=0, heat_request=True)
        s3 = head("s3", "C-1 Lab", valve_opening=0, battery=8.0)
        s4 = head(
            "s4",
            "C-0 Store",
            online=False,
            faults=[{"code": "E02", "bit": 1, "label": "valve fault"}],
        )
        for d in (x, y, s1, s2, s3, s4):
            self.data[d.id] = d
        # The test room g2 (one member, grouped) of the base fixture is dropped: g1 only in h1.
        del self.rooms["g2"]
        del self._group["c"]
        del self.data["c"]
        self.rooms["g7"] = aggregate_room(
            Room("g7", "B-0 Hall", "03wvrwpv", "h2", ("x", "y")), [x, y]
        )
        self._group.update({"x": "g7", "y": "g7"})
        self._home["g7"] = "h2"
        self.holidays["h2"] = {"gid": "h2", "name": "Building 2", "active": False}
        self.device_home = {
            "a": "h1", "b": "h1", "s1": "h1", "s2": "h1",
            "x": "h2", "y": "h2", "s3": "h2", "s4": "h2",
        }  # fmt: skip
        self.home_rooms = {
            "h1": [
                {"room_id": "401", "name": "Salle 1"},  # the group's room: claimed by g1
                {"room_id": "402", "name": "A-1  office"},  # case/space differ: still matches
                {"room_id": "403", "name": "A-1 Sas Wing"},  # not the head's name: no match
                {"room_id": "404", "name": "C-1 Lab"},  # same name, other home: ignored
            ],
            "h2": [
                {"room_id": "501", "name": "B-0 Hall"},
                {"room_id": "502", "name": "C-1 Lab"},
                {"room_id": "503", "name": "C-0 Store"},
            ],
        }


def _fleet():
    data = ops.overview_payload({DATA_COORDINATOR: _FleetCoord()})
    rooms = {r["id"]: r for h in data["homes"] for r in h["rooms"]}
    return data, rooms


def test_single_heads_listed_in_their_home():
    data, _ = _fleet()
    by_home = {h["gid"]: [r["id"] for r in h["rooms"]] for h in data["homes"]}
    # Sorted by name within each home, groups and single heads together.
    assert by_home == {"h1": ["s1", "s2", "g1"], "h2": ["g7", "s4", "s3"]}


def test_single_head_room_fields():
    _, rooms = _fleet()
    s1 = rooms["s1"]
    assert s1["kind"] == "single_head" and s1["head_count"] == 1
    assert s1["name"] == "A-1  office" and s1["name_source"] == "room" and s1["room_id"] == "402"
    assert s1["head_id"] == "s1" and s1["head_name"] == "A-1 Office"
    assert s1["online"] is True and s1["offline"] == 0
    assert s1["temperature"] == 19.5 and s1["setpoint"] == 20.0
    # No room of that name in its home: the head's name, flagged.
    s2 = rooms["s2"]
    assert s2["name"] == "A-1 Sas" and s2["name_source"] == "head" and s2["room_id"] is None
    assert s2["heating"] is True
    # Grouped rooms say so, and carry the same climate fields.
    g1 = rooms["g1"]
    assert g1["kind"] == "group" and "name_source" not in g1
    assert set(s1) >= set(g1)


def test_single_head_low_battery_and_fault_counted():
    _, rooms = _fleet()
    assert rooms["s3"]["low_battery"] == 1 and rooms["s3"]["name_source"] == "room"
    s4 = rooms["s4"]
    assert s4["faults"] == 1 and s4["offline"] == 1 and s4["online"] is False
    assert s4["temperature"] is None  # an offline head's temperature is stale
    assert s4["heating"] is False


def test_totals_cover_the_whole_fleet():
    data, _ = _fleet()
    totals = data["totals"]
    assert totals["rooms"] == 6
    assert totals["heads"] == 8  # 2 + 2 grouped, 4 single
    assert totals["offline"] == 2  # b (grouped) + s4 (single)
    assert totals["low_battery"] == 1  # s3
    assert totals["faults"] == 1  # s4
    assert totals["heating"] == 2  # g1 (head a, valve open) + s2 (heat request)


def test_single_head_name_match_must_be_unambiguous():
    coord = _FleetCoord()
    # A second single head with the same name in h2: neither takes the room.
    coord.data["s5"] = head("s5", "C-1 Lab")
    coord.device_home["s5"] = "h2"
    # Two rooms of one name in h1: no match either.
    coord.home_rooms["h1"].append({"room_id": "405", "name": "A-1 Office"})
    data = ops.overview_payload({DATA_COORDINATOR: coord})
    rooms = {r["id"]: r for h in data["homes"] for r in h["rooms"]}
    assert rooms["s3"]["name_source"] == "head" and rooms["s5"]["name_source"] == "head"
    assert rooms["s1"]["name_source"] == "head"


def test_single_head_room_claimed_by_a_group_is_not_reused():
    coord = _FleetCoord()
    # A single head named like a grouped room ("<name> Group" label too) keeps its own name.
    coord.rooms["g1"] = aggregate_room(
        Room("g1", "A-1 Office Group", "03wvrwpv", "h1", ("a", "b")),
        [coord.data["a"], coord.data["b"]],
    )
    rooms = {r["id"]: r for h in ops.overview_payload({DATA_COORDINATOR: coord})["homes"]
             for r in h["rooms"]}  # fmt: skip
    assert rooms["s1"]["name_source"] == "head"


def test_single_head_of_unknown_home_goes_to_first_home():
    coord = _FleetCoord()
    del coord.device_home["s4"]
    data = ops.overview_payload({DATA_COORDINATOR: coord})
    assert "s4" in [r["id"] for r in data["homes"][0]["rooms"]]
    assert data["totals"]["heads"] == 8


def test_home_known_only_from_its_single_heads():
    coord = _FleetCoord()
    coord.holidays.pop("h2")
    del coord.rooms["g7"]
    for dev_id in ("x", "y"):
        coord._group.pop(dev_id)
    data = ops.overview_payload({DATA_COORDINATOR: coord})
    h2 = next(h for h in data["homes"] if h["gid"] == "h2")
    assert h2["name"] == "Home h2"
    assert {r["kind"] for r in h2["rooms"]} == {"single_head"}
