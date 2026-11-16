"""Tests du CloudClient (async) avec une doublure de TuyaHttpClient (sans réseau)."""

from unittest.mock import patch

import pytest

from custom_components.danfoss_ally_cloud.api import client as client_mod
from custom_components.danfoss_ally_cloud.api._tuya.http import TuyaApiError
from custom_components.danfoss_ally_cloud.api.client import (
    CloudAuthError,
    CloudClient,
    CloudError,
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


def _tete_raw(dev_id="dev-1"):
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
    assert homes == [{"gid": 1, "nom": "Maison"}]


async def test_async_list_devices_decode():
    fake = FakeHttp(
        {
            "tuya.m.location.list": [{"groupId": 1}],
            "tuya.m.my.group.device.list": [_tete_raw("dev-1"), _tete_raw("dev-1")],
        }
    )
    with patch(_HTTP, return_value=fake):
        devices = await _client().async_list_devices()
    assert len(devices) == 1  # dédoublonné par id
    assert devices[0].temperature == 21.0
    assert devices[0].est_tete


async def test_async_write_setting_payload():
    fake = FakeHttp({"tuya.m.custom.wkf.settings.change": {"ok": True}})
    with patch(_HTTP, return_value=fake):
        await _client().async_write_setting("dev-1", "03wvrwpv", {"16": 210})
    api, _, body, _ = fake.calls[-1]
    assert api == "tuya.m.custom.wkf.settings.change"
    assert body["devId"] == "dev-1" and '"16":210' in body["settings"]


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


async def test_async_login_refus():
    with patch(_LOGIN, return_value={"sid": None, "ecode": None}), pytest.raises(CloudAuthError):
        await _client(sid=None, ecode=None).async_login()


async def test_relogin_sur_session_expiree():
    fake = FakeHttp(
        {"tuya.m.location.list": [{"groupId": 7, "name": "M"}]},
        raise_once=TuyaApiError("APP_SESSION_EXPIRED", "expirée", {}),
    )
    with (
        patch(_HTTP, return_value=fake),
        patch(_LOGIN, return_value={"sid": "S3", "ecode": "E3"}) as login_mock,
    ):
        homes = await _client().async_get_homes()
    assert homes == [{"gid": 7, "nom": "M"}]
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
