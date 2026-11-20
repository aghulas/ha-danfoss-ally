"""number platform: an isolated head's setpoint bounds over Tuya cloud MQTT (DP 18, 27, 120).

Fake coordinator and link, synthetic data, no network.
"""

from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.danfoss_ally_cloud import number
from custom_components.danfoss_ally_cloud.const import (
    DATA_CLOUD_MQTT,
    DATA_COORDINATOR,
    DATA_MQTT_LINK,
    DATA_MQTT_SUPERVISED_DPS,
    DATA_MQTT_SUPERVISED_HEAD,
    DOMAIN,
)
from custom_components.danfoss_ally_cloud.number import HEAD_BOUNDS, DanfossHeadBound

from .common import head
from .test_switch import _FakeClient, _FakeCloudCoord, _FakeMqttLink

UPPER = next(d for d in HEAD_BOUNDS if d.bound == "upper")
LOWER = next(d for d in HEAD_BOUNDS if d.bound == "lower")
# DP 18, 27 and 120 are proven on cloud MQTT (2026-11-19): no supervised trial is needed.
TRIAL = frozenset()


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


def test_bound_states_its_route_without_a_trial_marker():
    ent, _, _ = _bound(UPPER, _head())
    assert ent.available is True
    assert ent.extra_state_attributes == {"write_path": "cloud_mqtt", "write_scope": "head"}


def test_bound_unavailable_without_a_usable_route():
    # Link down.
    ent, _, _ = _bound(UPPER, _head(), link=_FakeMqttLink(connected=False))
    assert ent.available is False and ent.extra_state_attributes == {"write_path": "none"}
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


async def test_a_frame_with_a_closed_dp_is_refused_whole(monkeypatch):
    """Should a DP of the frame be closed on the channel, nothing is sent at all (here DP 120 put
    back among the candidates: the lower bound that needs it is refused, DP 27 does not go out
    alone)."""
    from custom_components.danfoss_ally_cloud.api import writes

    monkeypatch.setattr(writes, "MQTT_WRITE_DPS", writes.MQTT_WRITE_DPS - {120})
    monkeypatch.setattr(writes, "MQTT_CANDIDATE_DPS", writes.MQTT_CANDIDATE_DPS | {120})
    dev = _head()
    ent, _, link = _bound(LOWER, dev)
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


REMOVED: list[str] = []  # unique ids the last platform setup flagged as closed


def _removed_bounds():
    """The bound entities the last setup flagged as closed (other head numbers left aside)."""
    return [uid for uid in REMOVED if uid.endswith("_bound")]


async def _setup(
    devices,
    *,
    cloud_mqtt=True,
    link=True,
    supervised=TRIAL,
    groups=None,
    trial_head="iso",
    kind=DanfossHeadBound,
):
    """Run the platform setup on fakes. ``trial_head``: the head the supervised trial is confined
    to. The registry cleanup is recorded in ``REMOVED`` instead of touching a registry."""
    coord = _SetupCoord({d.id: d for d in devices}, client=_FakeClient(), groups=groups)
    added = []
    data = {
        DATA_COORDINATOR: coord,
        DATA_CLOUD_MQTT: cloud_mqtt,
        DATA_MQTT_LINK: _FakeMqttLink() if link else None,
        DATA_MQTT_SUPERVISED_DPS: supervised,
        DATA_MQTT_SUPERVISED_HEAD: trial_head,
    }
    REMOVED.clear()
    with patch.object(
        number, "remove_closed_head_numbers", lambda _hass, _entry, uids: REMOVED.extend(uids)
    ):
        await number.async_setup_entry(_Hass(data), _Entry(), added.extend)
    return [e for e in added if isinstance(e, kind)]


async def test_no_bound_entity_without_the_cloud_mqtt_option():
    assert await _setup([_head(dev_id="iso")], cloud_mqtt=False) == []
    assert _removed_bounds() == ["iso_upper_bound", "iso_lower_bound"]


async def test_bound_entities_need_no_trial():
    """Proven DPs: with the option on and a link, every isolated head gets its bounds, with no
    DP ticked and no trial head designated."""
    ents = await _setup([_head(dev_id="iso"), _head(dev_id="iso2")], trial_head=None)
    assert sorted(e.unique_id for e in ents) == [
        "iso2_lower_bound",
        "iso2_upper_bound",
        "iso_lower_bound",
        "iso_upper_bound",
    ]
    assert _removed_bounds() == []
    assert all("write_trial" not in e.extra_state_attributes for e in ents)


async def test_open_dp_without_a_link_creates_nothing_and_removes_nothing():
    """The link failed to start: transient. The entities are not created this run, and their
    registry entries are kept (no customisation lost)."""
    assert await _setup([_head(dev_id="iso")], link=False) == []
    assert _removed_bounds() == []


async def test_bound_entities_only_for_isolated_verified_heads():
    isolated = _head(dev_id="iso")
    grouped = _head(dev_id="grp")
    other_model = _head(dev_id="other", product_id="unverified")
    ents = await _setup([isolated, grouped, other_model], groups={"grp": "g1"})
    assert sorted(e.unique_id for e in ents) == ["iso_lower_bound", "iso_upper_bound"]
    # The grouped head's bounds are closed; the unverified model is never considered at all.
    assert _removed_bounds() == ["grp_upper_bound", "grp_lower_bound"]


async def test_a_trial_on_another_head_does_not_touch_the_bounds():
    """A trial of the remaining candidate armed on one head changes nothing for the proven
    bounds: both isolated heads keep theirs, unmarked."""
    ents = await _setup(
        [_head(dev_id="iso"), _head(dev_id="iso2")],
        supervised=frozenset({1}),
        trial_head="iso",
    )
    assert len(ents) == 4 and _removed_bounds() == []
    assert all("write_trial" not in e.extra_state_attributes for e in ents)


# --- registry: a disarmed trial leaves no restored, unavailable entity behind ---------------------


async def test_disarming_the_trial_removes_the_bound_entities_from_the_registry(hass):
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from .common import ENTRY_DATA

    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr")
    entry.add_to_hass(hass)
    other = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="autre@exemple.fr")
    other.add_to_hass(hass)
    reg = er.async_get(hass)
    bound = reg.async_get_or_create("number", DOMAIN, "iso_upper_bound", config_entry=entry)
    room = reg.async_get_or_create("number", DOMAIN, "77_comfort_setpoint", config_entry=entry)
    foreign = reg.async_get_or_create("number", DOMAIN, "iso_lower_bound", config_entry=other)

    number.remove_closed_head_numbers(
        hass, entry, ["iso_upper_bound", "iso_lower_bound", "never_registered"]
    )

    assert reg.async_get(bound.entity_id) is None  # the disarmed trial's entity is gone
    assert reg.async_get(room.entity_id) is not None  # a room's number is never touched
    assert reg.async_get(foreign.entity_id) is not None  # nor another config entry's entity
