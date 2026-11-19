"""R-3 — post-command refresh: recently commanded heads read via the per-device route.

The bulk ``device.list`` poll lags for minutes after a command; these tests pin the coordinator's
targeted, bounded overlay that keeps a just-commanded head fresh for a short window, then returns it
to the bulk route. Synthetic data only.
"""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant

from custom_components.danfoss_ally_cloud import coordinator as coord_mod
from custom_components.danfoss_ally_cloud.api.client import CloudError
from custom_components.danfoss_ally_cloud.api.decode import decode_device
from custom_components.danfoss_ally_cloud.const import (
    POST_COMMAND_REFRESH_MAX_HEADS,
    POST_COMMAND_REFRESH_TTL,
    POST_COMMAND_SETTLE,
)
from custom_components.danfoss_ally_cloud.coordinator import DanfossCoordinator

from .common import FakeCloudClient


def raw_head(dev_id="h1", name="Salle", dps=None):
    """Raw bulk device (as ``device.list`` returns it) with a full, decodable ``dps`` map."""
    base = {"170": 1, "16": 140, "34": 90, "24": 205}  # valve 1%, setpoint 14.0, batt 90, temp 20.5
    base.update(dps or {})
    return {
        "devId": dev_id,
        "name": name,
        "category": "wk",
        "productId": "03wvrwpv",
        "nodeId": "node-1",
        "meshId": "gw-1",
        "moduleMap": {"zigbee": {"isOnline": True}},
        "dps": base,
    }


def bulk_head(dev_id="h1", name="Salle", dps=None):
    return decode_device(raw_head(dev_id, name, dps))


@pytest.fixture
def clock(monkeypatch):
    """Controllable monotonic clock for the coordinator's TTL logic."""
    t = {"now": 1000.0}
    monkeypatch.setattr(coord_mod.time, "monotonic", lambda: t["now"])
    return t


_CREATED: list[DanfossCoordinator] = []


def _coord(hass, fake, *, enabled=True) -> DanfossCoordinator:
    coord = DanfossCoordinator(hass, fake, 90, post_command_refresh=enabled)
    _CREATED.append(coord)
    return coord


@pytest.fixture(autouse=True)
async def _shutdown_coordinators(hass: HomeAssistant):
    """Shut every coordinator down before HA's lingering-timer check (settle refresh, debouncer)."""
    yield
    while _CREATED:
        await _CREATED.pop().async_shutdown()


async def test_commanded_head_overlaid_from_per_device_route(hass: HomeAssistant, clock):
    # Bulk reports the stale pre-command state; the per-device route has the fresh one.
    fake = FakeCloudClient(
        devices=[bulk_head("h1")],
        device_get_dps={"h1": {"170": 82, "16": 210, "3": "heat"}},
    )
    coord = _coord(hass, fake)
    coord.note_commanded(["h1"])
    clock["now"] += POST_COMMAND_SETTLE  # past the settle delay
    data = await coord._async_update_data()
    assert data["h1"].valve_opening == 82  # DP 170 overlaid
    assert data["h1"].setpoint == 21.0  # DP 16 (tenths) overlaid
    assert data["h1"].state == "heat"  # DP 3 overlaid
    assert data["h1"].battery == 90  # DP 34 absent from fresh -> bulk kept
    assert fake.device_get_calls == ["h1"]


async def test_uncommanded_heads_stay_on_bulk(hass: HomeAssistant, clock):
    fake = FakeCloudClient(
        devices=[bulk_head("h1"), bulk_head("h2", dps={"170": 5})],
        device_get_dps={"h1": {"170": 82}, "h2": {"170": 99}},
    )
    coord = _coord(hass, fake)
    coord.note_commanded(["h1"])  # only h1 commanded
    clock["now"] += POST_COMMAND_SETTLE  # past the settle delay
    data = await coord._async_update_data()
    assert data["h1"].valve_opening == 82  # overlaid
    assert data["h2"].valve_opening == 5  # bulk, untouched
    assert fake.device_get_calls == ["h1"]  # h2 never individually read


async def test_returns_to_bulk_after_ttl(hass: HomeAssistant, clock):
    fake = FakeCloudClient(devices=[bulk_head("h1")], device_get_dps={"h1": {"170": 82}})
    coord = _coord(hass, fake)
    coord.note_commanded(["h1"])
    clock["now"] += POST_COMMAND_SETTLE  # past the settle delay
    await coord._async_update_data()
    assert fake.device_get_calls == ["h1"]
    # Past the window: the head is pruned and read from the bulk route only.
    clock["now"] += POST_COMMAND_REFRESH_TTL + 1
    data = await coord._async_update_data()
    assert fake.device_get_calls == ["h1"]  # no further per-device read
    assert data["h1"].valve_opening == 1  # bulk value
    assert not coord._commanded  # pruned


async def test_bounded_number_of_per_device_reads(hass: HomeAssistant, clock):
    n = POST_COMMAND_REFRESH_MAX_HEADS + 5
    ids = [f"h{i}" for i in range(n)]
    fake = FakeCloudClient(
        devices=[bulk_head(i) for i in ids],
        device_get_dps={i: {"170": 50} for i in ids},
    )
    coord = _coord(hass, fake)
    coord.note_commanded(ids)
    clock["now"] += POST_COMMAND_SETTLE  # past the settle delay
    await coord._async_update_data()
    # One poll never issues more than the cap of per-device reads.
    assert len(fake.device_get_calls) == POST_COMMAND_REFRESH_MAX_HEADS


async def test_disabled_option_never_reads_per_device(hass: HomeAssistant, clock):
    fake = FakeCloudClient(devices=[bulk_head("h1")], device_get_dps={"h1": {"170": 82}})
    coord = _coord(hass, fake, enabled=False)
    coord.note_commanded(["h1"])  # no-op when disabled
    clock["now"] += POST_COMMAND_SETTLE  # past the settle delay
    data = await coord._async_update_data()
    assert fake.device_get_calls == []
    assert data["h1"].valve_opening == 1  # bulk only
    assert not coord._commanded


async def test_per_device_failure_keeps_bulk(hass: HomeAssistant, clock):
    class _Boom(FakeCloudClient):
        async def async_get_device_dps(self, dev_id):
            self.device_get_calls.append(dev_id)
            raise CloudError("boom")

    fake = _Boom(devices=[bulk_head("h1", dps={"170": 7})])
    coord = _coord(hass, fake)
    coord.note_commanded(["h1"])
    clock["now"] += POST_COMMAND_SETTLE  # past the settle delay
    data = await coord._async_update_data()  # must not raise
    assert fake.device_get_calls == ["h1"]
    assert data["h1"].valve_opening == 7  # bulk kept


async def test_empty_per_device_response_keeps_bulk(hass: HomeAssistant, clock):
    # Route carries no DPs (None): degrade to the bulk value, head stays hot for a later retry.
    fake = FakeCloudClient(devices=[bulk_head("h1", dps={"170": 7})], device_get_dps={"h1": None})
    coord = _coord(hass, fake)
    coord.note_commanded(["h1"])
    clock["now"] += POST_COMMAND_SETTLE  # past the settle delay
    data = await coord._async_update_data()
    assert data["h1"].valve_opening == 7
    assert "h1" in coord._commanded  # still within the window


async def test_overlay_preserves_identity_and_topology(hass: HomeAssistant, clock):
    fake = FakeCloudClient(
        devices=[bulk_head("h1", name="Room A")],
        device_get_dps={"h1": {"170": 82}},
    )
    coord = _coord(hass, fake)
    coord.note_commanded(["h1"])
    clock["now"] += POST_COMMAND_SETTLE  # past the settle delay
    data = await coord._async_update_data()
    dev = data["h1"]
    assert dev.id == "h1" and dev.name == "Room A"
    assert dev.category == "head" and dev.node_id == "node-1" and dev.mesh_id == "gw-1"
    assert dev.online is True


async def test_no_overlay_during_settle_delay(hass: HomeAssistant, clock):
    # rc1 finding: a per-device read right after the write returned the PRE-command state, leaving
    # the written entity one write behind. During the settle delay the bulk value is kept.
    fake = FakeCloudClient(devices=[bulk_head("h1")], device_get_dps={"h1": {"170": 82}})
    coord = _coord(hass, fake)
    coord.note_commanded(["h1"])
    data = await coord._async_update_data()  # the write's own immediate refresh
    assert fake.device_get_calls == []
    assert data["h1"].valve_opening == 1  # bulk kept, no stale per-device read
    clock["now"] += POST_COMMAND_SETTLE
    data = await coord._async_update_data()  # the settle refresh
    assert fake.device_get_calls == ["h1"]
    assert data["h1"].valve_opening == 82
    await coord.async_shutdown()


async def test_settle_refresh_scheduled_rearmed_and_cancelled(hass: HomeAssistant, clock):
    fake = FakeCloudClient(devices=[bulk_head("h1")], device_get_dps={"h1": {"170": 82}})
    coord = _coord(hass, fake)
    assert coord._settle_unsub is None
    coord.note_commanded(["h1"])
    first = coord._settle_unsub
    assert first is not None  # one refresh scheduled at the end of the settle delay
    coord.note_commanded(["h1"])  # a new command re-arms it (single pending refresh)
    assert coord._settle_unsub is not None and coord._settle_unsub is not first
    await coord.async_shutdown()
    assert coord._settle_unsub is None  # cancelled on shutdown


async def test_settle_refresh_fires_a_refresh(hass: HomeAssistant, clock):
    from datetime import timedelta
    from unittest.mock import AsyncMock

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    fake = FakeCloudClient(devices=[bulk_head("h1")], device_get_dps={"h1": {"170": 82}})
    coord = _coord(hass, fake)
    coord.async_request_refresh = AsyncMock()
    coord.note_commanded(["h1"])
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=POST_COMMAND_SETTLE + 1))
    await hass.async_block_till_done()
    coord.async_request_refresh.assert_awaited_once()
    assert coord._settle_unsub is None


async def test_disabled_option_schedules_nothing(hass: HomeAssistant, clock):
    fake = FakeCloudClient(devices=[bulk_head("h1")])
    coord = _coord(hass, fake, enabled=False)
    coord.note_commanded(["h1"])
    assert coord._settle_unsub is None
