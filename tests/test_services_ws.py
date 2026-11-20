"""Integration tests of the actions and WebSocket commands (hass harness).

The WebSocket server does not start in this environment (HTTP stack import fails, outside
de ce code) : on appelle les handlers WebSocket en direct avec une fausse connexion.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError, Unauthorized
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud import operations as ops
from custom_components.danfoss_ally_cloud import websocket_api as ws
from custom_components.danfoss_ally_cloud.const import DOMAIN

from .common import ENTRY_DATA, FakeCloudClient, head

_GROUPS = [{"group_id": "13000000", "name": "Salle 1", "pid": "03wvrwpv", "head_count": 2}]
_MEMBERS = {"13000000": ["a", "b"]}
_ROOM_TARGET = {"type": "room", "id": "13000000"}
_VALID_DAYS = {"mon": [{"start": "08:30", "end": "17:30"}]}
_INVALID_DAYS = {"mon": [{"start": "17:30", "end": "08:30"}]}


@pytest.fixture(autouse=True)
def _no_timer(monkeypatch):
    monkeypatch.setattr(ops, "_defer_verification", lambda *a, **k: None)


@pytest.fixture
async def setup(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr")
    entry.add_to_hass(hass)
    fake = FakeCloudClient(
        devices=[head("a", "Salle 1 #2"), head("b", "Salle 1 #3")],
        groups=_GROUPS,
        members=_MEMBERS,
    )
    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    yield hass, entry, fake
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


# --- Actions (services) ------------------------------------------------------------------------


async def test_service_get_rooms(setup):
    hass, _, _ = setup
    res = await hass.services.async_call(
        DOMAIN, "get_rooms", {}, blocking=True, return_response=True
    )
    assert res["rooms"][0]["id"] == "13000000"
    assert {h["device_id"] for h in res["rooms"][0]["heads"]} == {"a", "b"}


async def test_service_get_schedule(setup):
    hass, _, _ = setup
    res = await hass.services.async_call(
        DOMAIN, "get_schedule", {"target": _ROOM_TARGET}, blocking=True, return_response=True
    )
    assert res["target"] == _ROOM_TARGET and "mon" in res["days"]


async def test_service_get_local_survey_disabled(setup):
    """Without the local tunnel, the service raises the translated local_disabled error."""
    hass, _, _ = setup
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "get_local_survey", {}, blocking=True, return_response=True
        )


async def test_service_set_descaling_disabled(setup):
    """With the local tunnel off, set_descaling raises the translated local_disabled error."""
    hass, _, _ = setup
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_descaling",
            {"target": {"type": "device", "id": "a"}, "day": "wed", "time": "13:00"},
            blocking=True,
            return_response=True,
        )


async def test_service_overrides_disabled(setup):
    """set_override and clear_override raise local_disabled when the tunnel is off."""
    hass, _, _ = setup
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_override",
            {"target": {"type": "device", "id": "a"}, "temperature": 20},
            blocking=True,
            return_response=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "clear_override",
            {"target": {"type": "device", "id": "a"}},
            blocking=True,
            return_response=True,
        )


async def test_service_set_window_detection_disabled(setup):
    hass, _, _ = setup
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_window_detection",
            {"target": {"type": "device", "id": "a"}, "enabled": True},
            blocking=True,
            return_response=True,
        )


async def test_service_set_schedule_invalide(setup):
    hass, _, fake = setup
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_schedule",
            {"target": _ROOM_TARGET, "days": _INVALID_DAYS},
            blocking=True,
            return_response=True,
        )
    assert fake.writes == []


async def test_service_set_schedule_valide_et_non_admin(setup, hass_read_only_user):
    hass, _, fake = setup
    res = await hass.services.async_call(
        DOMAIN,
        "set_schedule",
        {"target": _ROOM_TARGET, "days": _VALID_DAYS},
        blocking=True,
        return_response=True,
    )
    assert res["kind"] == "set_schedule" and any(w[0] == "set" for w in fake.writes)
    fake.writes.clear()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_schedule",
            {"target": _ROOM_TARGET, "days": _VALID_DAYS},
            blocking=True,
            return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    assert fake.writes == []


async def test_service_restore_puis_get_write_job(setup):
    hass, _, _ = setup
    job = await hass.services.async_call(
        DOMAIN, "restore_schedule", {"target": _ROOM_TARGET}, blocking=True, return_response=True
    )
    got = await hass.services.async_call(
        DOMAIN, "get_write_job", {"job_id": job["job_id"]}, blocking=True, return_response=True
    )
    assert got["job_id"] == job["job_id"] and job["kind"] == "restore"


# --- Commandes WebSocket (handlers en direct) --------------------------------------------------


class _FakeConn:
    def __init__(self, is_admin=True):
        self.user = SimpleNamespace(is_admin=is_admin)
        self.results: dict = {}
        self.errors: list = []
        self.messages: list = []
        self.subscriptions: dict = {}

    def send_result(self, msg_id, result=None):
        self.results[msg_id] = result

    def send_error(self, msg_id, code, message):
        self.errors.append((code, message))

    def send_message(self, message):
        self.messages.append(message)


async def test_ws_rooms_validate_info(setup):
    hass, _, _ = setup
    conn = _FakeConn()
    ws.ws_rooms(hass, conn, {"id": 1, "type": "danfoss_ally_cloud/rooms"})
    assert conn.results[1]["rooms"][0]["id"] == "13000000"
    ws.ws_schedule_validate(hass, conn, {"id": 2, "days": _INVALID_DAYS})
    assert conn.results[2]["valid"] is False
    ws.ws_info(hass, conn, {"id": 3})
    await hass.async_block_till_done()
    assert conn.results[3]["is_admin"] is True and conn.results[3]["version"]


async def test_ws_schedule_get_set_restore_and_refusal(setup):
    hass, _, fake = setup
    conn = _FakeConn(is_admin=True)
    ws.ws_schedule_get(hass, conn, {"id": 4, "target": _ROOM_TARGET, "refresh": False})
    await hass.async_block_till_done()
    assert conn.results[4]["target"] == _ROOM_TARGET

    ws.ws_schedule_set(hass, conn, {"id": 5, "target": _ROOM_TARGET, "days": _VALID_DAYS})
    await hass.async_block_till_done()
    assert conn.results[5]["kind"] == "set_schedule"

    ws.ws_schedule_restore(hass, conn, {"id": 6, "target": _ROOM_TARGET})
    await hass.async_block_till_done()
    assert conn.results[6]["kind"] == "restore"

    with pytest.raises(Unauthorized):
        ws.ws_schedule_set(
            hass, _FakeConn(is_admin=False), {"id": 7, "target": _ROOM_TARGET, "days": _VALID_DAYS}
        )


async def test_ws_local_survey_disabled(setup):
    hass, _, _ = setup
    conn = _FakeConn()
    ws.ws_local_survey(hass, conn, {"id": 9, "type": "danfoss_ally_cloud/local_survey"})
    await hass.async_block_till_done()
    assert conn.errors and conn.errors[-1][0] == "local_disabled"


async def test_ws_set_descaling_disabled(setup):
    hass, _, _ = setup
    conn = _FakeConn(is_admin=True)
    ws.ws_set_descaling(
        hass,
        conn,
        {"id": 10, "target": {"type": "device", "id": "a"}, "day": "wed", "time": "13:00"},
    )
    await hass.async_block_till_done()
    assert conn.errors and conn.errors[-1][0] == "local_disabled"


async def test_ws_overrides_disabled(setup):
    hass, _, _ = setup
    conn = _FakeConn(is_admin=True)
    ws.ws_set_override(
        hass, conn, {"id": 11, "target": {"type": "device", "id": "a"}, "temperature": 20.0}
    )
    await hass.async_block_till_done()
    ws.ws_clear_override(hass, conn, {"id": 12, "target": {"type": "device", "id": "a"}})
    await hass.async_block_till_done()
    assert [c for c, _ in conn.errors].count("local_disabled") == 2


async def test_ws_set_window_detection_disabled(setup):
    hass, _, _ = setup
    conn = _FakeConn(is_admin=True)
    ws.ws_set_window_detection(
        hass, conn, {"id": 13, "target": {"type": "device", "id": "a"}, "enabled": True}
    )
    await hass.async_block_till_done()
    assert conn.errors and conn.errors[-1][0] == "local_disabled"


async def test_ws_jobs_subscribe(setup):
    hass, _, _ = setup
    conn = _FakeConn()
    ws.ws_jobs_subscribe(hass, conn, {"id": 8, "type": "danfoss_ally_cloud/jobs/subscribe"})
    assert 8 in conn.subscriptions and 8 in conn.results


# --- B4: get_room (read) -----------------------------------------------------------------------


async def test_service_get_room(setup):
    hass, _, _ = setup
    res = await hass.services.async_call(
        DOMAIN, "get_room", {"target": _ROOM_TARGET}, blocking=True, return_response=True
    )
    assert res["room"]["id"] == "13000000"
    assert {h["device_id"] for h in res["room"]["heads"]} == {"a", "b"}
    assert "mon" in res["schedule"]["days"]


async def test_service_get_room_unknown(setup):
    hass, _, _ = setup
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "get_room",
            {"target": {"type": "room", "id": "nope"}},
            blocking=True,
            return_response=True,
        )


async def test_ws_room_get(setup):
    hass, _, _ = setup
    conn = _FakeConn()
    ws.ws_room_get(hass, conn, {"id": 20, "target": _ROOM_TARGET})
    await hass.async_block_till_done()
    assert conn.results[20]["room"]["id"] == "13000000"


async def test_ws_room_get_device_refused(setup):
    hass, _, _ = setup
    conn = _FakeConn()
    ws.ws_room_get(hass, conn, {"id": 21, "target": {"type": "device", "id": "a"}})
    await hass.async_block_till_done()
    assert conn.errors and conn.errors[-1][0] == "unknown_room"


# --- B5: room management writes ----------------------------------------------------------------


async def test_service_create_room(setup):
    hass, _, fake = setup
    res = await hass.services.async_call(
        DOMAIN,
        "create_room",
        {"name": "Classroom", "devices": ["a", "b"]},
        blocking=True,
        return_response=True,
    )
    assert res["room_id"] == "new-7"
    assert ("room_add", "1", "Classroom") in fake.writes  # home inferred from the devices
    assert ("room_set", "new-7", ["a", "b"]) in fake.writes


async def test_service_create_room_not_admin(setup):
    hass, _, _ = setup
    ctx = Context(user_id="non-admin")
    with (
        patch.object(hass.auth, "async_get_user", return_value=SimpleNamespace(is_admin=False)),
        pytest.raises((Unauthorized, ServiceValidationError)),
    ):
        await hass.services.async_call(
            DOMAIN,
            "create_room",
            {"name": "X", "devices": ["a"]},
            blocking=True,
            context=ctx,
            return_response=True,
        )


async def test_service_disconnect_head_not_admin(setup):
    # The most destructive write must refuse a non-admin at the service layer, and send nothing.
    hass, _, fake = setup
    ctx = Context(user_id="non-admin")
    with (
        patch.object(hass.auth, "async_get_user", return_value=SimpleNamespace(is_admin=False)),
        pytest.raises((Unauthorized, ServiceValidationError)),
    ):
        await hass.services.async_call(
            DOMAIN,
            "disconnect_head",
            {"target": {"type": "device", "id": "a"}, "confirm": True},
            blocking=True,
            context=ctx,
            return_response=True,
        )
    assert not any(w[0] == "device_reset" for w in fake.writes)  # nothing sent


async def test_ws_room_rename_and_delete(setup):
    hass, _, fake = setup
    conn = _FakeConn(is_admin=True)
    ws.ws_room_rename(hass, conn, {"id": 30, "target": _ROOM_TARGET, "name": "New"})
    await hass.async_block_till_done()
    assert conn.results[30]["room_id"] == "room-5"
    assert ("room_update", "room-5", "New") in fake.writes
    ws.ws_room_delete(hass, conn, {"id": 31, "target": _ROOM_TARGET})
    await hass.async_block_till_done()
    assert ("room_dismiss", "room-5") in fake.writes


async def test_ws_room_attach_detach(setup):
    hass, _, fake = setup
    conn = _FakeConn(is_admin=True)
    ws.ws_room_attach(hass, conn, {"id": 32, "target": _ROOM_TARGET, "devices": ["a"]})
    await hass.async_block_till_done()
    # a (already a member) + b (member): the member list stays {a, b}
    assert conn.results[32]["heads"] == ["a", "b"]
    ws.ws_room_detach(hass, conn, {"id": 33, "target": _ROOM_TARGET, "devices": ["b"]})
    await hass.async_block_till_done()
    assert conn.results[33]["heads"] == ["a"]
    assert ("room_set", "room-5", ["a"]) in fake.writes


async def test_ws_room_create(setup):
    hass, _, fake = setup
    conn = _FakeConn(is_admin=True)
    ws.ws_room_create(hass, conn, {"id": 34, "name": "C", "devices": ["a", "b"]})
    await hass.async_block_till_done()
    assert conn.results[34]["room_id"] == "new-7"


# --- B7: read services for holiday / relays ----------------------------------------------------


def test_holidays_payload_shape():
    from types import SimpleNamespace

    from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR

    coord = SimpleNamespace(
        holidays={"1": {"name": "H", "active": True, "scheduled": False, "detail": {"temp": 150}}},
    )
    out = ops.holidays_payload({DATA_COORDINATOR: coord})
    assert out == {
        "holidays": [
            {
                "home": "H",
                "gid": "1",
                "active": True,
                "scheduled": False,
                "detail": {"temp": 150},
            }
        ]
    }


async def test_service_get_holiday_and_relays(setup):
    hass, _, _ = setup
    hol = await hass.services.async_call(
        DOMAIN, "get_holiday", {}, blocking=True, return_response=True
    )
    assert "holidays" in hol
    rel = await hass.services.async_call(
        DOMAIN, "get_relays", {}, blocking=True, return_response=True
    )
    assert "relays" in rel


async def test_ws_holiday_and_relays(setup):
    hass, _, _ = setup
    conn = _FakeConn()
    ws.ws_holiday(hass, conn, {"id": 40})
    ws.ws_relays(hass, conn, {"id": 41})
    assert "holidays" in conn.results[40]
    assert "relays" in conn.results[41]


# --- D1: fleet overview + enriched room payload (axis D) ---------------------------------------


async def test_service_get_overview(setup):
    hass, _, _ = setup
    res = await hass.services.async_call(
        DOMAIN, "get_overview", {}, blocking=True, return_response=True
    )
    assert "homes" in res and "totals" in res
    assert res["totals"]["rooms"] == 1 and res["totals"]["heads"] == 2
    room = res["homes"][0]["rooms"][0]
    assert room["id"] == "13000000" and room["head_count"] == 2


async def test_ws_overview_and_room_climate_entity(setup):
    hass, _, _ = setup
    conn = _FakeConn()
    ws.ws_overview(hass, conn, {"id": 50})
    assert "homes" in conn.results[50]
    # The enriched room payload resolves the real room climate entity id (registry path).
    ws.ws_rooms(hass, conn, {"id": 51, "type": "danfoss_ally_cloud/rooms"})
    room = conn.results[51]["rooms"][0]
    assert room["climate_entity_id"] and room["climate_entity_id"].startswith("climate.")
    assert room["writable"] is True


# --- Service-path coverage of the remaining write wrappers (parity with the WS tests above) -----


async def test_service_copy_schedule(setup):
    hass, _, fake = setup
    res = await hass.services.async_call(
        DOMAIN,
        "copy_schedule",
        {"source": _ROOM_TARGET, "targets": [_ROOM_TARGET]},
        blocking=True,
        return_response=True,
    )
    assert len(res["jobs"]) == 1 and res["jobs"][0]["kind"] == "set_schedule"
    assert any(w[0] == "set" for w in fake.writes)


async def test_service_rename_and_delete_room(setup):
    hass, _, fake = setup
    res = await hass.services.async_call(
        DOMAIN,
        "rename_room",
        {"target": _ROOM_TARGET, "name": "New"},
        blocking=True,
        return_response=True,
    )
    assert res["room_id"] == "room-5"
    assert ("room_update", "room-5", "New") in fake.writes
    await hass.services.async_call(
        DOMAIN, "delete_room", {"target": _ROOM_TARGET}, blocking=True, return_response=True
    )
    assert ("room_dismiss", "room-5") in fake.writes


async def test_service_attach_and_detach_heads(setup):
    hass, _, fake = setup
    res = await hass.services.async_call(
        DOMAIN,
        "attach_heads",
        {"target": _ROOM_TARGET, "devices": ["a"]},
        blocking=True,
        return_response=True,
    )
    assert res["heads"] == ["a", "b"]
    res2 = await hass.services.async_call(
        DOMAIN,
        "detach_heads",
        {"target": _ROOM_TARGET, "devices": ["b"]},
        blocking=True,
        return_response=True,
    )
    assert res2["heads"] == ["a"]
    assert ("room_set", "room-5", ["a"]) in fake.writes


async def test_service_set_relay_room(hass: HomeAssistant):
    """set_relay_room via the service path: matches the room by name, calls reference.edit."""
    from .common import relay

    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr")
    entry.add_to_hass(hass)
    fake = FakeCloudClient(
        devices=[head("a", "Salle 1 #2"), head("b", "Salle 1 #3"), relay("relay-1")],
        groups=_GROUPS,
        members=_MEMBERS,
        relay_rooms={"relay-1": [{"room_id": "r9", "name": "Salle 1", "linked": False}]},
    )
    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    res = await hass.services.async_call(
        DOMAIN,
        "set_relay_room",
        {"relay": "relay-1", "target": _ROOM_TARGET, "linked": True},
        blocking=True,
        return_response=True,
    )
    assert res == {"relay": "relay-1", "room_id": "r9", "linked": True}
    assert ("relay_bind", "relay-1", "r9", True) in fake.writes
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_dynamic_topology_sync_adds_and_removes_room_and_head_entities(setup):
    """When a room is created or dissolved at runtime, the climate and number platforms add and
    remove the room and isolated-head entities dynamically without an entry reload."""
    from homeassistant.helpers import entity_registry as er

    hass, entry, fake = setup
    reg = er.async_get(hass)
    # Initial state: room 13000000 exists with heads a & b (no per-head climate for a or b).
    assert reg.async_get_entity_id("climate", DOMAIN, "13000000") is not None
    assert reg.async_get_entity_id("number", DOMAIN, "13000000_comfort_setpoint") is not None
    assert reg.async_get_entity_id("climate", DOMAIN, "a") is None

    # Dissolve the room in the cloud topology and refresh: room entities are retired, and
    # isolated-head climates are created for a & b.
    fake._groups = []
    fake._members = {}
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    coordinator.invalidate_topology()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert reg.async_get_entity_id("climate", DOMAIN, "13000000") is None
    assert reg.async_get_entity_id("number", DOMAIN, "13000000_comfort_setpoint") is None
    assert reg.async_get_entity_id("climate", DOMAIN, "a") is not None
    assert reg.async_get_entity_id("climate", DOMAIN, "b") is not None

    # Recreate a room grouping a & b: the isolated-head climates are retired and the new room
    # climate + setpoints appear.
    fake._groups = [{"group_id": "24000000", "name": "Salle 2", "pid": "03wvrwpv", "head_count": 2}]
    fake._members = {"24000000": ["a", "b"]}
    coordinator.invalidate_topology()
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert reg.async_get_entity_id("climate", DOMAIN, "24000000") is not None
    assert reg.async_get_entity_id("number", DOMAIN, "24000000_comfort_setpoint") is not None
    assert reg.async_get_entity_id("climate", DOMAIN, "a") is None
    assert reg.async_get_entity_id("climate", DOMAIN, "b") is None


def test_ws_store_resolves_target_and_home_across_multiple_entries(hass: HomeAssistant):
    """With multiple config entries and no explicit entry_id, _store resolves by room target,
    device target, or home gid, and falls back to the first entry for fleet queries."""
    from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR

    c1 = SimpleNamespace(
        rooms={"r1": object()},
        data={"d1": object()},
        holidays={"h1": {}},
        home_of=lambda g: "h1" if g == "r1" else None,
    )
    c2 = SimpleNamespace(
        rooms={"r2": object()},
        data={"d2": object()},
        holidays={"h2": {}},
        home_of=lambda g: "h2" if g == "r2" else None,
    )
    s1 = {DATA_COORDINATOR: c1}
    s2 = {DATA_COORDINATOR: c2}
    hass.data[DOMAIN] = {"e1": s1, "e2": s2}

    assert ws._store(hass, {"entry_id": "e2"}) is s2
    assert ws._store(hass, {"target": {"type": "room", "id": "r2"}}) is s2
    assert ws._store(hass, {"target": {"type": "device", "id": "d2"}}) is s2
    assert ws._store(hass, {"home": "h2"}) is s2
    assert ws._store(hass, {}) is s1
