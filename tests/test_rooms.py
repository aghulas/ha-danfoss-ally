"""Room aggregation tests (pure, no network or Home Assistant)."""

from custom_components.danfoss_ally_cloud.api.rooms import Room, aggregate_room

from .common import head


def _room(member_ids):
    return Room("77", "Salle", "03wvrwpv", "1", tuple(member_ids))


def test_aggregate_moyenne_et_chauffe():
    m1 = head("a", "A", temperature=20.0, valve_opening=0, mode="at_home", setpoint=6.0)
    m2 = head("b", "B", temperature=22.0, valve_opening=30, mode="at_home", setpoint=6.0)
    r = aggregate_room(_room(["a", "b"]), [m1, m2])
    assert r.temperature == 21.0  # mean of the online heads
    assert r.online is True
    assert r.heating is True  # m2 ouvre sa vanne
    assert r.setpoint == 6.0
    assert r.mode == "at_home"
    assert r.head_count == 2


def test_aggregate_chauffe_false_si_aucune_vanne():
    m = head("a", "A", valve_opening=0)
    assert aggregate_room(_room(["a"]), [m]).heating is False


def test_aggregate_ignores_offline_for_the_mean():
    m1 = head("a", "A", temperature=10.0, online=False)
    m2 = head("b", "B", temperature=20.0, online=True)
    r = aggregate_room(_room(["a", "b"]), [m1, m2])
    assert r.temperature == 20.0  # only the online head counts


def test_aggregate_all_offline():
    m = head("a", "A", temperature=20.0, online=False)
    r = aggregate_room(_room(["a"]), [m])
    assert r.online is False
    assert r.temperature is None
    assert r.heating is None


def test_aggregate_no_member_present():
    r = aggregate_room(_room(["a", "b"]), [])
    assert r.online is False and r.temperature is None and r.setpoint is None
    assert r.head_count == 2  # declared room size, even with no member present
