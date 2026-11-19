"""Stale devices and entities are removed at setup instead of lingering as restored orphans.

hass harness, fake cloud client, synthetic data.
"""

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud import async_remove_config_entry_device
from custom_components.danfoss_ally_cloud.api import GatewayKey
from custom_components.danfoss_ally_cloud.const import (
    CONF_ENABLE_CLOUD_MQTT,
    CONF_ENABLE_LOCAL,
    DOMAIN,
)

from .common import ENTRY_DATA, FakeCloudClient, head
from .test_coordinator_local import FakeManager

_ROOM = [{"group_id": 77, "name": "Salle", "pid": "03wvrwpv", "head_count": 2}]
_GW = {"gw-1": GatewayKey("gw-1", "GW", "cle-synth", ip="10.0.0.1")}


def _entry(hass, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr", options=options or {}
    )
    entry.add_to_hass(hass)
    return entry


async def _setup(hass, entry, fake):
    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _device(hass, entry, key, name):
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, key)}, name=name
    )


def _entity(hass, entry, domain, unique_id, device=None):
    return er.async_get(hass).async_get_or_create(
        domain,
        DOMAIN,
        unique_id,
        config_entry=entry,
        device_id=device.id if device else None,
    )


async def test_device_of_a_head_gone_from_the_account_is_removed_with_its_entities(
    hass: HomeAssistant,
):
    entry = _entry(hass)
    gone = _device(hass, entry, "dev-gone", "Old head")
    orphan_switch = _entity(hass, entry, "switch", "dev-gone_preheat", gone)
    orphan_sensor = _entity(hass, entry, "sensor", "dev-gone_battery", gone)

    await _setup(hass, entry, FakeCloudClient(devices=[head()]))

    assert dr.async_get(hass).async_get(gone.id) is None
    reg = er.async_get(hass)
    assert reg.async_get(orphan_switch.entity_id) is None
    assert reg.async_get(orphan_sensor.entity_id) is None
    # The head that is still in the account keeps its device and entities.
    assert dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "dev-1")}) is not None
    assert hass.states.get("sensor.salon_battery") is not None


async def test_room_and_home_devices_are_never_removed_automatically(hass: HomeAssistant):
    """Their presence depends on best-effort reads: a failed topology read at start-up must not
    cost the user their room devices."""
    from custom_components.danfoss_ally_cloud.api.client import CloudError

    entry = _entry(hass)
    room = _device(hass, entry, "group_77", "Salle")
    home = _device(hass, entry, "home_1", "Maison")
    room_number = _entity(hass, entry, "number", "77_comfort_setpoint", room)

    await _setup(hass, entry, FakeCloudClient(devices=[head()], topology_exc=CloudError("x")))

    assert dr.async_get(hass).async_get(room.id) is not None
    assert dr.async_get(hass).async_get(home.id) is not None
    assert er.async_get(hass).async_get(room_number.entity_id) is not None


async def test_preheat_switches_removed_when_the_local_tunnel_option_is_off(hass: HomeAssistant):
    entry = _entry(hass)  # enable_local off
    dev = _device(hass, entry, "dev-1", "Salon")
    preheat = _entity(hass, entry, "switch", "dev-1_preheat", dev)
    lock = _entity(hass, entry, "switch", "dev-1_child_lock", dev)

    await _setup(hass, entry, FakeCloudClient(devices=[head()]))

    reg = er.async_get(hass)
    assert reg.async_get(preheat.entity_id) is None
    assert reg.async_get(lock.entity_id) is not None  # other switches untouched
    assert dr.async_get(hass).async_get(dev.id) is not None


async def test_preheat_switches_kept_when_the_tunnel_is_enabled_but_failed_to_start(
    hass: HomeAssistant,
):
    entry = _entry(hass, {CONF_ENABLE_LOCAL: True})
    dev = _device(hass, entry, "dev-1", "Salon")
    preheat = _entity(hass, entry, "switch", "dev-1_preheat", dev)
    with patch(
        "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
        AsyncMock(side_effect=RuntimeError("synthetic key fetch failure")),
    ):
        await _setup(hass, entry, FakeCloudClient(devices=[head()]))
    assert er.async_get(hass).async_get(preheat.entity_id) is not None  # transient: kept


async def test_preheat_switch_kept_and_provided_when_the_tunnel_runs(hass: HomeAssistant):
    entry = _entry(hass, {CONF_ENABLE_LOCAL: True})
    dev = _device(hass, entry, "dev-1", "Salon")
    preheat = _entity(hass, entry, "switch", "dev-1_preheat", dev)
    with (
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value=_GW),
        ),
        patch(
            "custom_components.danfoss_ally_cloud.LocalTunnelManager",
            return_value=FakeManager({"dev-1": True}),
        ),
    ):
        await _setup(hass, entry, FakeCloudClient(devices=[head()]))
    assert er.async_get(hass).async_get(preheat.entity_id) is not None
    assert hass.states.get(preheat.entity_id).state == "on"


async def test_link_sensor_removed_when_the_cloud_mqtt_option_is_off(hass: HomeAssistant):
    entry = _entry(hass)
    link = _entity(hass, entry, "binary_sensor", f"{entry.entry_id}_cloud_mqtt_link")
    await _setup(hass, entry, FakeCloudClient(devices=[head()]))
    assert er.async_get(hass).async_get(link.entity_id) is None


async def test_link_sensor_kept_when_the_cloud_mqtt_option_is_on(hass: HomeAssistant):
    entry = _entry(hass, {CONF_ENABLE_CLOUD_MQTT: True})
    link = _entity(hass, entry, "binary_sensor", f"{entry.entry_id}_cloud_mqtt_link")
    # The link itself fails to start here (no gateway key): the sensor entry is kept anyway.
    with patch(
        "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
        AsyncMock(return_value={}),
    ):
        await _setup(hass, entry, FakeCloudClient(devices=[head()]))
    assert er.async_get(hass).async_get(link.entity_id) is not None


async def test_nothing_removed_on_a_clean_install(hass: HomeAssistant):
    entry = _entry(hass)
    fake = FakeCloudClient(
        devices=[head("h1", "Une"), head("h2", "Deux")],
        groups=_ROOM,
        members={"77": ["h1", "h2"]},
    )
    await _setup(hass, entry, fake)
    before = {
        e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    devices_before = {
        d.id for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    }
    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    after = {
        e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    devices_after = {
        d.id for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    }
    assert before == after and before
    assert devices_before == devices_after and devices_before


async def test_user_can_delete_only_a_device_that_is_no_longer_provided(hass: HomeAssistant):
    entry = _entry(hass)
    fake = FakeCloudClient(
        devices=[head("h1", "Une"), head("h2", "Deux")],
        groups=_ROOM,
        members={"77": ["h1", "h2"]},
    )
    await _setup(hass, entry, fake)
    reg = dr.async_get(hass)
    live_head = reg.async_get_device(identifiers={(DOMAIN, "h1")})
    live_room = reg.async_get_device(identifiers={(DOMAIN, "group_77")})
    old_room = _device(hass, entry, "group_99", "Dissolved room")
    assert await async_remove_config_entry_device(hass, entry, live_head) is False
    assert await async_remove_config_entry_device(hass, entry, live_room) is False
    assert await async_remove_config_entry_device(hass, entry, old_room) is True
    # Entry not loaded: refuse rather than guess.
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await async_remove_config_entry_device(hass, entry, old_room) is False
