"""Message center of the app (docs/message-center.md): parsing, coordinator, sensor, event,
diagnostics. Synthetic data only (no real id, no real text)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.danfoss_ally_cloud.api import CloudClient, CloudError
from custom_components.danfoss_ally_cloud.api._tuya.http import TuyaApiError
from custom_components.danfoss_ally_cloud.api.messages import (
    CATEGORY_ALERT,
    CATEGORY_HOME,
    CATEGORY_OTHER,
    CATEGORY_SYSTEM,
    MSG_LIST_API,
    MSG_LIST_VERSION,
    parse_message,
    parse_messages,
)
from custom_components.danfoss_ally_cloud.const import (
    DATA_COORDINATOR,
    DATA_MESSAGES,
    DOMAIN,
    EVENT_MESSAGE,
)
from custom_components.danfoss_ally_cloud.coordinator import (
    DanfossCoordinator,
    DanfossMessageCoordinator,
)
from custom_components.danfoss_ally_cloud.device_links import find_device
from custom_components.danfoss_ally_cloud.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .common import ENTRY_DATA, FakeCloudClient, head

T0 = 1_790_000_000  # synthetic epoch


def raw_msg(n: int, *, msg_type=4, code="SMART_MSG_V3", src="dev-1", big=1, **kw) -> dict:
    """A synthetic ``msg.list`` v2.0 element (shape of docs/message-center.md)."""
    m = {
        "id": 9_000_000_000_000_000_000 + n,
        "idStr": f"9{n:018d}",
        "time": T0 + n * 60,
        "dateTime": "2026-1-2 03:04",
        "msgType": msg_type,
        "msgTypeContent": {4: "Low Battery Warning", -1: "Home Message", 0: "System"}.get(
            msg_type, "Other"
        ),
        "msgCode": code,
        "msgContent": f"synthetic message {n}",
        "readStatus": 0,
        "uid": "uid-synthetic",
        "homeId": "home-synthetic",
        "sceneId": "scene-synthetic",
        "icon": "https://example.invalid/icon.png",
        "actionURL": "https://example.invalid/action",
    }
    if msg_type == 4:
        m["msgTitle"] = "Low Battery Warning"
    if big is not None and msg_type == 4:
        m["bigMsgType"] = big
    if src is not None:
        m["msgSrcId"] = src
    m.update(kw)
    return m


# --- parsing -------------------------------------------------------------------------------


def test_parse_alert_fields():
    msg = parse_message(raw_msg(1))
    assert msg is not None
    assert msg.message_id == "9000000000000000001"
    assert msg.time == T0 + 60
    assert msg.timestamp == datetime.fromtimestamp(T0 + 60, tz=UTC)
    assert msg.category == CATEGORY_ALERT and msg.is_alert
    assert msg.title == "Low Battery Warning"
    assert msg.content == "synthetic message 1"
    assert msg.source_id == "dev-1"
    assert msg.read_status == 0
    assert msg.alarm is True


def test_parse_categories():
    assert parse_message(raw_msg(1, msg_type=-1, big=None)).category == CATEGORY_HOME
    assert parse_message(raw_msg(1, msg_type=0, big=None)).category == CATEGORY_SYSTEM
    assert parse_message(raw_msg(1, msg_type=-7, big=None)).category == CATEGORY_OTHER
    # An alarm template not seen yet still counts as an alert, by msgType or by bigMsgType.
    assert parse_message(raw_msg(1, msg_type=1, big=None)).is_alert
    assert parse_message(raw_msg(1, msg_type=-7, bigMsgType=1)).is_alert
    no_type = raw_msg(1)
    del no_type["msgType"], no_type["bigMsgType"]
    assert parse_message(no_type).category == CATEGORY_OTHER


def test_parse_id_fallbacks_and_rejects():
    no_str = raw_msg(2)
    del no_str["idStr"]
    assert parse_message(no_str).message_id == str(9_000_000_000_000_000_002)
    str_time = raw_msg(3, time=str(T0))
    assert parse_message(str_time).time == T0
    assert parse_message(raw_msg(4, time="soon")) is None
    assert parse_message(raw_msg(4, time=0)) is None
    assert parse_message(raw_msg(4, time=True)) is None
    no_id = raw_msg(5)
    del no_id["idStr"], no_id["id"]
    assert parse_message(no_id) is None
    assert parse_message("garbage") is None


def test_parse_missing_optional_fields():
    minimal = {"idStr": "1", "time": T0}
    msg = parse_message(minimal)
    assert msg is not None
    assert msg.msg_type is None and msg.code is None and msg.title is None
    assert msg.content is None and msg.source_id is None and msg.read_status is None
    out = msg.public_dict()
    assert out["title"] is None and out["device"] is None
    # Title falls back on the type label when the message carries no title.
    home = parse_message(raw_msg(6, msg_type=-1, big=None)).public_dict("Salon")
    assert home["title"] == "Home Message" and home["device"] == "Salon"


def test_parse_messages_sorts_dedups_and_tolerates_shapes():
    raw = [raw_msg(1), raw_msg(3), "junk", raw_msg(2), raw_msg(3)]
    msgs = parse_messages(raw)
    assert [m.message_id for m in msgs] == [
        "9000000000000000003",
        "9000000000000000002",
        "9000000000000000001",
    ]
    assert parse_messages({"datas": [raw_msg(1)], "pageNo": 0}) == [parse_message(raw_msg(1))]
    assert parse_messages({"datas": None}) == []
    assert parse_messages(None) == []


def test_public_dict_carries_no_identifier():
    out = parse_message(raw_msg(1)).public_dict("Salon")
    flat = repr(out)
    for secret in (
        "9000000000000000001",
        "dev-1",
        "uid-synthetic",
        "home-synthetic",
        "scene-synthetic",
        "example.invalid",
    ):
        assert secret not in flat
    assert out == {
        "time": datetime.fromtimestamp(T0 + 60, tz=UTC).isoformat(),
        "category": "alert",
        "type": "Low Battery Warning",
        "code": "SMART_MSG_V3",
        "title": "Low Battery Warning",
        "message": "synthetic message 1",
        "device": "Salon",
        "read_status": 0,
    }


# --- client --------------------------------------------------------------------------------


async def test_client_reads_the_whole_list_without_body():
    client = CloudClient("u", "p", "33", "sk", "dev", "ch", sid="s", ecode="e")
    with patch.object(client, "_request", AsyncMock(return_value=[raw_msg(1), raw_msg(2)])) as req:
        msgs = await client.async_list_messages()
    req.assert_awaited_once_with(MSG_LIST_API, MSG_LIST_VERSION, None)
    assert [m.message_id for m in msgs] == ["9000000000000000002", "9000000000000000001"]


async def test_client_relogs_in_on_session_error():
    client = CloudClient("u", "p", "33", "sk", "dev", "ch", sid="s", ecode="e")
    once = AsyncMock(
        side_effect=[TuyaApiError("USER_SESSION_INVALID", "session", {}), [raw_msg(1)]]
    )
    with (
        patch.object(client, "_request_once", once),
        patch.object(client, "async_login", AsyncMock()) as login,
    ):
        msgs = await client.async_list_messages()
    login.assert_awaited_once()
    assert len(msgs) == 1


# --- coordinator and event -----------------------------------------------------------------


async def test_backlog_fires_nothing_then_each_new_message_fires(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "dev-1")}, name="Salon"
    )
    fake = FakeCloudClient(messages=[raw_msg(1), raw_msg(2, msg_type=-1, big=None)])
    coord = DanfossMessageCoordinator(hass, fake, entry.entry_id)
    events = async_capture_events(hass, EVENT_MESSAGE)

    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.last_update_success and len(coord.data) == 2
    assert events == []  # backlog at the first read: no replay

    fake.messages_raw = [raw_msg(5, src="gone"), raw_msg(4), *fake.messages_raw]
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert [e.data["message"] for e in events] == ["synthetic message 4", "synthetic message 5"]
    first = events[0].data
    assert first["device_id"] == device.id and first["device"] == "Salon"
    assert first["config_entry_id"] == entry.entry_id and first["category"] == "alert"
    # A source the registry does not know (removed head) gives no device.
    assert events[1].data["device_id"] is None and events[1].data["device"] is None
    assert "dev-1" not in repr([e.data for e in events])

    # Same list again: nothing new.
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert len(events) == 2


async def test_failed_read_is_update_failed_and_keeps_seen(hass: HomeAssistant):
    fake = FakeCloudClient(messages=[raw_msg(1)])
    coord = DanfossMessageCoordinator(hass, fake, "entry")
    events = async_capture_events(hass, EVENT_MESSAGE)
    await coord.async_refresh()
    fake.messages_exc = CloudError("cloud ko")
    await coord.async_refresh()
    assert coord.last_update_success is False
    fake.messages_exc = None
    await coord.async_refresh()
    await hass.async_block_till_done()
    assert coord.last_update_success is True
    assert events == []  # the failure did not reset the seen ids


async def test_device_name_prefers_user_name(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    reg = dr.async_get(hass)
    device = reg.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "dev-1")}, name="Salon"
    )
    reg.async_update_device(device.id, name_by_user="Living room")
    coord = DanfossMessageCoordinator(hass, FakeCloudClient(), entry.entry_id)
    assert coord.device_name("dev-1") == "Living room"
    assert coord.device_name(None) is None
    assert coord.device_name("unknown") is None


# --- setup, sensor, diagnostics ------------------------------------------------------------


async def _setup(hass: HomeAssistant, fake: FakeCloudClient) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr")
    entry.add_to_hass(hass)
    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _sensor_state(hass: HomeAssistant):
    return hass.states.get("sensor.danfoss_ally_account_last_device_alert")


async def test_sensor_state_and_attributes(hass: HomeAssistant):
    fake = FakeCloudClient(
        devices=[head()],
        messages=[
            raw_msg(1),
            raw_msg(2, src="dev-unknown"),
            raw_msg(3, msg_type=-1, big=None),
            raw_msg(4, msg_type=0, big=None, src=None),
        ],
    )
    entry = await _setup(hass, fake)
    state = _sensor_state(hass)
    assert state is not None
    # State = time of the newest ALERT (message 2), not of the newest message (4, system).
    assert state.state == datetime.fromtimestamp(T0 + 120, tz=UTC).isoformat()
    attrs = state.attributes
    assert attrs["alert_count"] == 2 and attrs["message_count"] == 4
    assert attrs["last_alert"]["message"] == "synthetic message 2"
    assert attrs["last_alert"]["device"] is None
    assert [m["category"] for m in attrs["messages"]] == ["system", "home", "alert", "alert"]
    assert attrs["messages"][3]["device"] == "Salon"
    flat = repr(dict(attrs))
    for secret in ("9000000000000000", "dev-1", "dev-unknown", "uid-synthetic", "example.invalid"):
        assert secret not in flat

    # The account device holds the sensor.
    device = find_device(dr.async_get(hass), entry.entry_id, f"account_{entry.entry_id}")
    assert device is not None and device.name == "Danfoss Ally account"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_sensor_without_alert_and_recent_cap(hass: HomeAssistant):
    raw = [raw_msg(n, msg_type=-1, big=None) for n in range(15)]
    await _setup(hass, FakeCloudClient(devices=[head()], messages=raw))
    state = _sensor_state(hass)
    assert state.state == "unknown"
    assert state.attributes["alert_count"] == 0
    assert state.attributes["last_alert"] is None
    assert state.attributes["message_count"] == 15
    assert len(state.attributes["messages"]) == 10


async def test_message_failure_never_blocks_setup(hass: HomeAssistant):
    fake = FakeCloudClient(devices=[head()], messages_exc=CloudError("cloud ko"))
    entry = await _setup(hass, fake)
    assert hass.states.get("sensor.salon_battery") is not None
    assert _sensor_state(hass).state == "unavailable"
    assert entry.runtime_data.messages is not None


async def test_diagnostics_message_center_has_counts_only(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    fake = FakeCloudClient(
        messages=[
            raw_msg(1),
            raw_msg(2, msg_type=-1, big=None, code="ADD_SUB_DEVICE_FOR_LOCATION_MSG_V2"),
        ]
    )
    coord = DanfossCoordinator(hass, fake, 90)
    coord.data = {"dev-1": head()}
    messages = DanfossMessageCoordinator(hass, fake, entry.entry_id)
    await messages.async_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_COORDINATOR: coord,
        DATA_MESSAGES: messages,
    }
    diag = await async_get_config_entry_diagnostics(hass, entry)
    center = diag["message_center"]
    assert center == {
        "last_update_success": True,
        "message_count": 2,
        "by_category": {"alert": 1, "home": 1, "system": 0, "other": 0},
        "codes": ["ADD_SUB_DEVICE_FOR_LOCATION_MSG_V2", "SMART_MSG_V3"],
        "newest_time": datetime.fromtimestamp(T0 + 120, tz=UTC).isoformat(),
    }
    flat = repr(diag["message_center"])
    assert "synthetic message" not in flat and "dev-1" not in flat
