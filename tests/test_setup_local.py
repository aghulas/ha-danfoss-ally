"""Mise en place runtime : repli local + publication MQTT + rechargement (harnais hass).

Couvre les branches de __init__ (local/MQTT), la branche locale de switch.async_setup_entry
(creation of the preheat switch) and its write. Everything is doubled: no network, no tinytuya,
no real broker.
"""

from unittest.mock import AsyncMock, patch

import homeassistant.components.mqtt as mqtt_mod
import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.danfoss_ally_cloud as integration
from custom_components.danfoss_ally_cloud.api import GatewayKey
from custom_components.danfoss_ally_cloud.const import (
    CONF_ENABLE_LOCAL,
    CONF_MQTT_MODE,
    DATA_LOCAL,
    DATA_MQTT,
    DOMAIN,
)

from .common import ENTRY_DATA, FakeCloudClient, head
from .test_coordinator_local import FakeManager

_GW = {"gw-1": GatewayKey("gw-1", "GW", "cle-synth", ip="10.0.0.1")}


@pytest.fixture
def mqtt_double(monkeypatch):
    publie = AsyncMock()
    monkeypatch.setattr(mqtt_mod, "async_publish", publie)
    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    return publie


async def _setup(hass: HomeAssistant, fake: FakeCloudClient, manager: FakeManager):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id="compte@exemple.fr",
        options={CONF_ENABLE_LOCAL: True, CONF_MQTT_MODE: "discovery"},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value=_GW),
        ),
        patch("custom_components.danfoss_ally_cloud.LocalTunnelManager", return_value=manager),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_setup_local_et_mqtt(hass: HomeAssistant, mqtt_double):
    fake = FakeCloudClient(devices=[head()])
    manager = FakeManager(survey={"dev-1": True})
    entry = await _setup(hass, fake, manager)

    data = hass.data[DOMAIN][entry.entry_id]
    assert data[DATA_LOCAL] is not None  # coordinateur local en place
    assert data[DATA_MQTT] is not None  # MQTT publisher started
    assert mqtt_double.await_count > 0  # published (simulated broker present)

    # The preheat switch is created (head attached to a known gateway) and is ON.
    etat = hass.states.get("switch.salon_pre_heating")
    assert etat is not None and etat.state == "on"

    # Preheat write via the HA service: goes through the manager.
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.salon_pre_heating"}, blocking=True
    )
    assert manager.ecrits == [("dev-1", False)]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert fake.closed is True


async def test_local_without_gateway_returns_none(hass: HomeAssistant):
    """enable_local with no keyed gateway: local fallback = None, the cloud starts anyway."""
    fake = FakeCloudClient(devices=[head()])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id="compte@exemple.fr",
        options={CONF_ENABLE_LOCAL: True},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value={}),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.data[DOMAIN][entry.entry_id][DATA_LOCAL] is None


async def test_local_echec_recuperation_cles(hass: HomeAssistant):
    """A key-fetch error must not prevent the cloud from starting."""
    fake = FakeCloudClient(devices=[head()])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id="compte@exemple.fr",
        options={CONF_ENABLE_LOCAL: True},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(side_effect=RuntimeError("cloud ko")),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.data[DOMAIN][entry.entry_id][DATA_LOCAL] is None


async def test_update_options_recharge(hass: HomeAssistant, mqtt_double):
    fake = FakeCloudClient(devices=[head()])
    manager = FakeManager(survey={"dev-1": True})
    entry = await _setup(hass, fake, manager)
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value=_GW),
        ),
        patch("custom_components.danfoss_ally_cloud.LocalTunnelManager", return_value=manager),
    ):
        await integration._async_update_options(hass, entry)
        await hass.async_block_till_done()
    # The entry is still in place after reload.
    assert entry.entry_id in hass.data[DOMAIN]


async def test_cloud_mqtt_live_link_setup_routes_isolated_switch(hass: HomeAssistant, monkeypatch):
    """enable_cloud_mqtt ON: a live link is created from the integration's own session and connects;
    an isolated head's child-lock switch then routes via cloud MQTT. paho is faked (no network)."""
    import paho.mqtt.client as paho

    from custom_components.danfoss_ally_cloud.const import CONF_ENABLE_CLOUD_MQTT, DATA_MQTT_LINK

    from .test_mqtt_client import _FakePaho

    _FakePaho.instances.clear()
    monkeypatch.setattr(paho, "Client", _FakePaho)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id="compte@exemple.fr",
        options={CONF_ENABLE_CLOUD_MQTT: True},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=FakeCloudClient()),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value=_GW),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    link = hass.data[DOMAIN][entry.entry_id][DATA_MQTT_LINK]
    assert link is not None
    c = _FakePaho.instances[-1]
    c.on_connect(c, None, None, 0)  # broker accepts -> link usable
    assert link.can_publish("gw-1") is True

    # The isolated head's child_lock switch now routes via cloud MQTT (default head has no group).
    from custom_components.danfoss_ally_cloud.switch import PATH_MQTT, DanfossSwitch

    sw = next(
        e
        for e in hass.data["entity_components"]["switch"].entities
        if isinstance(e, DanfossSwitch) and e.entity_description.key == "child_lock"
    )
    assert sw._write_path(sw.device) == PATH_MQTT
    assert sw.available is True

    import threading

    loop_thread = threading.current_thread()
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert c.loop_stopped and c.disconnected  # link closed on unload
    # loop_stop() joins the paho thread: it must run in the executor, not on the event loop.
    assert c.loop_stop_thread is not None and c.loop_stop_thread is not loop_thread
