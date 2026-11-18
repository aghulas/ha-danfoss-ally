"""Vacation (holiday) writes — CIBLE 2, GATED. Synthetic data only; no real heating write.

Covers the captured request bodies at the client level and the gated/validated operations at the
service level. The gate (`enable_vacation_write`) is OFF by default: writes refuse until enabled.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud.api.client import CloudClient
from custom_components.danfoss_ally_cloud.const import CONF_ENABLE_VACATION_WRITE, DOMAIN

from .common import ENTRY_DATA, FakeCloudClient, head
from .test_client_async import FakeHttp

_HTTP = "custom_components.danfoss_ally_cloud.api.client.TuyaHttpClient"
_GROUPS = [{"group_id": "13000000", "name": "Salle 1", "pid": "03wvrwpv", "head_count": 2}]
_MEMBERS = {"13000000": ["a", "b"]}
_ROOM_TARGET = {"type": "room", "id": "13000000"}


def _client():
    return CloudClient("u", "p", "33", "sk", "dev", "ck", sid="s", ecode="e")


# --- Client: the captured request bodies (route, version, shape) -------------------------------


async def test_vacation_leave_body_temperature_is_string():
    fake = FakeHttp({"tuya.m.solution.wkf.vacation.plan.leave": {"ok": True}})
    with patch(_HTTP, return_value=fake):
        await _client().async_vacation_leave(
            1, "20261220", "08:00", "20270105", "18:00", 150, ["r1", "r2"]
        )
    api, version, body, _ = fake.calls[0]
    assert api == "tuya.m.solution.wkf.vacation.plan.leave" and version == "1.0"
    assert body == {
        "startDate": "20261220",
        "startTime": "08:00",
        "endDate": "20270105",
        "endTime": "18:00",
        "temperature": "150",  # STRING tenths in plan.leave
        "homeId": "1",
        "roomIds": "r1,r2",  # csv
        "timeZoneId": "Europe/Paris",
    }


async def test_vacation_athome_body_has_no_temperature():
    fake = FakeHttp({"tuya.m.solution.wkf.vacation.plan.athome": {"ok": True}})
    with patch(_HTTP, return_value=fake):
        await _client().async_vacation_athome(1, "20261220", "20270105", "r1")
    api, version, body, _ = fake.calls[0]
    assert api == "tuya.m.solution.wkf.vacation.plan.athome" and version == "1.0"
    assert body == {
        "startDate": "20261220",
        "endDate": "20270105",
        "homeId": "1",
        "roomIds": "r1",
        "timeZoneId": "Europe/Paris",
    }
    assert "temperature" not in body


async def test_vacation_cancel_body():
    fake = FakeHttp({"tuya.m.solution.wkf.vacation.cancel": {"ok": True}})
    with patch(_HTTP, return_value=fake):
        await _client().async_vacation_cancel(1)
    assert fake.calls[0][:2] == ("tuya.m.solution.wkf.vacation.cancel", "1.0")
    assert fake.calls[0][2] == {"homeId": "1", "timeZoneId": "Europe/Paris"}


async def test_vacation_leave_now_temperature_is_int():
    fake = FakeHttp({"tuya.m.solution.wkf.vacation.leave.now": {"ok": True}})
    with patch(_HTTP, return_value=fake):
        await _client().async_vacation_leave_now(1, ["r1", "r2"], 150)
    api, version, body, _ = fake.calls[0]
    assert api == "tuya.m.solution.wkf.vacation.leave.now" and version == "1.0"
    assert body["temperature"] == 150 and isinstance(body["temperature"], int)  # INT tenths
    assert body == {
        "homeId": "1",
        "roomIds": "r1,r2",
        "temperature": 150,
        "timeZoneId": "Europe/Paris",
    }


# --- Operations / services: the gate and the value validation ----------------------------------


@pytest.fixture(autouse=True)
def _no_timer(monkeypatch):
    monkeypatch.setattr(ops, "_defer_verification", lambda *a, **k: None)


async def _setup(hass: HomeAssistant, *, vacation_write: bool):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id="compte@exemple.fr",
        options={CONF_ENABLE_VACATION_WRITE: vacation_write},
    )
    entry.add_to_hass(hass)
    fake = FakeCloudClient(
        devices=[head("a", "Salle 1 #2"), head("b", "Salle 1 #3")],
        groups=_GROUPS,
        members=_MEMBERS,
    )
    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, fake


async def _call(hass, service, data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def test_vacation_disabled_by_default(hass: HomeAssistant):
    await _setup(hass, vacation_write=False)
    with pytest.raises(ServiceValidationError) as exc:
        await _call(
            hass,
            "set_vacation",
            {
                "home": "1",
                "start_date": "20261220",
                "start_time": "08:00",
                "end_date": "20270105",
                "end_time": "18:00",
                "temperature": 15.0,
            },
        )
    assert exc.value.translation_key == "vacation_disabled"


async def test_set_vacation_away_defaults_to_all_rooms(hass: HomeAssistant):
    _, fake = await _setup(hass, vacation_write=True)
    res = await _call(
        hass,
        "set_vacation",
        {
            "home": "1",
            "start_date": "20261220",
            "start_time": "08:00",
            "end_date": "20270105",
            "end_time": "18:00",
            "temperature": 15.0,
        },
    )
    assert res["mode"] == "away" and res["temperature"] == 15.0 and res["rooms"] == ["room-5"]
    call = next(w for w in fake.writes if w[0] == "vac_leave")
    # (tag, home, start_date, start_time, end_date, end_time, tenths, roomIds, tz)
    assert call[1] == "1" and call[6] == 150 and call[7] == "room-5"


async def test_set_vacation_rejects_reversed_period(hass: HomeAssistant):
    await _setup(hass, vacation_write=True)
    with pytest.raises(ServiceValidationError) as exc:
        await _call(
            hass,
            "set_vacation",
            {
                "home": "1",
                "start_date": "20270105",
                "start_time": "08:00",
                "end_date": "20261220",
                "end_time": "18:00",
                "temperature": 15.0,
            },
        )
    assert exc.value.translation_key == "invalid_vacation_period"


async def test_set_vacation_rejects_bad_date(hass: HomeAssistant):
    await _setup(hass, vacation_write=True)
    with pytest.raises(ServiceValidationError) as exc:
        await _call(
            hass,
            "set_vacation",
            {
                "home": "1",
                "start_date": "2026-12-20",  # wrong format
                "start_time": "08:00",
                "end_date": "20270105",
                "end_time": "18:00",
                "temperature": 15.0,
            },
        )
    assert exc.value.translation_key == "invalid_date"


async def test_set_vacation_rejects_out_of_range_temperature(hass: HomeAssistant):
    await _setup(hass, vacation_write=True)
    with pytest.raises(ServiceValidationError) as exc:
        await _call(
            hass,
            "set_vacation",
            {
                "home": "1",
                "start_date": "20261220",
                "start_time": "08:00",
                "end_date": "20270105",
                "end_time": "18:00",
                "temperature": 99.0,
            },
        )
    assert exc.value.translation_key == "invalid_setpoint"


async def test_set_vacation_unknown_home(hass: HomeAssistant):
    await _setup(hass, vacation_write=True)
    with pytest.raises(ServiceValidationError) as exc:
        await _call(
            hass,
            "set_vacation",
            {
                "home": "999",
                "start_date": "20261220",
                "start_time": "08:00",
                "end_date": "20270105",
                "end_time": "18:00",
                "temperature": 15.0,
            },
        )
    assert exc.value.translation_key == "unknown_home"


async def test_vacation_at_home_and_cancel_and_end(hass: HomeAssistant):
    _, fake = await _setup(hass, vacation_write=True)
    await _call(
        hass,
        "set_vacation_at_home",
        {"home": "1", "start_date": "20261220", "end_date": "20270105"},
    )
    assert any(w[0] == "vac_athome" for w in fake.writes)
    await _call(hass, "cancel_vacation", {"home": "1"})
    assert ("vac_cancel", "1", "Europe/Paris") in fake.writes
    await _call(hass, "end_vacation", {"home": "1", "temperature": 20.0})
    end = next(w for w in fake.writes if w[0] == "vac_leave_now")
    assert end[1] == "1" and end[3] == 200  # tenths int


async def test_set_vacation_explicit_rooms_resolved(hass: HomeAssistant):
    _, fake = await _setup(hass, vacation_write=True)
    await _call(
        hass,
        "set_vacation",
        {
            "home": "1",
            "start_date": "20261220",
            "start_time": "08:00",
            "end_date": "20270105",
            "end_time": "18:00",
            "temperature": 15.0,
            "rooms": [_ROOM_TARGET],
        },
    )
    call = next(w for w in fake.writes if w[0] == "vac_leave")
    assert call[7] == "room-5"  # group id resolved to its Tuya room id


# --- WebSocket parity ---------------------------------------------------------------------------


async def test_ws_vacation_set_cancel_and_gate(hass: HomeAssistant):
    from custom_components.danfoss_ally_cloud import websocket_api as ws

    from .test_services_ws import _FakeConn

    _, fake = await _setup(hass, vacation_write=True)
    conn = _FakeConn(is_admin=True)
    ws.ws_vacation_set(
        hass,
        conn,
        {
            "id": 60,
            "home": "1",
            "start_date": "20261220",
            "start_time": "08:00",
            "end_date": "20270105",
            "end_time": "18:00",
            "temperature": 15.0,
            "time_zone": "Europe/Paris",
        },
    )
    await hass.async_block_till_done()
    assert conn.results[60]["mode"] == "away"
    ws.ws_vacation_cancel(hass, conn, {"id": 61, "home": "1", "time_zone": "Europe/Paris"})
    await hass.async_block_till_done()
    assert conn.results[61]["cancelled"] is True
    assert any(w[0] == "vac_cancel" for w in fake.writes)


async def test_ws_vacation_gate_off_errors(hass: HomeAssistant):
    from custom_components.danfoss_ally_cloud import websocket_api as ws

    from .test_services_ws import _FakeConn

    await _setup(hass, vacation_write=False)
    conn = _FakeConn(is_admin=True)
    ws.ws_vacation_cancel(hass, conn, {"id": 62, "home": "1", "time_zone": "Europe/Paris"})
    await hass.async_block_till_done()
    assert conn.errors and conn.errors[-1][0] == "vacation_disabled"
