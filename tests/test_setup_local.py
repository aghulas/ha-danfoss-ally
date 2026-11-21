"""Mise en place runtime : repli local + publication MQTT + rechargement (harnais hass).

Couvre les branches de __init__ (local/MQTT), la branche locale de switch.async_setup_entry
(creation of the preheat switch) and its write. Everything is doubled: no network, no tinytuya,
no real broker.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import homeassistant.components.mqtt as mqtt_mod
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.danfoss_ally_cloud as integration
from custom_components.danfoss_ally_cloud.api import GatewayKey
from custom_components.danfoss_ally_cloud.const import (
    CONF_ENABLE_LOCAL,
    CONF_MQTT_MODE,
    DATA_LOCAL,
    DATA_MQTT,
    DOMAIN,
    LOCAL_SETTINGS_INTERVAL,
)

from .common import ENTRY_DATA, FakeCloudClient, head
from .test_coordinator_local import FakeManager, GatedManager, _wait

_GW = {"gw-1": GatewayKey("gw-1", "GW", "cle-synth", ip="10.0.0.1")}


@pytest.fixture
def mqtt_double(monkeypatch):
    publie = AsyncMock()
    monkeypatch.setattr(mqtt_mod, "async_publish", publie)
    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    return publie


async def _setup(
    hass: HomeAssistant, fake: FakeCloudClient, manager: FakeManager, wait_survey: bool = True
):
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
        # The first local survey is a background task: wait for it explicitly.
        await hass.async_block_till_done(wait_background_tasks=wait_survey)
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


async def test_local_and_cloud_mqtt_share_a_single_gateway_key_fetch(
    hass: HomeAssistant, monkeypatch
):
    """When both enable_local and enable_cloud_mqtt are on, gateway keys are fetched once and the
    existing session from the first refresh is reused without a second login."""
    import paho.mqtt.client as paho

    from custom_components.danfoss_ally_cloud.const import CONF_ENABLE_CLOUD_MQTT

    from .test_mqtt_client import _FakePaho

    _FakePaho.instances.clear()
    monkeypatch.setattr(paho, "Client", _FakePaho)
    fake = FakeCloudClient(devices=[head()])
    manager = FakeManager(survey={"dev-1": True})
    fetch_keys = AsyncMock(return_value=_GW)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id="compte@exemple.fr",
        options={CONF_ENABLE_LOCAL: True, CONF_ENABLE_CLOUD_MQTT: True},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake),
        patch("custom_components.danfoss_ally_cloud.async_fetch_gateway_keys", fetch_keys),
        patch("custom_components.danfoss_ally_cloud.LocalTunnelManager", return_value=manager),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert fetch_keys.await_count == 1
    assert getattr(fake, "logged_in", False) is False
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


_PREHEAT_1 = "switch.salon_pre_heating"
_PREHEAT_2 = "switch.bureau_pre_heating"


def _two_heads() -> FakeCloudClient:
    return FakeCloudClient(devices=[head(), head("dev-2", name="Bureau", node_id="node-2")])


async def test_setup_does_not_wait_for_the_local_survey(hass: HomeAssistant, mqtt_double):
    """Regression: setup awaited the first local survey, which reads every head one by one (minutes
    on a large site). With a survey that never ends on its own, the entry must still load, and the
    preheat switches must be UNAVAILABLE (neither on nor off) until their head has been read."""
    manager = GatedManager(survey={"dev-1": True, "dev-2": False})
    async with asyncio.timeout(3):  # the gated survey would hold a blocking setup much longer
        entry = await _setup(hass, _two_heads(), manager, wait_survey=False)
    await _wait(hass, manager.started)

    assert hass.data[DOMAIN][entry.entry_id][DATA_LOCAL] is not None
    assert not manager.finished.is_set()  # loaded while the survey is still running
    assert hass.states.get(_PREHEAT_1).state == "unavailable"
    assert hass.states.get(_PREHEAT_2).state == "unavailable"

    # Each switch becomes available when ITS head is read, without waiting for the others.
    manager.gate("dev-1").set()
    await _wait(hass, manager.was_read("dev-1"))
    assert hass.states.get(_PREHEAT_1).state == "on"
    assert hass.states.get(_PREHEAT_2).state == "unavailable"

    manager.gate("dev-2").set()
    await _wait(hass, manager.finished)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(_PREHEAT_1).state == "on"
    assert hass.states.get(_PREHEAT_2).state == "off"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_unload_during_the_first_survey(hass: HomeAssistant, mqtt_double, caplog):
    """Unloading (or reloading) while the first survey runs: the survey is aborted, no task or
    thread is left behind and nothing is logged as an error."""
    manager = GatedManager()
    entry = await _setup(hass, _two_heads(), manager, wait_survey=False)
    await _wait(hass, manager.started)
    assert not manager.finished.is_set()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await _wait(hass, manager.finished)
    assert manager.aborted is True and manager.calls == 1
    assert hass.states.get(_PREHEAT_1).state == "unavailable"
    assert not [r for r in caplog.records if r.levelname in ("ERROR", "CRITICAL")]


async def test_reload_during_the_first_survey_starts_a_fresh_one(hass: HomeAssistant, mqtt_double):
    first = GatedManager()
    entry = await _setup(hass, _two_heads(), first, wait_survey=False)
    await _wait(hass, first.started)

    second = GatedManager(survey={"dev-1": True, "dev-2": True})
    second.gate("dev-1").set()
    second.gate("dev-2").set()
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=_two_heads()),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value=_GW),
        ),
        patch("custom_components.danfoss_ally_cloud.LocalTunnelManager", return_value=second),
    ):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    await _wait(hass, first.finished)
    assert first.aborted is True  # the old survey did not survive the reload
    assert second.calls == 1 and hass.states.get(_PREHEAT_2).state == "on"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


_WINDOW_1 = "switch.salon_open_window_detection"
_WINDOW_2 = "switch.bureau_open_window_detection"


async def test_isolated_window_switch_follows_the_first_local_read(
    hass: HomeAssistant, mqtt_double
):
    """Regression: the window-detection switch of an isolated head (write path ``local``) only
    listened to the CLOUD coordinator. After the non-blocking start it stayed unavailable after its
    head had been read locally, until the next cloud poll (up to the scan interval). It must follow
    the local coordinator: available as soon as ITS head is read, the other head still waiting."""
    fake = _two_heads()
    cloud_lists: list[int] = []
    list_devices = fake.async_list_devices

    async def counted_list_devices():
        cloud_lists.append(1)
        return await list_devices()

    fake.async_list_devices = counted_list_devices
    manager = GatedManager(survey={"dev-1": True, "dev-2": True})
    entry = await _setup(hass, fake, manager, wait_survey=False)
    await _wait(hass, manager.started)
    cloud_polls = len(cloud_lists)

    assert hass.states.get(_WINDOW_1).state == "unavailable"
    assert hass.states.get(_WINDOW_2).state == "unavailable"

    manager.gate("dev-1").set()
    await _wait(hass, manager.was_read("dev-1"))
    await hass.async_block_till_done()
    state = hass.states.get(_WINDOW_1)
    assert state.state == "on"  # cloud value of the head, now writable through the tunnel
    assert state.attributes["write_path"] == "local"
    assert hass.states.get(_WINDOW_2).state == "unavailable"
    assert len(cloud_lists) == cloud_polls  # no cloud poll was needed

    manager.gate("dev-2").set()
    await _wait(hass, manager.finished)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(_WINDOW_2).state == "on"

    local = hass.data[DOMAIN][entry.entry_id][DATA_LOCAL]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not local._listeners  # the switches' local listeners went with them


async def test_window_switch_state_not_rewritten_by_unrelated_local_reads(
    hass: HomeAssistant, mqtt_double
):
    """A survey publishes every head one by one: a window switch whose availability and write path
    do not change must not have its state rewritten for each of them."""
    manager = GatedManager(survey={"dev-1": True, "dev-2": True})
    entry = await _setup(hass, _two_heads(), manager, wait_survey=False)
    await _wait(hass, manager.started)
    manager.gate("dev-1").set()
    await _wait(hass, manager.was_read("dev-1"))
    await hass.async_block_till_done()
    before = hass.states.get(_WINDOW_1)

    manager.gate("dev-2").set()  # another head read: nothing changes for dev-1's switch
    await _wait(hass, manager.finished)
    await hass.async_block_till_done(wait_background_tasks=True)
    after = hass.states.get(_WINDOW_1)
    assert after.state == "on"
    assert after.last_reported == before.last_reported  # not even re-reported

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


# --- Enum sensors read through the tunnel (docs/zigbee2mqtt-alignment.md, batch B) -------------


async def test_local_enum_sensors_follow_the_survey(hass: HomeAssistant, mqtt_double):
    manager = FakeManager(survey={"dev-1": True})
    manager.setpoint_source = 0
    entry = await _setup(hass, FakeCloudClient(devices=[head()]), manager)

    mode = hass.states.get("sensor.salon_programming_mode")
    assert mode is not None and mode.state == "schedule_with_preheat"
    assert mode.attributes["raw"] == 3
    assert mode.attributes["options"] == ["setpoint", "schedule", "schedule_with_preheat", "eco"]
    source = hass.states.get("sensor.salon_setpoint_change_source")
    assert source is not None and source.state == "manual"

    # A preheat write reads the head back: the mode follows without waiting for the next survey.
    manager._survey["dev-1"] = False
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.salon_pre_heating"}, blocking=True
    )
    assert hass.states.get("sensor.salon_programming_mode").state == "schedule"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_local_enum_sensor_unknown_on_an_unlisted_raw_value(hass: HomeAssistant, mqtt_double):
    manager = FakeManager(survey={"dev-1": False})
    manager.mode_without_preheat = 9
    await _setup(hass, FakeCloudClient(devices=[head()]), manager)
    mode = hass.states.get("sensor.salon_programming_mode")
    assert mode.state == "unknown" and mode.attributes["raw"] == 9


async def test_local_enum_sensors_unavailable_without_an_answer(hass: HomeAssistant, mqtt_double):
    await _setup(hass, FakeCloudClient(devices=[head()]), FakeManager(survey={"dev-1": None}))
    assert hass.states.get("sensor.salon_programming_mode").state == "unavailable"
    assert hass.states.get("sensor.salon_setpoint_change_source").state == "unavailable"


async def test_local_enum_sensors_absent_without_the_local_tunnel(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr")
    entry.add_to_hass(hass)
    fake = FakeCloudClient(devices=[head()])
    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get("sensor.salon_programming_mode") is None


# --- Daily settings pass (docs/zigbee2mqtt-alignment.md, batch B2) -----------------------------

_SETTINGS = {
    "window_state": 3,
    "adaptation_state": 2,
    "radiator_covered": True,
    "heat_available": False,
    "orientation": False,
    "control_speed": 5,
    "setpoint_offset": -15,
    "descale_day": "monday",
    "descale_time": "10:30",
}


async def test_settings_entities_follow_the_daily_pass(hass: HomeAssistant, mqtt_double):
    manager = FakeManager(survey={"dev-1": True})
    manager.settings = {"dev-1": dict(_SETTINGS)}
    await _setup(hass, FakeCloudClient(devices=[head()]), manager)

    window = hass.states.get("sensor.salon_window_state")
    assert window.state == "open" and window.attributes["raw"] == 3
    assert window.attributes["read_at"] is not None
    assert hass.states.get("sensor.salon_adaptation_run").state == "found"
    assert hass.states.get("binary_sensor.salon_radiator_covered").state == "on"
    assert hass.states.get("binary_sensor.salon_heat_available").state == "off"
    # The static settings are disabled by default: registered, without a state.
    registry = er.async_get(hass)
    for name in ("orientation", "regulation_speed", "setpoint_offset"):
        reg = registry.async_get(f"sensor.salon_{name}")
        assert reg is not None and reg.disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(f"sensor.salon_{name}") is None


async def test_settings_pass_runs_once_a_day_and_keeps_the_last_value(
    hass: HomeAssistant, mqtt_double
):
    manager = FakeManager(survey={"dev-1": True})
    manager.settings = {"dev-1": dict(_SETTINGS)}
    entry = await _setup(hass, FakeCloudClient(devices=[head()]), manager)
    local = hass.data[DOMAIN][entry.entry_id][DATA_LOCAL]
    assert manager.settings_surveys == 1

    # The next preheat surveys do not read the settings again.
    await local.async_refresh()
    await hass.async_block_till_done()
    assert manager.settings_surveys == 1

    # A day later the pass runs again; a head that misses it keeps its last value, dated.
    read_at = hass.states.get("sensor.salon_window_state").attributes["read_at"]
    manager.settings = {}
    local._settings_at -= LOCAL_SETTINGS_INTERVAL
    await local.async_refresh()
    await hass.async_block_till_done()
    assert manager.settings_surveys == 2
    window = hass.states.get("sensor.salon_window_state")
    assert window.state == "open" and window.attributes["read_at"] == read_at


async def test_settings_entities_unavailable_until_read_and_retry_after_a_failure(
    hass: HomeAssistant, mqtt_double
):
    manager = FakeManager(survey={"dev-1": True})
    manager.settings_exc = RuntimeError("tunnel busy")
    entry = await _setup(hass, FakeCloudClient(devices=[head()]), manager)
    local = hass.data[DOMAIN][entry.entry_id][DATA_LOCAL]
    # The failed pass did not fail the preheat survey it followed.
    assert hass.states.get("switch.salon_pre_heating").state == "on"
    assert hass.states.get("sensor.salon_window_state").state == "unavailable"
    assert hass.states.get("binary_sensor.salon_radiator_covered").state == "unavailable"

    # It is tried again right after the next survey.
    manager.settings_exc = None
    manager.settings = {"dev-1": dict(_SETTINGS)}
    await local.async_refresh()
    await hass.async_block_till_done()
    assert manager.settings_surveys == 2
    assert hass.states.get("sensor.salon_window_state").state == "open"


def test_local_sensor_values():
    """Scaled, plain and enum values; an unlisted or ill-typed raw value reads unknown."""
    from custom_components.danfoss_ally_cloud.sensor import LOCAL_SENSORS, DanfossLocalSensor

    class _Local:
        attributes: dict = {}
        settings = {
            "h": {**_SETTINGS, "window_state": 9, "control_speed": [5]},
        }

    def value(key):
        desc = next(d for d in LOCAL_SENSORS if d.key == key)
        sensor = DanfossLocalSensor.__new__(DanfossLocalSensor)
        sensor.coordinator = _Local()
        sensor._device_id = "h"
        sensor.entity_description = desc
        sensor._attribute = desc.attribute
        sensor._daily = desc.daily
        return sensor.native_value

    assert value("setpoint_offset") == -1.5
    assert value("descale_day") == "monday" and value("descale_time") == "10:30"
    assert value("orientation") == "horizontal"
    assert value("window_state") is None and value("regulation_speed") is None
