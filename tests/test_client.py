"""Cloud client tests (pure logic, no network)."""

from custom_components.danfoss_ally_cloud.api import client
from custom_components.danfoss_ally_cloud.api._tuya.http import TuyaApiError


def test_is_session_error_par_code():
    assert client._is_session_error(TuyaApiError("APP_SESSION_EXPIRED", "x", {}))
    assert client._is_session_error(TuyaApiError("SIGN_INVALID", "x", {}))


def test_is_session_error_par_message():
    assert client._is_session_error(TuyaApiError("SOME_CODE", "session is invalid", {}))


def test_is_session_error_faux_positif():
    assert not client._is_session_error(TuyaApiError("PERMISSION_DENIED", "no access", {}))


def test_region_endpoint():
    c = client.CloudClient("u", "p", "33", "sk", "dev", "chk", region="us", sid="s", ecode="e")
    assert "tuyaus" in c._endpoint
    assert c.session == {"sid": "s", "ecode": "e"}


def test_region_default_eu():
    c = client.CloudClient("u", "p", "33", "sk", "dev", "chk", region="zz")
    assert "tuyaeu" in c._endpoint
