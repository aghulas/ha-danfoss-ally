"""number platform: an isolated head's comfort / setback / pause setpoints over Tuya cloud MQTT.

Fake coordinator and link, synthetic data, no network.
"""

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.danfoss_ally_cloud.api import CloudError
from custom_components.danfoss_ally_cloud.number import (
    HEAD_SETPOINTS,
    DanfossHeadSetpoint,
    settings_block,
)

from . import test_number_bounds as bounds_tests
from .common import head
from .test_number_bounds import _setup as _setup_platform
from .test_switch import _FakeClient, _FakeCloudCoord, _FakeMqttLink

COMFORT = next(d for d in HEAD_SETPOINTS if d.setpoint == "comfort")
SETBACK = next(d for d in HEAD_SETPOINTS if d.setpoint == "setback")
PAUSE = next(d for d in HEAD_SETPOINTS if d.setpoint == "pause")
TRIAL = frozenset({118, 16, 119, 120})
BLOCK_DPS = {"1": False, "118": 210, "119": 140, "121": 145}


def _head(**kw):
    base = dict(
        max_setpoint=28.0,
        min_setpoint=5.0,
        setpoints={"comfort": 21.0, "setback": 14.0, "pause": 5.0},
        dps=dict(BLOCK_DPS),
    )
    base.update(kw)
    return head(**base)


def _number(desc, dev, *, link=None, supervised=TRIAL, groups=None, client=None):
    client = client or _FakeClient()
    coord = _FakeCloudCoord({dev.id: dev}, client=client, groups=groups)
    link = link or _FakeMqttLink()
    return DanfossHeadSetpoint(coord, dev.id, desc, link, supervised), coord, link, client


def test_setpoint_reads_the_head_value_within_its_own_bounds():
    ent, _, _, _ = _number(COMFORT, _head())
    assert ent.native_value == 21.0
    assert (ent.native_min_value, ent.native_max_value) == (5.0, 28.0)
    assert ent.unique_id == "dev-1_comfort_setpoint"
    ent, _, _, _ = _number(PAUSE, _head(max_setpoint=None, min_setpoint=None))
    assert ent.native_value == 5.0
    assert (ent.native_min_value, ent.native_max_value) == (5.0, 35.0)  # schema fallback


def test_setpoint_under_trial_states_its_route():
    ent, _, _, _ = _number(SETBACK, _head())
    assert ent.available is True
    assert ent.extra_state_attributes == {
        "write_path": "cloud_mqtt",
        "write_scope": "head",
        "write_trial": True,
    }


def test_comfort_needs_both_of_its_dps_open():
    ent, _, _, _ = _number(COMFORT, _head(), supervised=frozenset({118}))  # 16 not opened
    assert ent.available is False and ent.extra_state_attributes == {"write_path": "none"}


def test_setpoint_unavailable_for_a_grouped_head_or_a_down_link():
    dev = _head()
    ent, _, _, _ = _number(COMFORT, dev, groups={dev.id: "g1"})
    assert ent.available is False  # a grouped head is written through its room
    ent, _, _, _ = _number(COMFORT, _head(), link=_FakeMqttLink(connected=False))
    assert ent.available is False


async def test_comfort_publishes_118_and_16_then_posts_the_whole_block():
    dev = _head()
    ent, coord, link, client = _number(COMFORT, dev)
    await ent.async_set_native_value(20.5)
    assert link.published == [("gw-1", "node-1", {"118": 205, "16": 205})]  # one frame
    assert link.confirmations == [("node-1", 118, 205)]  # only the setting DP must be confirmed
    assert client.calls == [
        (dev.id, "03wvrwpv", {"1": False, "118": 205, "119": 140, "121": 145}, None)
    ]  # gw_id None -> gwId = devId, as the app sends this block
    assert list(client.calls[0][2]) == ["1", "118", "119", "121"]
    assert coord.commanded == [dev.id]


async def test_setback_publishes_119_alone_then_posts_the_whole_block():
    dev = _head()
    ent, _, link, client = _number(SETBACK, dev)
    await ent.async_set_native_value(14.5)
    assert link.published == [("gw-1", "node-1", {"119": 145})]  # no DP 109 on an isolated head
    assert client.calls[0][2] == {"1": False, "118": 210, "119": 145, "121": 145}


async def test_pause_publishes_120_and_posts_no_block():
    ent, _, link, client = _number(PAUSE, _head())
    await ent.async_set_native_value(6.0)
    assert link.published == [("gw-1", "node-1", {"120": 60})]
    assert client.calls == []


@pytest.mark.parametrize("value", [4.5, 28.5, "abc"])
async def test_setpoint_outside_the_head_bounds_is_refused_before_sending(value):
    ent, _, link, client = _number(COMFORT, _head())
    with pytest.raises(HomeAssistantError, match="setpoint refused"):
        await ent.async_set_native_value(value)
    assert link.published == [] and client.calls == []


async def test_nothing_is_sent_when_the_settings_block_cannot_be_built():
    dev = _head(dps={"1": False, "118": 210, "119": 140})  # DP 121 unknown
    ent, _, link, client = _number(COMFORT, dev)
    with pytest.raises(HomeAssistantError, match="DP 121"):
        await ent.async_set_native_value(20.5)
    assert link.published == [] and client.calls == []


async def test_unconfirmed_publish_posts_no_block():
    ent, _, link, client = _number(COMFORT, _head(), link=_FakeMqttLink(confirm=False))
    with pytest.raises(HomeAssistantError, match="not confirmed"):
        await ent.async_set_native_value(20.5)
    assert link.published and client.calls == []  # the cloud store is not touched


async def test_confirmation_by_per_device_read_ignores_the_companion_dp():
    """No echo: the head's own route shows 118 at the new value while 16 follows the schedule."""
    dev = _head()
    client = _FakeClient()
    client.device_dps = {dev.id: {"118": 205, "16": 140}}
    ent, _, _, _ = _number(COMFORT, dev, link=_FakeMqttLink(confirm=False), client=client)
    await ent.async_set_native_value(20.5)
    assert len(client.calls) == 1  # confirmed, so the block is posted


async def test_refused_block_after_a_confirmed_write_says_so():
    class _Refusing(_FakeClient):
        async def async_write_setting(self, dev_id, pid, dps, *, gw_id=None):
            raise CloudError("synthetic refusal")

    ent, _, link, _ = _number(SETBACK, _head(), client=_Refusing())
    with pytest.raises(HomeAssistantError, match="written on the head and confirmed"):
        await ent.async_set_native_value(14.5)
    assert link.published


async def test_write_refused_when_the_route_is_gone():
    ent, _, link, _ = _number(COMFORT, _head(), link=_FakeMqttLink(connected=False))
    with pytest.raises(HomeAssistantError, match="unavailable"):
        await ent.async_set_native_value(20.5)
    assert link.published == []


def test_settings_block_keeps_current_values_and_applies_the_change():
    assert settings_block(_head(), {119: 150}) == {"1": False, "118": 210, "119": 150, "121": 145}
    with pytest.raises(HomeAssistantError, match="DP 1 "):
        settings_block(_head(dps={"118": 210, "119": 140, "121": 145}), {118: 200})


def _removed_setpoints():
    return [uid for uid in bounds_tests.REMOVED if uid.endswith("_setpoint")]


async def test_setpoint_entities_only_for_open_settings_of_isolated_heads():
    kind = DanfossHeadSetpoint
    all_three = ["iso_comfort_setpoint", "iso_setback_setpoint", "iso_pause_setpoint"]
    iso = _head(dev_id="iso")
    assert await _setup_platform([iso], supervised=frozenset(), kind=kind) == []  # closed
    assert _removed_setpoints() == all_three
    assert await _setup_platform([iso], supervised=TRIAL, cloud_mqtt=False, kind=kind) == []
    assert _removed_setpoints() == all_three
    assert await _setup_platform([iso], supervised=TRIAL, trial_head=None, kind=kind) == []
    assert _removed_setpoints() == all_three  # no trial head designated: nothing is open
    # The link failed to start: transient, nothing created and nothing removed.
    assert await _setup_platform([iso], supervised=TRIAL, link=False, kind=kind) == []
    assert _removed_setpoints() == []

    grouped = _head(dev_id="grp")
    ents = await _setup_platform([iso, grouped], supervised=TRIAL, groups={"grp": "g1"}, kind=kind)
    assert sorted(e.unique_id for e in ents) == sorted(all_three)
    assert _removed_setpoints() == [u.replace("iso_", "grp_") for u in all_three]
    # Comfort needs 118 AND 16: with 118 alone there is no comfort entity.
    ents = await _setup_platform([iso], supervised=frozenset({118, 119}), kind=kind)
    assert [e.unique_id for e in ents] == ["iso_setback_setpoint"]
    assert _removed_setpoints() == ["iso_comfort_setpoint", "iso_pause_setpoint"]


async def test_setpoint_trial_is_confined_to_the_designated_head():
    """Two isolated heads, a trial armed on one: the other head gets no setpoint entity, so nothing
    of it can be written through the channel under trial."""
    kind = DanfossHeadSetpoint
    ents = await _setup_platform(
        [_head(dev_id="iso"), _head(dev_id="iso2")], supervised=TRIAL, trial_head="iso", kind=kind
    )
    assert {e.unique_id.split("_")[0] for e in ents} == {"iso"}
    assert _removed_setpoints() == [
        "iso2_comfort_setpoint",
        "iso2_setback_setpoint",
        "iso2_pause_setpoint",
    ]
