"""number platform: an isolated head's setpoint bounds over Tuya cloud MQTT (DP 18, 27, 120).

Fake coordinator and link, synthetic data, no network.
"""

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.danfoss_ally_cloud import number
from custom_components.danfoss_ally_cloud.const import (
    DATA_CLOUD_MQTT,
    DATA_COORDINATOR,
    DATA_MQTT_LINK,
    DATA_MQTT_SUPERVISED_DPS,
    DOMAIN,
)
from custom_components.danfoss_ally_cloud.number import HEAD_BOUNDS, DanfossHeadBound

from .common import head
from .test_switch import _FakeClient, _FakeCloudCoord, _FakeMqttLink

UPPER = next(d for d in HEAD_BOUNDS if d.bound == "upper")
LOWER = next(d for d in HEAD_BOUNDS if d.bound == "lower")
TRIAL = frozenset({18, 27, 120})


def _head(**kw):
    base = dict(
        max_setpoint=35.0,
        min_setpoint=5.0,
        setpoints={"comfort": 21.0, "setback": 14.0, "pause": 5.0},
    )
    base.update(kw)
    return head(**base)


def _bound(desc, dev, *, link=None, supervised=TRIAL, groups=None, client=None):
    coord = _FakeCloudCoord({dev.id: dev}, client=client or _FakeClient(), groups=groups)
    link = link or _FakeMqttLink()
    return DanfossHeadBound(coord, dev.id, desc, link, supervised), coord, link


def test_bound_reads_the_decoded_value_and_schema_range():
    up, _, _ = _bound(UPPER, _head(max_setpoint=28.0))
    low, _, _ = _bound(LOWER, _head(min_setpoint=6.5))
    assert up.native_value == 28.0 and (up.native_min_value, up.native_max_value) == (20.0, 35.0)
    assert low.native_value == 6.5 and (low.native_min_value, low.native_max_value) == (5.0, 20.0)
    assert up.unique_id == "dev-1_upper_bound" and low.unique_id == "dev-1_lower_bound"


def test_bound_under_trial_states_its_route():
    ent, _, _ = _bound(UPPER, _head())
    assert ent.available is True
    assert ent.extra_state_attributes == {
        "write_path": "cloud_mqtt",
        "write_scope": "head",
        "write_trial": True,
    }


def test_bound_unavailable_without_a_usable_route():
    # Candidate not opened for a trial.
    ent, _, _ = _bound(UPPER, _head(), supervised=frozenset())
    assert ent.available is False and ent.extra_state_attributes == {"write_path": "none"}
    # Link down.
    ent, _, _ = _bound(UPPER, _head(), link=_FakeMqttLink(connected=False))
    assert ent.available is False
    # Gateway unknown to the link.
    ent, _, _ = _bound(UPPER, _head(), link=_FakeMqttLink(gateways=("gw-x",)))
    assert ent.available is False
    # Head grouped since setup: no proven bound write for a room here.
    dev = _head()
    ent, _, _ = _bound(UPPER, dev, groups={dev.id: "g1"})
    assert ent.available is False
    # Head offline.
    ent, _, _ = _bound(UPPER, _head(online=False))
    assert ent.available is False


async def test_upper_bound_write_publishes_tenths_and_confirms():
    dev = _head()
    ent, coord, link = _bound(UPPER, dev)
    await ent.async_set_native_value(34.5)
    assert link.published == [("gw-1", "node-1", {"18": 345})]
    assert link.confirmations == [("node-1", 18, 345)]
    assert coord.commanded == [dev.id] and coord.refreshed is True


async def test_lower_bound_alone_when_the_pause_setpoint_stays_inside():
    dev = _head(min_setpoint=6.0, setpoints={"comfort": 21.0, "setback": 14.0, "pause": 7.0})
    ent, _, link = _bound(LOWER, dev)
    await ent.async_set_native_value(6.5)
    assert link.published == [("gw-1", "node-1", {"27": 65})]


async def test_lower_bound_drags_the_pause_setpoint_when_it_rises_above_it():
    dev = _head()  # pause 5.0
    ent, _, link = _bound(LOWER, dev)
    await ent.async_set_native_value(5.5)
    assert link.published == [("gw-1", "node-1", {"27": 55, "120": 55})]  # one frame, like the app
    assert sorted(link.confirmations) == [("node-1", 27, 55), ("node-1", 120, 55)]


async def test_lower_bound_needing_dp120_is_refused_when_dp120_is_closed():
    dev = _head()
    ent, _, link = _bound(LOWER, dev, supervised=frozenset({27}))
    with pytest.raises(HomeAssistantError, match="DP 120"):
        await ent.async_set_native_value(5.5)
    assert link.published == []


async def test_lower_bound_with_unknown_pause_setpoint_writes_dp27_only():
    dev = _head(setpoints={"comfort": 21.0, "setback": 14.0})
    ent, _, link = _bound(LOWER, dev)
    await ent.async_set_native_value(5.5)
    assert link.published == [("gw-1", "node-1", {"27": 55})]


@pytest.mark.parametrize(
    ("desc", "value", "match"),
    [
        (UPPER, 19.5, "out of range"),  # under the schema range of DP 18
        (UPPER, 36.0, "out of range"),
        (LOWER, 4.5, "out of range"),
        (LOWER, 20.5, "out of range"),
        (UPPER, "abc", "non-numeric"),
        (UPPER, 20.5, "comfort setpoint"),  # would exclude comfort 21
        (LOWER, 14.5, "setback setpoint"),  # would exclude setback 14
    ],
)
async def test_bound_values_refused_before_sending(desc, value, match):
    ent, _, link = _bound(desc, _head())
    with pytest.raises(HomeAssistantError, match=match):
        await ent.async_set_native_value(value)
    assert link.published == [] and link.confirmations == []


async def test_bounds_must_stay_ordered():
    """The schema ranges (lower 5-20, upper 20-35) already keep the bounds ordered; the explicit
    check covers a head that reports a bound outside its schema range."""
    low, _, link = _bound(LOWER, _head(max_setpoint=18.0, setpoints={}))
    with pytest.raises(HomeAssistantError, match="upper bound"):
        await low.async_set_native_value(19.0)
    up, _, link2 = _bound(UPPER, _head(min_setpoint=22.0, setpoints={}))
    with pytest.raises(HomeAssistantError, match="lower bound"):
        await up.async_set_native_value(21.0)
    assert link.published == [] and link2.published == []
    # Equal bounds are allowed.
    low, _, link = _bound(LOWER, _head(max_setpoint=20.0, setpoints={}))
    await low.async_set_native_value(20.0)
    assert link.published == [("gw-1", "node-1", {"27": 200})]


async def test_bound_rounds_to_the_half_degree_step():
    ent, _, link = _bound(UPPER, _head())
    await ent.async_set_native_value(30.2)
    assert link.published == [("gw-1", "node-1", {"18": 300})]


async def test_bound_write_refused_when_the_route_is_gone():
    ent, _, link = _bound(UPPER, _head(), link=_FakeMqttLink(connected=False))
    with pytest.raises(HomeAssistantError, match="unavailable"):
        await ent.async_set_native_value(30.0)
    assert link.published == []


async def test_bound_write_unconfirmed_raises():
    ent, coord, link = _bound(UPPER, _head(), link=_FakeMqttLink(confirm=False))
    with pytest.raises(HomeAssistantError, match="not confirmed"):
        await ent.async_set_native_value(30.0)
    assert link.published  # sent, but nothing claimed


# --- platform setup: entities exist only with an open route --------------------------------------


class _Hass:
    def __init__(self, data):
        self.data = {DOMAIN: {"e1": data}}


class _Entry:
    entry_id = "e1"


class _SetupCoord(_FakeCloudCoord):
    rooms: dict = {}


async def _setup(devices, *, cloud_mqtt=True, link=True, supervised=TRIAL, groups=None):
    coord = _SetupCoord({d.id: d for d in devices}, client=_FakeClient(), groups=groups)
    added = []
    data = {
        DATA_COORDINATOR: coord,
        DATA_CLOUD_MQTT: cloud_mqtt,
        DATA_MQTT_LINK: _FakeMqttLink() if link else None,
        DATA_MQTT_SUPERVISED_DPS: supervised,
    }
    await number.async_setup_entry(_Hass(data), _Entry(), added.extend)
    return [e for e in added if isinstance(e, DanfossHeadBound)]


async def test_no_bound_entity_by_default():
    assert await _setup([_head()], supervised=frozenset()) == []  # candidates are closed
    assert await _setup([_head()], cloud_mqtt=False) == []
    assert await _setup([_head()], link=False) == []


async def test_bound_entities_only_for_isolated_verified_heads_and_open_dps():
    isolated = _head(dev_id="iso")
    grouped = _head(dev_id="grp")
    other_model = _head(dev_id="other", product_id="unverified")
    ents = await _setup([isolated, grouped, other_model], groups={"grp": "g1"})
    assert sorted(e.unique_id for e in ents) == ["iso_lower_bound", "iso_upper_bound"]
    only_upper = await _setup([isolated], supervised=frozenset({18}))
    assert [e.unique_id for e in only_upper] == ["iso_upper_bound"]
