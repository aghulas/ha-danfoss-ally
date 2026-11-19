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


def _find_device(hass, entry, key):
    """Device of this entry by identifier value (works on every supported HA line)."""
    for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id):
        if (DOMAIN, key) in device.identifiers:
            return device
    return None


def _entity(hass, entry, domain, unique_id, device=None):
    return er.async_get(hass).async_get_or_create(
        domain,
        DOMAIN,
        unique_id,
        config_entry=entry,
        device_id=device.id if device else None,
    )


def _remember(hass_storage, entry, homes):
    """Seed the record of a previous COMPLETE device list: {home gid: device count}."""
    key = f"{DOMAIN}.{entry.entry_id}.homes"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": {"homes": homes}}


def _recorded(hass_storage, entry):
    return hass_storage.get(f"{DOMAIN}.{entry.entry_id}.homes", {}).get("data", {}).get("homes")


async def test_device_of_a_head_gone_from_the_account_is_removed_with_its_entities(
    hass: HomeAssistant, hass_storage
):
    entry = _entry(hass)
    _remember(hass_storage, entry, {"1": 1})  # the previous start saw the same picture
    gone = _device(hass, entry, "dev-gone", "Old head")
    orphan_switch = _entity(hass, entry, "switch", "dev-gone_preheat", gone)
    orphan_sensor = _entity(hass, entry, "sensor", "dev-gone_battery", gone)

    await _setup(hass, entry, FakeCloudClient(devices=[head()]))

    assert dr.async_get(hass).async_get(gone.id) is None
    reg = er.async_get(hass)
    assert reg.async_get(orphan_switch.entity_id) is None
    assert reg.async_get(orphan_sensor.entity_id) is None
    # The head that is still in the account keeps its device and entities.
    assert _find_device(hass, entry, "dev-1") is not None
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
    live_head = _find_device(hass, entry, "h1")
    live_room = _find_device(hass, entry, "group_77")
    assert live_head is not None and live_room is not None
    old_room = _device(hass, entry, "group_99", "Dissolved room")
    assert await async_remove_config_entry_device(hass, entry, live_head) is False
    assert await async_remove_config_entry_device(hass, entry, live_room) is False
    assert await async_remove_config_entry_device(hass, entry, old_room) is True
    # Entry not loaded: refuse rather than guess.
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await async_remove_config_entry_device(hass, entry, old_room) is False


# --- guard-rails: never remove on a list that is not confirmed complete, never in bulk -----------


def _stale_devices(hass, entry, count, prefix="gone"):
    return [_device(hass, entry, f"{prefix}-{i}", f"Old head {i}") for i in range(count)]


def _remaining(hass, devices):
    reg = dr.async_get(hass)
    return [d for d in devices if reg.async_get(d.id) is not None]


async def test_first_start_removes_nothing_then_the_next_confirmed_start_does(
    hass: HomeAssistant, hass_storage
):
    """No earlier complete list on record: the absence cannot be confirmed, so nothing is removed;
    the list is recorded, and the next start that shows the same picture removes."""
    entry = _entry(hass)
    gone = _stale_devices(hass, entry, 1)
    fake = FakeCloudClient(devices=[head()])
    await _setup(hass, entry, fake)
    assert _remaining(hass, gone) == gone
    assert _recorded(hass_storage, entry) == {"1": 1}

    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert _remaining(hass, gone) == []


async def test_incomplete_device_list_removes_nothing_and_keeps_the_record(
    hass: HomeAssistant, hass_storage
):
    """A home answered with something that is not a list: the client flags the list incomplete."""
    entry = _entry(hass)
    _remember(hass_storage, entry, {"1": 1, "2": 2})
    gone = _stale_devices(hass, entry, 2)
    fake = FakeCloudClient(devices=[head()])
    fake.device_list_complete = False
    fake.list_homes = {"1": 1}  # home 2 did not answer with a list
    await _setup(hass, entry, fake)
    assert _remaining(hass, gone) == gone
    assert _recorded(hass_storage, entry) == {"1": 1, "2": 2}  # an incomplete list is not recorded


async def test_home_answering_empty_removes_nothing_until_confirmed(
    hass: HomeAssistant, hass_storage
):
    """A home that held devices now answers an EMPTY list: indistinguishable from a degraded
    answer on one read, so nothing is removed. Only a later start confirming it may remove."""
    entry = _entry(hass)
    _remember(hass_storage, entry, {"1": 1, "2": 2})
    gone = _stale_devices(hass, entry, 2)
    fake = FakeCloudClient(devices=[head()])
    fake.list_homes = {"1": 1, "2": 0}
    await _setup(hass, entry, fake)
    assert _remaining(hass, gone) == gone
    assert _recorded(hass_storage, entry) == {"1": 1, "2": 0}

    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert _remaining(hass, gone) == []  # confirmed by a second, identical complete list


async def test_home_missing_from_the_homes_list_removes_nothing(hass: HomeAssistant, hass_storage):
    entry = _entry(hass)
    _remember(hass_storage, entry, {"1": 1, "2": 2})
    gone = _stale_devices(hass, entry, 2)
    fake = FakeCloudClient(devices=[head()])  # reports home "1" only, as a complete list
    await _setup(hass, entry, fake)
    assert _remaining(hass, gone) == gone


async def test_client_without_a_completeness_indicator_removes_nothing(
    hass: HomeAssistant, hass_storage
):
    entry = _entry(hass)
    _remember(hass_storage, entry, {"1": 2})
    gone = _stale_devices(hass, entry, 1)
    fake = FakeCloudClient(devices=[head()])
    fake.device_list_complete = False
    await _setup(hass, entry, fake)
    assert _remaining(hass, gone) == gone


async def test_too_many_absent_devices_removes_nothing_and_warns_without_identifiers(
    hass: HomeAssistant, hass_storage, caplog
):
    """4 of 5 devices absent on a confirmed list: over the limit (3, or 5 % if more), so nothing is
    removed. The warning carries counts only."""
    entry = _entry(hass)
    _remember(hass_storage, entry, {"1": 1})  # same picture as now: only the limit protects
    _device(hass, entry, "dev-1", "Salon")  # the live head, registered by an earlier run
    gone = _stale_devices(hass, entry, 4, prefix="secretid")
    await _setup(hass, entry, FakeCloudClient(devices=[head()]))
    assert _remaining(hass, gone) == gone
    warning = next(r.getMessage() for r in caplog.records if "too many" in r.getMessage())
    assert "4 of 5" in warning and "limit 3" in warning
    assert "secretid" not in caplog.text and "Old head" not in caplog.text


async def test_absent_devices_at_the_limit_are_removed(hass: HomeAssistant, hass_storage):
    entry = _entry(hass)
    _remember(hass_storage, entry, {"1": 1})
    gone = _stale_devices(hass, entry, 3)
    await _setup(hass, entry, FakeCloudClient(devices=[head()]))
    assert _remaining(hass, gone) == []


async def test_limit_follows_the_share_on_a_large_install(hass: HomeAssistant, hass_storage):
    """100 devices: the 5 % share (5) is the limit. 6 absent are kept, 5 would be removed."""
    live = [head(f"h{i}", f"Head {i}") for i in range(94)]
    entry = _entry(hass)
    _remember(hass_storage, entry, {"1": 94})
    for dev in live:  # registered by earlier runs, as on a real install
        _device(hass, entry, dev.id, dev.name)
    gone = _stale_devices(hass, entry, 6)
    await _setup(hass, entry, FakeCloudClient(devices=live))
    assert _remaining(hass, gone) == gone  # 6 of 100 > 5

    entry2 = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="autre@exemple.fr")
    entry2.add_to_hass(hass)
    _remember(hass_storage, entry2, {"1": 95})
    live2 = [head(f"k{i}", f"Other {i}") for i in range(95)]
    for dev in live2:
        _device(hass, entry2, dev.id, dev.name)
    gone2 = _stale_devices(hass, entry2, 5, prefix="gone2")
    await _setup(hass, entry2, FakeCloudClient(devices=live2))
    assert _remaining(hass, gone2) == []  # 5 of 100 = the limit


async def test_record_of_known_homes_is_dropped_with_the_entry(hass: HomeAssistant, hass_storage):
    entry = _entry(hass)
    await _setup(hass, entry, FakeCloudClient(devices=[head()]))
    assert _recorded(hass_storage, entry) == {"1": 1}
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _recorded(hass_storage, entry) is None


async def test_truncated_list_within_the_limit_removes_nothing_at_that_start(
    hass: HomeAssistant, hass_storage
):
    """A home answers a complete-looking but SHORTER list (3 devices before, 1 now). The absence
    fits the limit, yet one read cannot tell a truncated answer from devices that left: nothing
    is removed at this start. If the next start shows the same picture, they are removed."""
    entry = _entry(hass)
    _remember(hass_storage, entry, {"1": 3})
    _device(hass, entry, "dev-1", "Salon")
    missing = _stale_devices(hass, entry, 2)
    fake = FakeCloudClient(devices=[head()])  # complete flag true, 1 device instead of 3
    await _setup(hass, entry, fake)
    assert _remaining(hass, missing) == missing
    assert _recorded(hass_storage, entry) == {"1": 1}  # the new picture is recorded

    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert _remaining(hass, missing) == []  # confirmed over two starts


async def test_truncated_list_that_recovers_never_removes_anything(
    hass: HomeAssistant, hass_storage
):
    """The short answer was a glitch: the next start sees the full list again. The picture
    differs from the recorded short one, so that start does not remove either, and the devices
    are all present anyway."""
    entry = _entry(hass)
    _remember(hass_storage, entry, {"1": 3})
    heads = [head("dev-1", "Salon"), head("dev-2", "Deux"), head("dev-3", "Trois")]
    devices = [_device(hass, entry, h.id, h.name) for h in heads]
    await _setup(hass, entry, FakeCloudClient(devices=heads[:1]))  # truncated
    assert _remaining(hass, devices) == devices

    with patch(
        "custom_components.danfoss_ally_cloud.CloudClient",
        return_value=FakeCloudClient(devices=heads),
    ):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert _remaining(hass, devices) == devices
    assert _recorded(hass_storage, entry) == {"1": 3}


async def test_a_new_device_delays_the_cleanup_by_one_start(hass: HomeAssistant, hass_storage):
    """Any change of the picture, even a count going UP, postpones removals to the next start."""
    entry = _entry(hass)
    _remember(hass_storage, entry, {"1": 1})
    gone = _stale_devices(hass, entry, 1)
    fake = FakeCloudClient(devices=[head("dev-1", "Salon"), head("dev-2", "New")])
    await _setup(hass, entry, fake)
    assert _remaining(hass, gone) == gone
    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert _remaining(hass, gone) == []
