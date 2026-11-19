"""Axis B — holiday read: decode helper + home-level entities. Synthetic data only."""

from types import SimpleNamespace
from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.danfoss_ally_cloud import binary_sensor, sensor
from custom_components.danfoss_ally_cloud.api.client import CloudError
from custom_components.danfoss_ally_cloud.api.decode import holiday_running, holiday_temperature
from custom_components.danfoss_ally_cloud.binary_sensor import DanfossHoliday
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR, DOMAIN
from custom_components.danfoss_ally_cloud.coordinator import DanfossCoordinator
from custom_components.danfoss_ally_cloud.sensor import DanfossHolidaySetpoint

from .common import FakeCloudClient, head


def test_holiday_temperature_scales_and_misses():
    assert holiday_temperature({"temp": 150}) == 15.0  # tenths of °C
    assert holiday_temperature({"temperature": 7.0}) == 7.0  # already °C (< 50)
    assert holiday_temperature({"holidayTemp": 205}) == 20.5
    assert holiday_temperature({"other": 1}) is None  # no recognised field
    assert holiday_temperature(None) is None
    assert holiday_temperature({"temp": "abc"}) is None


class _FakeCoord:
    def __init__(self, holidays):
        self.holidays = holidays
        self.data = {}
        self.last_update_success = True

    def async_add_listener(self, *_a, **_k):
        return lambda: None


def _coord(active=True, detail=None, name="Maison", scheduled=None):
    if scheduled is None and active is not None:
        scheduled = bool(detail) and not active
    return _FakeCoord(
        {
            "77": {
                "gid": "77",
                "name": name,
                "active": active,
                "scheduled": scheduled,
                "detail": detail,
            }
        }
    )


def test_holiday_running_reads_is_running():
    assert holiday_running({"isRunning": True}) is True
    assert holiday_running({"isRunning": False, "startDate": "20261205"}) is False
    assert holiday_running({"isRunning": "false"}) is False
    assert holiday_running({}) is False  # no holiday on record
    assert holiday_running(None) is False
    assert holiday_running({"startDate": "20261205"}) is None  # flag missing: unknown


async def test_binary_sensor_setup_adds_one_holiday_per_home():
    coord = _coord()
    hass = SimpleNamespace(data={DOMAIN: {"e1": {DATA_COORDINATOR: coord}}})
    added: list = []
    await binary_sensor.async_setup_entry(
        hass, SimpleNamespace(entry_id="e1"), lambda ents: added.extend(ents)
    )
    holidays = [e for e in added if isinstance(e, DanfossHoliday)]
    assert len(holidays) == 1
    assert holidays[0].unique_id == "home_77_holiday"


def test_holiday_is_on_and_attributes():
    detail = {"end": "2026-12-31", "isRunning": True}
    ent = DanfossHoliday(_coord(active=True, detail=detail), "77", "Maison")
    assert ent.is_on is True
    assert ent.extra_state_attributes == {"scheduled": False, "detail": detail}
    # device groups under a per-home device
    assert (DOMAIN, "home_77") in ent.device_info["identifiers"]


def test_holiday_off_no_detail():
    ent = DanfossHoliday(_coord(active=False), "77", "Maison")
    assert ent.is_on is False
    assert ent.extra_state_attributes == {"scheduled": False}


def test_planned_holiday_is_off_and_scheduled():
    # Regression (real hardware 2026-11-19): a holiday planned two weeks ahead came back in
    # vacation.detail with isRunning false and the sensor read "on".
    detail = {"startDate": "20261205", "isRunning": False, "vacationType": 3, "temperature": 145}
    ent = DanfossHoliday(_coord(active=False, detail=detail), "77", "Maison")
    assert ent.is_on is False
    assert ent.extra_state_attributes == {"scheduled": True, "detail": detail}


def test_holiday_unknown_running_flag_is_unknown():
    ent = DanfossHoliday(_coord(active=None, detail={"startDate": "x"}), "77", "Maison")
    assert ent.is_on is None


def test_holiday_unknown_home_is_none():
    ent = DanfossHoliday(_FakeCoord({}), "99", "Maison")
    assert ent.is_on is None


async def test_sensor_setup_adds_holiday_setpoint():
    coord = _coord(active=True, detail={"temp": 160})
    hass = SimpleNamespace(data={DOMAIN: {"e1": {DATA_COORDINATOR: coord}}})
    added: list = []
    await sensor.async_setup_entry(
        hass, SimpleNamespace(entry_id="e1"), lambda ents: added.extend(ents)
    )
    sp = [e for e in added if isinstance(e, DanfossHolidaySetpoint)]
    assert len(sp) == 1 and sp[0].native_value == 16.0


def test_holiday_setpoint_follows_record_running_or_planned():
    # a planned holiday's setpoint is shown (the binary_sensor says it is not running yet)
    ent = DanfossHolidaySetpoint(_coord(active=False, detail={"temp": 160}), "77", "Maison")
    assert ent.native_value == 16.0


def test_holiday_setpoint_none_without_record():
    ent = DanfossHolidaySetpoint(_coord(active=False, detail=None), "77", "Maison")
    assert ent.native_value is None


async def test_coordinator_populates_holidays(hass: HomeAssistant):
    hol = [{"gid": "1", "name": "Maison", "active": True, "detail": {"temp": 150}}]
    coord = DanfossCoordinator(hass, FakeCloudClient(holidays=hol), 90)
    await coord._async_update_data()
    assert coord.holidays["1"]["active"] is True


async def test_coordinator_keeps_holidays_on_read_failure(hass: HomeAssistant):
    coord = DanfossCoordinator(hass, FakeCloudClient(holidays_exc=CloudError("boom")), 90)
    coord.holidays = {"1": {"gid": "1", "active": True}}  # a previous value
    await coord._async_update_data()
    # a holiday read failure must not wipe the previous value nor break the poll
    assert coord.holidays == {"1": {"gid": "1", "active": True}}


async def test_invalidate_topology_forces_room_refetch(hass: HomeAssistant):
    # A structural write cache-busts the topology; without it the hourly cache hides the change.
    # monotonic() is pinned to a small value < TTL to model a freshly booted host (as on CI): then
    # invalidate_topology must STILL force the refetch, which it only does if it doesn't rely on
    # `now - 0 >= TTL` (it uses -inf). Without that fix this test fails here (and did, in CI).
    fake = FakeCloudClient(
        devices=[head("a", "A")],
        groups=[{"group_id": "g1", "name": "R1", "pid": "03wvrwpv", "head_count": 1}],
        members={"g1": ["a"]},
    )
    with patch("custom_components.danfoss_ally_cloud.coordinator.time.monotonic", return_value=5.0):
        coord = DanfossCoordinator(hass, fake, 90)
        await coord._async_update_data()
        assert "g1" in coord.rooms

        # the cloud topology changes (room g1 -> g2)
        fake._groups = [{"group_id": "g2", "name": "R2", "pid": "03wvrwpv", "head_count": 1}]
        fake._members = {"g2": ["a"]}

        # a plain refresh keeps the cached topology (the bug behind create_room invisibility)
        await coord._async_update_data()
        assert "g1" in coord.rooms and "g2" not in coord.rooms

        # invalidating the topology makes the next refresh re-read it, even on a low-uptime host
        coord.invalidate_topology()
        await coord._async_update_data()
        assert "g2" in coord.rooms and "g1" not in coord.rooms
