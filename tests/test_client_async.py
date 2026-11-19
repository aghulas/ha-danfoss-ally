"""CloudClient (async) tests with a TuyaHttpClient double (no network)."""

from unittest.mock import patch

import pytest

from custom_components.danfoss_ally_cloud.api import client as client_mod
from custom_components.danfoss_ally_cloud.api._tuya.http import TuyaApiError
from custom_components.danfoss_ally_cloud.api.client import (
    CloudAuthError,
    CloudClient,
    CloudError,
    CloudWriteError,
)

_HTTP = "custom_components.danfoss_ally_cloud.api.client.TuyaHttpClient"
_LOGIN = "custom_components.danfoss_ally_cloud.api.client.login"


class FakeHttp:
    def __init__(self, responses=None, raise_once=None):
        self.responses = responses or {}
        self.raise_once = raise_once
        self.calls: list[tuple] = []

    def request(self, api, version, body=None, extra_params=None):
        self.calls.append((api, version, body, extra_params))
        if self.raise_once is not None:
            exc = self.raise_once
            self.raise_once = None
            raise exc
        r = self.responses.get(api)
        return r(body, extra_params) if callable(r) else r

    def close(self):
        pass


def _head_raw(dev_id="dev-1"):
    return {
        "devId": dev_id,
        "name": "Salon",
        "category": "wk",
        "productId": "03wvrwpv",
        "nodeId": "node-1",
        "meshId": "gw-1",
        "moduleMap": {"zigbee": {"isOnline": True}},
        "dps": {"24": 210, "16": 210, "34": 88},
    }


def _client(sid="s", ecode="e"):
    return CloudClient("u", "p", "33", "sk", "dev", "ck", sid=sid, ecode=ecode)


async def test_async_get_homes():
    fake = FakeHttp({"tuya.m.location.list": [{"groupId": 1, "name": "Maison"}]})
    with patch(_HTTP, return_value=fake):
        homes = await _client().async_get_homes()
    assert homes == [{"gid": 1, "name": "Maison"}]


async def test_async_list_devices_decode():
    fake = FakeHttp(
        {
            "tuya.m.location.list": [{"groupId": 1}],
            "tuya.m.my.group.device.list": [_head_raw("dev-1"), _head_raw("dev-1")],
        }
    )
    with patch(_HTTP, return_value=fake):
        devices = await _client().async_list_devices()
    assert len(devices) == 1  # deduplicated by id
    assert devices[0].temperature == 21.0
    assert devices[0].is_head


async def test_async_write_setting_payload():
    fake = FakeHttp({"tuya.m.custom.wkf.settings.change": {"ok": True}})
    with patch(_HTTP, return_value=fake):
        await _client().async_write_setting("dev-1", "03wvrwpv", {"16": 210})
    api, _, body, _ = fake.calls[-1]
    assert api == "tuya.m.custom.wkf.settings.change"
    assert body["devId"] == "dev-1" and '"16":210' in body["settings"]
    # Without an explicit gateway, gwId falls back to devId (previous behaviour).
    assert body["gwId"] == "dev-1"


async def test_async_write_setting_uses_meshid_gateway():
    """An isolated head's settings write addresses gwId = meshId (contract §4.1/§4.2)."""
    fake = FakeHttp({"tuya.m.custom.wkf.settings.change": {"ok": True}})
    with patch(_HTTP, return_value=fake):
        await _client().async_write_setting(
            "dev-1", "03wvrwpv", {"2": "at_home"}, gw_id="gw-mesh-9"
        )
    _, _, body, _ = fake.calls[-1]
    assert body["devId"] == "dev-1"  # resId/devId stay the head
    assert body["gwId"] == "gw-mesh-9"  # gateway (meshId), not the head's devId


async def test_async_device_meta():
    fake = FakeHttp({"smartlife.m.device.get": {"name": "GW", "meta": {"lan_ip": "10.0.0.9"}}})
    with patch(_HTTP, return_value=fake):
        meta = await _client().async_device_meta("gw-1")
    assert meta["lan_ip"] == "10.0.0.9"


async def test_async_login_sets_session():
    with (
        patch(_HTTP, return_value=FakeHttp()),
        patch(_LOGIN, return_value={"sid": "S2", "ecode": "E2"}),
    ):
        c = _client(sid=None, ecode=None)
        await c.async_login()
    assert c.session == {"sid": "S2", "ecode": "E2"}


async def test_async_login_refused():
    with patch(_LOGIN, return_value={"sid": None, "ecode": None}), pytest.raises(CloudAuthError):
        await _client(sid=None, ecode=None).async_login()


async def test_relogin_sur_session_expiree():
    fake = FakeHttp(
        {"tuya.m.location.list": [{"groupId": 7, "name": "M"}]},
        raise_once=TuyaApiError("APP_SESSION_EXPIRED", "expired", {}),
    )
    with (
        patch(_HTTP, return_value=fake),
        patch(_LOGIN, return_value={"sid": "S3", "ecode": "E3"}) as login_mock,
    ):
        homes = await _client().async_get_homes()
    assert homes == [{"gid": 7, "name": "M"}]
    login_mock.assert_called_once()  # re-login unique


async def test_erreur_non_session_remonte():
    fake = FakeHttp(raise_once=TuyaApiError("PERMISSION_DENIED", "refus", {}))
    with patch(_HTTP, return_value=fake), pytest.raises(CloudError):
        await _client().async_get_homes()


async def test_async_validate_et_close():
    fake = FakeHttp({"tuya.m.location.list": []})
    with (
        patch(_HTTP, return_value=fake),
        patch(_LOGIN, return_value={"sid": "S", "ecode": "E"}),
    ):
        c = _client(sid=None, ecode=None)
        assert await c.async_validate() == []
        await c.async_close()


def test_is_session_error_divers():
    assert client_mod._is_session_error(TuyaApiError("ILLEGAL_CLIENT_ID", "", {}))
    assert client_mod._is_session_error(TuyaApiError(None, "token is expired", {}))
    assert not client_mod._is_session_error(TuyaApiError("OTHER", "", {}))


# --- Durable setpoint at ROOM level (path 1a) ------------------------------------------------


def _groupe_responses(
    *, home_gid=1, group_id=90000001, membre="dev-1", pid="03wvrwpv", programme=None
):
    """FakeHttp response set for discovery + the room setpoint write."""
    if programme is None:
        programme = [
            {"loops": "1000000", "loopData": []},  # dimanche vide
            {
                "loops": "0100000",
                "loopData": [{"startTime": 510, "endTime": 1050, "mode": "at_home"}],
            },
        ]
    return {
        "tuya.m.location.list": [{"groupId": home_gid, "name": "Maison"}],
        "m.life.my.group.device.relation.list": {
            "5": [{"id": group_id, "children": {"6": [{"id": membre}]}}]
        },
        "m.life.my.group.device.group.list": [
            {"id": group_id, "name": "Room", "deviceNum": 2, "productId": pid}
        ],
        "s.m.dev.group.dp.publish": {"result": True},
        "tuya.m.custom.wkf.week.timer.list": {"data": programme},
        "tuya.m.custom.wkf.week.timer.delete": {"result": True},
        "tuya.m.custom.wkf.week.timer.create": {"result": True},
    }


async def test_async_list_groups_et_members():
    fake = FakeHttp(_groupe_responses())
    with patch(_HTTP, return_value=fake):
        c = _client()
        groups = await c.async_list_groups(1)
        members = await c.async_group_members(1)
    assert groups == [{"group_id": 90000001, "name": "Room", "head_count": 2, "pid": "03wvrwpv"}]
    assert members == {"90000001": ["dev-1"]}


async def test_async_resolve_group():
    fake = FakeHttp(_groupe_responses())
    with patch(_HTTP, return_value=fake):
        resolved = await _client().async_resolve_group("dev-1")
    assert resolved == ("90000001", "03wvrwpv")


async def test_async_resolve_group_absent():
    fake = FakeHttp(_groupe_responses())
    with patch(_HTTP, return_value=fake):
        assert await _client().async_resolve_group("inconnue") is None


async def test_async_group_publish_payload():
    fake = FakeHttp(_groupe_responses())
    with patch(_HTTP, return_value=fake):
        await _client().async_group_publish("90000001", {"118": 60})
    api, _, body, _ = fake.calls[-1]
    assert api == "s.m.dev.group.dp.publish"
    assert body == {"dps": '{"118":60}', "groupId": 90000001}


async def test_async_set_room_setpoint_publishes_then_rewrites_schedule():
    fake = FakeHttp(_groupe_responses())
    with patch(_HTTP, return_value=fake):
        group_id = await _client().async_set_room_setpoint("dev-1", {"118": 60})
    assert group_id == "90000001"
    apis = [a for a, *_ in fake.calls]
    assert "s.m.dev.group.dp.publish" in apis
    # a single day rewritten: delete then create
    assert apis.count("tuya.m.custom.wkf.week.timer.delete") == 1
    assert apis.count("tuya.m.custom.wkf.week.timer.create") == 1
    create = next(b for a, _, b, _ in fake.calls if a == "tuya.m.custom.wkf.week.timer.create")
    assert create["loops"] == "0100000"  # the comfort day found
    assert create["periods"] == '[{"startTime": "08:30", "endTime": "17:30"}]'
    assert create["resType"] == 2  # room level


async def test_async_set_room_setpoint_no_comfort_day_does_not_rewrite():
    prog = [{"loops": "1000000", "loopData": []}]  # no comfort window
    fake = FakeHttp(_groupe_responses(programme=prog))
    with patch(_HTTP, return_value=fake):
        await _client().async_set_room_setpoint("dev-1", {"118": 60})
    apis = [a for a, *_ in fake.calls]
    assert "s.m.dev.group.dp.publish" in apis
    assert "tuya.m.custom.wkf.week.timer.create" not in apis


async def test_async_set_room_setpoint_ungrouped_head():
    fake = FakeHttp(_groupe_responses())
    with patch(_HTTP, return_value=fake), pytest.raises(CloudWriteError):
        await _client().async_set_room_setpoint("inconnue", {"118": 60})


async def test_async_set_room_setpoint_without_repush():
    fake = FakeHttp(_groupe_responses())
    with patch(_HTTP, return_value=fake):
        await _client().async_set_room_setpoint("dev-1", {"118": 60}, repush=False)
    apis = [a for a, *_ in fake.calls]
    assert "tuya.m.custom.wkf.week.timer.list" not in apis


async def test_async_set_group_setpoint_direct_without_resolution():
    # The room climate already knows its group: publish + repush, WITHOUT resolving via a head.
    fake = FakeHttp(_groupe_responses())
    with patch(_HTTP, return_value=fake):
        await _client().async_set_group_setpoint("90000001", "03wvrwpv", {"109": 60, "119": 60})
    apis = [a for a, *_ in fake.calls]
    assert "m.life.my.group.device.relation.list" not in apis  # no resolution
    publish = next(b for a, _, b, _ in fake.calls if a == "s.m.dev.group.dp.publish")
    assert publish == {"dps": '{"109":60,"119":60}', "groupId": 90000001}
    assert apis.count("tuya.m.custom.wkf.week.timer.create") == 1


async def test_async_set_group_setpoint_without_pid_does_not_rewrite():
    fake = FakeHttp(_groupe_responses())
    with patch(_HTTP, return_value=fake):
        await _client().async_set_group_setpoint("90000001", None, {"118": 60})
    apis = [a for a, *_ in fake.calls]
    assert "s.m.dev.group.dp.publish" in apis
    assert "tuya.m.custom.wkf.week.timer.list" not in apis  # pid inconnu → pas de re-push


# --- R-3 per-device fresh read (async_get_device_dps via smartlife.m.device.get v4.0) -----------


async def test_get_device_dps_returns_fresh_dps():
    fake = FakeHttp({"smartlife.m.device.get": {"name": "Salon", "dps": {"170": 82, "16": 210}}})
    with patch(_HTTP, return_value=fake):
        dps = await _client().async_get_device_dps("dev-1")
    assert dps == {"170": 82, "16": 210}
    api, version, body, _ = fake.calls[0]
    assert (api, version, body) == ("smartlife.m.device.get", "4.0", {"devId": "dev-1"})


async def test_get_device_dps_none_when_no_dps():
    # The route carries only meta (gateways): no DPs -> None (caller keeps the bulk value).
    fake = FakeHttp({"smartlife.m.device.get": {"name": "GW", "meta": {"zigChannel": 15}}})
    with patch(_HTTP, return_value=fake):
        assert await _client().async_get_device_dps("gw-1") is None


async def test_get_device_dps_coerces_keys_to_str():
    fake = FakeHttp({"smartlife.m.device.get": {"dps": {170: 50}}})
    with patch(_HTTP, return_value=fake):
        assert await _client().async_get_device_dps("dev-1") == {"170": 50}


# --- completeness of the device list (a tolerant read must say when it is partial) ---------------


def _two_homes(second_home_answer):
    def devices(_body, extra):
        return [_head_raw("dev-1")] if extra["gid"] == 1 else second_home_answer

    return FakeHttp(
        {
            "tuya.m.location.list": [{"groupId": 1, "name": "A"}, {"groupId": 2, "name": "B"}],
            "tuya.m.my.group.device.list": devices,
        }
    )


async def test_device_list_complete_when_every_home_answers_with_a_list():
    c = _client()
    assert c.device_list_complete is False and c.device_list_homes == {}  # before any read
    with patch(_HTTP, return_value=_two_homes([_head_raw("dev-2")])):
        devices = await c.async_list_devices()
    assert [d.id for d in devices] == ["dev-1", "dev-2"]
    assert c.device_list_complete is True and c.device_list_homes == {"1": 1, "2": 1}
    assert c.device_home == {"dev-1": "1", "dev-2": "2"}  # exact home of each device


@pytest.mark.parametrize("answer", [None, {"error": "x"}, "oops"])
async def test_device_list_incomplete_when_a_home_does_not_answer_with_a_list(answer):
    c = _client()
    with patch(_HTTP, return_value=_two_homes(answer)):
        devices = await c.async_list_devices()  # still tolerant: no exception, a partial result
    assert [d.id for d in devices] == ["dev-1"]
    assert c.device_list_complete is False and c.device_list_homes == {"1": 1}


async def test_device_list_empty_home_is_counted_as_zero_and_no_home_is_incomplete():
    c = _client()
    with patch(_HTTP, return_value=_two_homes([])):
        await c.async_list_devices()
    assert c.device_list_complete is True and c.device_list_homes == {"1": 1, "2": 0}
    no_home = _client()
    with patch(_HTTP, return_value=FakeHttp({"tuya.m.location.list": []})):
        assert await no_home.async_list_devices() == []
    assert no_home.device_list_complete is False and no_home.device_list_homes == {}
