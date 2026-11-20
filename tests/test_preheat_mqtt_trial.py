"""Preheat (DP 1) over Tuya cloud MQTT: a closed candidate, confirmed by the local tunnel only.

DP 1 is the known trap: over HTTP it only changed the gateway cache. So the gateway's echo and the
cloud read are never accepted for it; only the head's attribute 0x0025, read through the tunnel,
confirms a write. Doubles only, synthetic data.
"""

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import paho.mqtt.client as paho
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud import mqtt_write
from custom_components.danfoss_ally_cloud.api import (
    CloudError,
    CloudWriteError,
    GatewayKey,
    writes,
)
from custom_components.danfoss_ally_cloud.const import (
    CONF_CLOUD_MQTT_SUPERVISED_DPS,
    CONF_CLOUD_MQTT_SUPERVISED_HEAD,
    CONF_ENABLE_CLOUD_MQTT,
    CONF_ENABLE_LOCAL,
    DATA_MQTT_SUPERVISED_DPS,
    DOMAIN,
)
from custom_components.danfoss_ally_cloud.mqtt_write import (
    CONFIRMED_BY_TUNNEL,
    UNCHANGED,
    async_mqtt_write,
    async_mqtt_write_preheat,
)
from custom_components.danfoss_ally_cloud.switch import PATH_LOCAL, PATH_MQTT, DanfossPreheat

from .common import ENTRY_DATA, FakeCloudClient
from .common import head as _bare_head
from .test_coordinator_local import FakeManager
from .test_mqtt_client import _FakePaho

_ARMED = frozenset({1})
# The cloud's values of the app's settings block (preheat, comfort, setback, holiday setpoints).
_BLOCK = {"1": False, "118": 210, "119": 140, "121": 145}


def head(*args, **kw):
    """A synthetic head whose cloud DPs carry the settings block."""
    kw.setdefault("dps", dict(_BLOCK))
    return _bare_head(*args, **kw)


def _cloud(write_setting=None):
    """Double of the cloud coordinator: only the HTTP settings call is used."""
    cloud = MagicMock()
    cloud.client.async_write_setting = write_setting or AsyncMock()
    return cloud


@pytest.fixture(autouse=True)
def _fast_confirmation(monkeypatch):
    """No real waiting between two tunnel reads; two reads at most after the publish."""
    monkeypatch.setattr(mqtt_write, "PREHEAT_CONFIRM_INTERVAL", 0.0)
    monkeypatch.setattr(mqtt_write, "PREHEAT_CONFIRM_TIMEOUT", 0.0)


class _Local:
    """Double of the local coordinator: the tunnel reads of one head, in order."""

    def __init__(self, reads):
        self._reads = list(reads)
        self.read_heads: list = []
        self.data: dict = {}
        self.manager = MagicMock()
        self.manager.write_preheat = MagicMock(return_value=True)

    async def async_refresh_head(self, head_):
        self.read_heads.append(head_)
        value = self._reads.pop(0) if self._reads else self.data.get(head_.dev_id)
        self.data[head_.dev_id] = value
        return value


def _link(can_publish=True):
    link = MagicMock()
    link.can_publish = MagicMock(return_value=can_publish)
    link.publish_dp = AsyncMock()
    link.await_confirmation = AsyncMock(return_value=True)  # an echo that must never be used
    return link


# --- value rule and gate ------------------------------------------------------------------------


def test_dp1_is_a_closed_candidate_confirmed_by_the_tunnel_only():
    assert 1 in writes.MQTT_CANDIDATE_DPS
    assert 1 not in writes.MQTT_WRITE_DPS
    assert 1 in writes.MQTT_TUNNEL_CONFIRMED_DPS
    # Every tunnel-confirmed DP is at most a candidate: none is open by default.
    assert writes.MQTT_TUNNEL_CONFIRMED_DPS <= writes.MQTT_CANDIDATE_DPS
    assert writes.mqtt_dp_open(1) is False
    assert writes.mqtt_dp_open(1, _ARMED) is True


def test_dp1_value_must_be_a_boolean_and_listed():
    assert writes.mqtt_write_value(1, True, _ARMED) is True
    assert writes.mqtt_write_value(1, False, _ARMED) is False
    with pytest.raises(CloudWriteError, match="supervised first write"):
        writes.mqtt_write_value(1, True)
    with pytest.raises(CloudWriteError, match="boolean"):
        writes.mqtt_write_value(1, 1, _ARMED)


async def test_generic_mqtt_write_refuses_dp1_even_when_armed():
    """The generic write confirms by echo or cloud read: worthless for preheat, so it refuses."""
    link = _link()
    coordinator = MagicMock()
    with pytest.raises(HomeAssistantError, match="local tunnel"):
        await async_mqtt_write(coordinator, link, head(), {1: True}, supervised=_ARMED)
    # Also when DP 1 rides along with another DP.
    with pytest.raises(HomeAssistantError, match="local tunnel"):
        await async_mqtt_write(coordinator, link, head(), {30: True, 1: True}, supervised=_ARMED)
    link.publish_dp.assert_not_awaited()
    link.await_confirmation.assert_not_called()


# --- the tunnel-confirmed write -----------------------------------------------------------------


async def test_preheat_write_closed_by_default_sends_and_reads_nothing():
    local, link = _Local([False]), _link()
    with pytest.raises(HomeAssistantError, match="supervised first write"):
        await async_mqtt_write_preheat(local, _cloud(), link, head(), True)
    assert local.read_heads == []
    link.publish_dp.assert_not_awaited()


async def test_preheat_write_refused_when_the_tunnel_does_not_answer_first():
    local, link = _Local([None]), _link()
    with pytest.raises(HomeAssistantError, match="does not answer through the local tunnel"):
        await async_mqtt_write_preheat(local, _cloud(), link, head(), True, supervised=_ARMED)
    link.publish_dp.assert_not_awaited()


async def test_preheat_write_needs_the_gateway_address():
    local, link = _Local([False]), _link()
    with pytest.raises(HomeAssistantError, match="gateway address"):
        await async_mqtt_write_preheat(
            local, _cloud(), link, head(node_id=None), True, supervised=_ARMED
        )
    link.publish_dp.assert_not_awaited()


async def test_preheat_already_at_the_value_publishes_nothing():
    local, link = _Local([True]), _link()
    assert (
        await async_mqtt_write_preheat(local, _cloud(), link, head(), True, supervised=_ARMED)
        == UNCHANGED
    )
    link.publish_dp.assert_not_awaited()


async def test_preheat_confirmed_by_the_tunnel_read(monkeypatch):
    monkeypatch.setattr(mqtt_write, "PREHEAT_CONFIRM_TIMEOUT", 60.0)
    local, link = _Local([False, False, True]), _link()  # before, still old, then the new value
    dev = head("dev-1", node_id="node-1", mesh_id="gw-1")
    order: list[str] = []
    link.publish_dp.side_effect = lambda *a: order.append("mqtt")
    cloud = _cloud(AsyncMock(side_effect=lambda *a: order.append("http")))
    result = await async_mqtt_write_preheat(local, cloud, link, dev, True, supervised=_ARMED)
    assert result == CONFIRMED_BY_TUNNEL
    link.publish_dp.assert_awaited_once_with("gw-1", "node-1", {"1": True})
    # Then the WHOLE settings block over HTTP, as the app does, with only DP 1 changed.
    cloud.client.async_write_setting.assert_awaited_once_with(
        "dev-1", "03wvrwpv", {"1": True, "118": 210, "119": 140, "121": 145}
    )
    assert order == ["mqtt", "http"]
    assert [(h.dev_id, h.node_id, h.gateway_id) for h in local.read_heads] == [
        ("dev-1", "node-1", "gw-1")
    ] * 3
    link.await_confirmation.assert_not_called()  # the echo is never listened to


async def test_preheat_not_confirmed_when_the_head_does_not_change():
    """The "accepted but not applied" case: the gateway would echo, the head keeps its value."""
    local, link = _Local([False, False]), _link()
    with pytest.raises(HomeAssistantError, match="not confirmed") as err:
        await async_mqtt_write_preheat(local, _cloud(), link, head(), True, supervised=_ARMED)
    # The message does not claim more than is known: the frame left, and may still apply later.
    assert "the frame and the settings block were sent" in str(err.value)
    assert " s later" in str(err.value)  # the time really elapsed, not the nominal timeout
    assert "may still apply it later" in str(err.value)
    link.publish_dp.assert_awaited_once()
    assert local.data["dev-1"] is False  # the switch keeps showing what the head said
    link.await_confirmation.assert_not_called()


async def test_toggling_back_after_a_failed_trial_publishes_nothing():
    """Documented limit: after a "not confirmed", asking for the head's own value again sends
    nothing (the tunnel could not confirm such a publish). The cloud's DP 1 is resynchronised from
    the Danfoss app (DP 1 sheet of docs/first-write-procedure.md), never by a blind publish."""
    local, link = _Local([False, False, False]), _link()
    with pytest.raises(HomeAssistantError, match="not confirmed"):
        await async_mqtt_write_preheat(local, _cloud(), link, head(), True, supervised=_ARMED)
    assert (
        await async_mqtt_write_preheat(local, _cloud(), link, head(), False, supervised=_ARMED)
        == UNCHANGED
    )
    link.publish_dp.assert_awaited_once_with("gw-1", "node-1", {"1": True})  # the trial only


async def test_preheat_not_confirmed_when_the_tunnel_stops_answering():
    local, link = _Local([False, None]), _link()
    with pytest.raises(HomeAssistantError, match="not confirmed"):
        await async_mqtt_write_preheat(local, _cloud(), link, head(), True, supervised=_ARMED)
    assert local.data["dev-1"] is None  # unknown: the switch is unavailable, not optimistic


async def test_preheat_refused_when_the_settings_block_cannot_be_built():
    """A value of the block unknown in the cloud: nothing is read, nothing is sent."""
    local, link, cloud = _Local([False]), _link(), _cloud()
    dev = head(dps={"1": False, "118": 210, "119": 140})  # DP 121 missing
    with pytest.raises(HomeAssistantError, match="settings block is unknown"):
        await async_mqtt_write_preheat(local, cloud, link, dev, True, supervised=_ARMED)
    assert local.read_heads == []
    link.publish_dp.assert_not_awaited()
    cloud.client.async_write_setting.assert_not_awaited()


async def test_preheat_settings_block_refused_by_the_cloud_is_surfaced():
    """The frame left, the HTTP block was refused: a clear error, and the head is read once so the
    switch shows what it says. No confirmation loop: the trial is of the pair, not of the frame."""
    local, link = _Local([False, False]), _link()
    cloud = _cloud(AsyncMock(side_effect=CloudError("refused")))
    with pytest.raises(HomeAssistantError, match="settings block was refused"):
        await async_mqtt_write_preheat(local, cloud, link, head(), True, supervised=_ARMED)
    link.publish_dp.assert_awaited_once()
    assert len(local.read_heads) == 2
    assert local.data["dev-1"] is False


async def test_nothing_goes_over_http_when_nothing_is_published():
    for reads in ([None], [True]):  # tunnel silent; head already at the value
        local, link, cloud = _Local(reads), _link(), _cloud()
        with contextlib.suppress(HomeAssistantError):
            await async_mqtt_write_preheat(local, cloud, link, head(), True, supervised=_ARMED)
        cloud.client.async_write_setting.assert_not_awaited()


async def test_preheat_publish_failure_is_surfaced():
    local, link = _Local([False]), _link()
    link.publish_dp.side_effect = RuntimeError("not connected")
    cloud = _cloud()
    with pytest.raises(HomeAssistantError, match="write failed"):
        await async_mqtt_write_preheat(local, cloud, link, head(), True, supervised=_ARMED)
    assert len(local.read_heads) == 1  # no read-back loop after a failed send
    cloud.client.async_write_setting.assert_not_awaited()  # and no HTTP block either


# --- the preheat switch -------------------------------------------------------------------------


def _switch(local, link, *, enabled=True, supervised=_ARMED, dev=None, grouped=False):
    dev = dev or head()
    cloud = MagicMock()
    cloud.data = {dev.id: dev}
    cloud.group_of = MagicMock(return_value="g-synth" if grouped else None)
    cloud.client.async_write_setting = AsyncMock()
    ent = DanfossPreheat(local, cloud, dev.id, link, enabled, supervised)
    ent.hass = MagicMock()
    ent.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda func, *args: func(*args)  # run the "executor job" inline
    )
    return ent


async def test_switch_on_trial_writes_over_mqtt_and_never_through_the_tunnel(monkeypatch):
    monkeypatch.setattr(mqtt_write, "PREHEAT_CONFIRM_TIMEOUT", 60.0)
    local, link = _Local([False, True]), _link()
    ent = _switch(local, link)
    assert ent.extra_state_attributes == {
        "write_path": PATH_MQTT,
        "write_scope": "head",
        "write_trial": True,
    }
    await ent.async_turn_on()
    link.publish_dp.assert_awaited_once_with("gw-1", "node-1", {"1": True})
    ent._cloud.client.async_write_setting.assert_awaited_once()
    local.manager.write_preheat.assert_not_called()


async def test_switch_on_trial_with_the_link_down_writes_nothing():
    """Armed trial, link down: no silent fallback to the tunnel (it would credit the wrong
    channel), a clear error instead."""
    local, link = _Local([False]), _link(can_publish=False)
    ent = _switch(local, link)
    with pytest.raises(HomeAssistantError, match="nothing was written"):
        await ent.async_turn_on()
    link.publish_dp.assert_not_awaited()
    local.manager.write_preheat.assert_not_called()
    # Same without any link object.
    ent = _switch(local, None)
    with pytest.raises(HomeAssistantError, match="nothing was written"):
        await ent.async_turn_off()
    local.manager.write_preheat.assert_not_called()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"supervised": frozenset()},  # DP 1 not listed (the default), or another head's trial
        {"supervised": frozenset({116})},  # another DP under trial on this head
        {"enabled": False},  # cloud-MQTT option off
        {"grouped": True},  # a head in a room: the app's MQTT publish is for isolated heads
        {"dev": head(product_id="unverified")},  # model outside the guard-rail
    ],
)
async def test_switch_not_on_trial_keeps_the_tunnel_write(kwargs):
    local, link = _Local([True]), _link()
    ent = _switch(local, link, **kwargs)
    assert ent.extra_state_attributes == {"write_path": PATH_LOCAL, "write_scope": "head"}
    await ent.async_turn_on()
    local.manager.write_preheat.assert_called_once()
    link.publish_dp.assert_not_awaited()


# --- setup: the trial is confined to its designated head ----------------------------------------

_GW = {"gw-1": GatewayKey("gw-1", "GW", "0123456789abcdef", ip="10.0.0.1")}


@pytest.fixture
def fake_paho(monkeypatch):
    _FakePaho.instances.clear()
    monkeypatch.setattr(paho, "Client", _FakePaho)
    return _FakePaho


async def _setup(hass: HomeAssistant, options):
    fleet = FakeCloudClient(
        devices=[
            head("trial-head-id", "Test head", node_id="n1"),
            head("other-head-id", "Other head", node_id="n2"),
        ]
    )
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr", options=options
    )
    entry.add_to_hass(hass)
    manager = FakeManager(survey={"trial-head-id": False, "other-head-id": False})
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fleet),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value=_GW),
        ),
        patch("custom_components.danfoss_ally_cloud.LocalTunnelManager", return_value=manager),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    if _FakePaho.instances:
        c = _FakePaho.instances[-1]
        c.on_connect(c, None, None, 0)
    return entry, manager


def _preheat_switch(hass, device_id):
    return next(
        e
        for e in hass.data["entity_components"]["switch"].entities
        if isinstance(e, DanfossPreheat) and e._device_id == device_id
    )


async def test_setup_arms_preheat_on_the_designated_head_only(hass: HomeAssistant, fake_paho):
    entry, manager = await _setup(
        hass,
        {
            CONF_ENABLE_LOCAL: True,
            CONF_ENABLE_CLOUD_MQTT: True,
            CONF_CLOUD_MQTT_SUPERVISED_DPS: ["1"],
            CONF_CLOUD_MQTT_SUPERVISED_HEAD: "trial-head-id",
        },
    )
    assert hass.data[DOMAIN][entry.entry_id][DATA_MQTT_SUPERVISED_DPS] == _ARMED
    trial = _preheat_switch(hass, "trial-head-id")
    assert trial.extra_state_attributes["write_path"] == PATH_MQTT
    assert trial.extra_state_attributes["write_trial"] is True
    # The other isolated head keeps the tunnel: its write does not touch the channel on trial.
    other = _preheat_switch(hass, "other-head-id")
    assert other.extra_state_attributes == {"write_path": PATH_LOCAL, "write_scope": "head"}
    await other.async_turn_on()
    assert manager.ecrits == [("other-head-id", True)]
    assert fake_paho.instances[-1].published == []


async def test_setup_default_options_keep_preheat_on_the_tunnel(hass: HomeAssistant, fake_paho):
    """DP 1 not listed (the default): cloud MQTT on changes nothing for preheat."""
    _, manager = await _setup(hass, {CONF_ENABLE_LOCAL: True, CONF_ENABLE_CLOUD_MQTT: True})
    for device_id in ("trial-head-id", "other-head-id"):
        sw = _preheat_switch(hass, device_id)
        assert sw.extra_state_attributes == {"write_path": PATH_LOCAL, "write_scope": "head"}
    await _preheat_switch(hass, "trial-head-id").async_turn_on()
    assert manager.ecrits == [("trial-head-id", True)]
    assert fake_paho.instances[-1].published == []
