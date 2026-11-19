"""A supervised cloud-MQTT trial is confined to ONE designated head.

Ticking a candidate DP must not open it on every isolated head of the install: only the designated
trial head routes through the channel under trial, every other head keeps its normal routing.
hass harness, paho faked, synthetic data.
"""

import json
import logging
from unittest.mock import AsyncMock, patch

import paho.mqtt.client as paho
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud.api import GatewayKey
from custom_components.danfoss_ally_cloud.const import (
    CONF_CLOUD_MQTT_SUPERVISED_DPS,
    CONF_CLOUD_MQTT_SUPERVISED_HEAD,
    CONF_ENABLE_CLOUD_MQTT,
    DATA_MQTT_SUPERVISED_DPS,
    DATA_MQTT_SUPERVISED_HEAD,
    DOMAIN,
)
from custom_components.danfoss_ally_cloud.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.danfoss_ally_cloud.mqtt_write import supervised_for
from custom_components.danfoss_ally_cloud.switch import PATH_MQTT, PATH_NONE, DanfossSwitch

from .common import ENTRY_DATA, FakeCloudClient, head
from .test_mqtt_client import _FakePaho

_GW = {"gw-1": GatewayKey("gw-1", "GW", "0123456789abcdef", ip="10.0.0.1")}
_ROOM = [{"group_id": 77, "name": "Salle", "pid": "03wvrwpv", "head_count": 2}]


def _fleet():
    """Two isolated heads, two grouped heads, one isolated head on an unverified model."""
    return FakeCloudClient(
        devices=[
            head("trial-head-id", "Test head", node_id="n1"),
            head("other-head-id", "Other head", node_id="n2"),
            head("g1", "Grouped one", node_id="n3"),
            head("g2", "Grouped two", node_id="n4"),
            head("unverified-id", "Unverified", node_id="n5", product_id="unverified"),
        ],
        groups=_ROOM,
        members={"77": ["g1", "g2"]},
    )


@pytest.fixture
def fake_paho(monkeypatch):
    _FakePaho.instances.clear()
    monkeypatch.setattr(paho, "Client", _FakePaho)
    return _FakePaho


async def _setup(hass: HomeAssistant, options):
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr", options=options
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=_fleet()),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value=_GW),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    if _FakePaho.instances:
        c = _FakePaho.instances[-1]
        c.on_connect(c, None, None, 0)
    return entry


def _window_switch(hass, device_id):
    return next(
        e
        for e in hass.data["entity_components"]["switch"].entities
        if isinstance(e, DanfossSwitch)
        and e.entity_description.key == "window_detection"
        and e._device_id == device_id
    )


def test_supervised_for_gives_the_trial_set_to_the_designated_head_only():
    data = {
        DATA_MQTT_SUPERVISED_DPS: frozenset({116}),
        DATA_MQTT_SUPERVISED_HEAD: "trial-head-id",
    }
    assert supervised_for(data, "trial-head-id") == frozenset({116})
    assert supervised_for(data, "other-head-id") == frozenset()
    # No head designated: nothing opens anywhere, whatever is ticked.
    assert (
        supervised_for({DATA_MQTT_SUPERVISED_DPS: frozenset({116})}, "trial-head-id") == frozenset()
    )
    assert supervised_for({**data, DATA_MQTT_SUPERVISED_HEAD: None}, "trial-head-id") == frozenset()
    assert supervised_for({}, "trial-head-id") == frozenset()


async def test_trial_opens_on_the_designated_head_and_nowhere_else(hass: HomeAssistant, fake_paho):
    await _setup(
        hass,
        {
            CONF_ENABLE_CLOUD_MQTT: True,
            CONF_CLOUD_MQTT_SUPERVISED_DPS: ["116"],
            CONF_CLOUD_MQTT_SUPERVISED_HEAD: "trial-head-id",
        },
    )
    trial = _window_switch(hass, "trial-head-id")
    assert trial._write_path(trial.device) == PATH_MQTT
    assert trial.extra_state_attributes["write_trial"] is True
    # The other isolated head keeps its normal routing: DP 116 is not proven on cloud MQTT and no
    # tunnel is configured here, so it has no route. It must NOT go through the channel on trial.
    other = _window_switch(hass, "other-head-id")
    assert other._write_path(other.device) == PATH_NONE
    assert other.extra_state_attributes == {"write_path": "none"}
    await other.async_turn_off()
    assert fake_paho.instances[-1].published == []


async def test_ticked_dp_without_a_designated_head_opens_nothing(
    hass: HomeAssistant, fake_paho, caplog
):
    caplog.set_level(logging.WARNING)
    await _setup(hass, {CONF_ENABLE_CLOUD_MQTT: True, CONF_CLOUD_MQTT_SUPERVISED_DPS: ["116"]})
    for device_id in ("trial-head-id", "other-head-id"):
        sw = _window_switch(hass, device_id)
        assert sw._write_path(sw.device) == PATH_NONE
    assert "no trial head is designated" in caplog.text


async def test_trial_head_is_never_logged_and_is_redacted_in_the_diagnostics(
    hass: HomeAssistant, fake_paho, caplog
):
    caplog.set_level(logging.DEBUG)
    entry = await _setup(
        hass,
        {
            CONF_ENABLE_CLOUD_MQTT: True,
            CONF_CLOUD_MQTT_SUPERVISED_DPS: ["116"],
            CONF_CLOUD_MQTT_SUPERVISED_HEAD: "trial-head-id",
        },
    )
    assert "designated trial head only" in caplog.text
    assert "trial-head-id" not in caplog.text
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["options"][CONF_CLOUD_MQTT_SUPERVISED_HEAD] == "**REDACTED**"
    assert "trial-head-id" not in json.dumps(diag)


async def test_options_form_offers_only_isolated_verified_heads(hass: HomeAssistant, fake_paho):
    entry = await _setup(hass, {CONF_ENABLE_CLOUD_MQTT: True})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    field = next(
        k for k in result["data_schema"].schema if str(k) == CONF_CLOUD_MQTT_SUPERVISED_HEAD
    )
    choices = result["data_schema"].schema[field].container
    assert choices == {"": "—", "trial-head-id": "Test head", "other-head-id": "Other head"}
    assert field.default() == ""  # no trial head by default

    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=_fleet()),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value=_GW),
        ),
    ):
        done = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_ENABLE_CLOUD_MQTT: True,
                CONF_CLOUD_MQTT_SUPERVISED_DPS: ["116"],
                CONF_CLOUD_MQTT_SUPERVISED_HEAD: "trial-head-id",
            },
        )
        await hass.async_block_till_done()
    assert done["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_CLOUD_MQTT_SUPERVISED_HEAD] == "trial-head-id"
    assert hass.data[DOMAIN][entry.entry_id][DATA_MQTT_SUPERVISED_HEAD] == "trial-head-id"


async def test_options_form_keeps_a_designated_head_that_is_no_longer_offered(hass: HomeAssistant):
    """Entry not loaded (or the head got grouped): the stored value stays selectable, so opening
    the form does not silently change the option."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id="compte@exemple.fr",
        options={CONF_CLOUD_MQTT_SUPERVISED_HEAD: "gone-head-id"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    field = next(
        k for k in result["data_schema"].schema if str(k) == CONF_CLOUD_MQTT_SUPERVISED_HEAD
    )
    assert result["data_schema"].schema[field].container == {
        "": "—",
        "gone-head-id": "(head not available)",
    }
