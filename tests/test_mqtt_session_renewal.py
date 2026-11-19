"""What the cloud refresh asked by a refused cloud-MQTT connection actually does.

``CloudMqttLink.on_auth_refused`` makes the integration request one coordinator refresh. These
tests run the REAL ``CloudClient`` and ``DanfossCoordinator`` (HTTP layer doubled, synthetic data)
to establish the two outcomes:

- the session was invalidated elsewhere: the client signs in again by itself inside the request,
  the refresh succeeds, and the link's next credentials carry the renewed session;
- the sign-in itself is refused (password or installation secrets no longer valid): the refresh
  raises ``ConfigEntryAuthFailed``. Nothing can renew the session then, and the link is right to
  stop after its refusals.
"""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.danfoss_ally_cloud.api._tuya.http import TuyaApiError
from custom_components.danfoss_ally_cloud.api.client import CloudClient
from custom_components.danfoss_ally_cloud.api.mqtt_client import build_credentials
from custom_components.danfoss_ally_cloud.coordinator import DanfossCoordinator

from .test_client_async import _HTTP, _LOGIN, FakeHttp, _head_raw

_SIGN_KEY = "com.danfoss.ally_" + "aa:" * 15 + "aa_" + "b" * 32 + "_" + "c" * 32


def _client():
    return CloudClient("u", "p", "33", _SIGN_KEY, "devid-synth", "ck", sid="OLD", ecode="OLDEC")


def _creds(client):
    """Credentials as ``__init__._fresh_creds`` builds them: from the client's current session."""
    return build_credentials(
        region="eu",
        sign_key=_SIGN_KEY,
        sid=client.session["sid"] or "",
        ecode=client.session["ecode"] or "",
        uid="uid-synth",
        partner_identity="p100",
        device_id="devid-synth",
        ch_key="ck",
    )


def _http(raise_once):
    return FakeHttp(
        {
            "tuya.m.location.list": [{"groupId": 1, "name": "Maison"}],
            "tuya.m.my.group.device.list": [_head_raw()],
        },
        raise_once=raise_once,
    )


async def test_invalidated_session_is_renewed_by_the_refresh_itself(hass: HomeAssistant):
    client = _client()
    before = _creds(client)
    coordinator = DanfossCoordinator(hass, client, 90)
    fake = _http(TuyaApiError("USER_SESSION_INVALID", "session invalid", {}))
    with (
        patch(_HTTP, return_value=fake),
        patch(_LOGIN, return_value={"sid": "NEW", "ecode": "NEWEC"}) as login,
        patch.object(coordinator, "_ensure_topology", AsyncMock()),
    ):
        data = await coordinator._async_update_data()  # no ConfigEntryAuthFailed
    assert "dev-1" in data
    login.assert_called_once()  # one sign-in, inside the request
    assert client.session == {"sid": "NEW", "ecode": "NEWEC"}
    after = _creds(client)
    # The link's next reconnection presents the renewed session.
    assert after.username != before.username and after.password != before.password
    assert after.client_id == before.client_id  # same dedicated client id


async def test_refused_sign_in_raises_auth_failed_and_nothing_is_renewed(hass: HomeAssistant):
    client = _client()
    coordinator = DanfossCoordinator(hass, client, 90)
    fake = _http(TuyaApiError("USER_SESSION_INVALID", "session invalid", {}))
    with (
        patch(_HTTP, return_value=fake),
        patch(_LOGIN, side_effect=TuyaApiError("USER_PASSWD_WRONG", "wrong password", {})),
        patch.object(coordinator, "_ensure_topology", AsyncMock()),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await coordinator._async_update_data()
    assert client.session == {"sid": "OLD", "ecode": "OLDEC"}  # unchanged: the link stays refused
