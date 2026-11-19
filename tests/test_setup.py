"""Runtime integration tests: setup / unload and coordinator (hass harness)."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud import (
    _cleanup_orphaned_head_climates,
    _migrate_unique_id,
)
from custom_components.danfoss_ally_cloud.api.client import CloudAuthError, CloudError
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR, DOMAIN
from custom_components.danfoss_ally_cloud.coordinator import DanfossCoordinator

from .common import ENTRY_DATA, FakeCloudClient, head

_PIECE = [{"group_id": 77, "name": "Salle", "pid": "03wvrwpv", "head_count": 2}]


async def test_setup_and_unload(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr")
    entry.add_to_hass(hass)
    fake = FakeCloudClient(devices=[head()])
    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanfossCoordinator = data[DATA_COORDINATOR]
    assert "dev-1" in coordinator.data
    # The platforms created entities (main climate + sensors/binary sensors).
    assert hass.states.get("climate.salon") is not None
    assert hass.states.get("sensor.salon_battery") is not None
    assert hass.states.get("binary_sensor.salon_online") is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert fake.closed is True
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_coordinator_maps_the_devices(hass: HomeAssistant):
    fake = FakeCloudClient(devices=[head("a", "A"), head("b", "B")])
    coordinator = DanfossCoordinator(hass, fake, 90)
    data = await coordinator._async_update_data()
    assert set(data) == {"a", "b"}
    assert data["a"].name == "A"


async def test_coordinator_auth_error(hass: HomeAssistant):
    fake = FakeCloudClient(list_exc=CloudAuthError("refus"))
    coordinator = DanfossCoordinator(hass, fake, 90)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_coordinator_cloud_error(hass: HomeAssistant):
    fake = FakeCloudClient(list_exc=CloudError("cloud ko"))
    coordinator = DanfossCoordinator(hass, fake, 90)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_coordinator_builds_the_rooms(hass: HomeAssistant):
    fake = FakeCloudClient(
        devices=[head("a", "A", temperature=18.0), head("b", "B", temperature=20.0)],
        groups=_PIECE,
        members={"77": ["a", "b"]},
    )
    coordinator = DanfossCoordinator(hass, fake, 90)
    data = await coordinator._async_update_data()
    assert set(data) == {"a", "b"}
    assert "77" in coordinator.rooms
    assert coordinator.rooms["77"].temperature == 19.0  # moyenne
    assert coordinator.grouped_ids == {"a", "b"}
    assert coordinator.group_of("a") == "77"


async def test_coordinator_topologie_degrade_en_isole(hass: HomeAssistant):
    # Topology read failed and no cache: heads treated as isolated (no room).
    fake = FakeCloudClient(devices=[head("a", "A")], topology_exc=CloudError("topo ko"))
    coordinator = DanfossCoordinator(hass, fake, 90)
    data = await coordinator._async_update_data()
    assert set(data) == {"a"}
    assert coordinator.rooms == {}
    assert coordinator.grouped_ids == set()
    assert coordinator.group_of("a") is None


async def test_cleanup_removes_old_per_head_climate(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr")
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    # Old model: one climate per head. "a" is now grouped, "c" stays isolated.
    groupee = registry.async_get_or_create("climate", DOMAIN, "a", config_entry=entry)
    isolee = registry.async_get_or_create("climate", DOMAIN, "c", config_entry=entry)
    coord = SimpleNamespace(grouped_ids={"a"})

    _cleanup_orphaned_head_climates(hass, entry, coord)

    assert registry.async_get(groupee.entity_id) is None  # grouped head: old climate removed
    assert registry.async_get(isolee.entity_id) is not None  # isolated head: climate kept


def test_migrate_unique_id_renames_french_slugs():
    """The unique_id migration maps every old French slug to its English equivalent."""
    cases = {
        "dev-1_en_ligne": "dev-1_online",
        "dev-1_fenetre": "dev-1_window",
        "dev-1_batterie": "dev-1_battery",
        "dev-1_ouverture_vanne": "dev-1_valve_opening",
        "dev-1_defaut": "dev-1_fault",
        "dev-1_verrou_enfant": "dev-1_child_lock",
        "dev-1_detection_fenetre": "dev-1_window_detection",
        "dev-1_pre_chauffage": "dev-1_preheat",
        "77_consigne_confort": "77_comfort_setpoint",
        "77_consigne_reduit": "77_setback_setpoint",
    }
    for old, new in cases.items():
        assert _migrate_unique_id(SimpleNamespace(unique_id=old)) == {"new_unique_id": new}


def test_migrate_unique_id_leaves_others_untouched():
    """Already-English or unrelated unique_ids are not migrated (idempotent)."""
    for uid in ("dev-1_temperature", "dev-1_window_detection", "13000000", "dev-1_online"):
        assert _migrate_unique_id(SimpleNamespace(unique_id=uid)) is None


async def test_setup_links_grouped_heads_to_their_room_device(hass: HomeAssistant):
    # End to end: after setup, a grouped head's device is a sub-device of its room device
    # (via_device_id on the registry), with no deprecated DeviceInfo.via_device involved.
    from homeassistant.helpers import device_registry as dr

    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr")
    entry.add_to_hass(hass)
    fake = FakeCloudClient(
        devices=[head("a", "A"), head("b", "B"), head("c", "C")],
        groups=_PIECE,
        members={"77": ["a", "b"]},
    )
    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    from custom_components.danfoss_ally_cloud.device_links import _find

    reg = dr.async_get(hass)
    room = _find(reg, entry.entry_id, "group_77")
    assert room is not None
    for head_id in ("a", "b"):
        dev = _find(reg, entry.entry_id, head_id)
        assert dev is not None and dev.via_device_id == room.id
    isolated = _find(reg, entry.entry_id, "c")
    assert isolated is not None and isolated.via_device_id is None

    assert await hass.config_entries.async_unload(entry.entry_id)
