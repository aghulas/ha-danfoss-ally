"""Tests de la pile HTTP Tuya bas niveau (requests moqué, aucun réseau)."""

import json
from unittest.mock import patch

import pytest
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA

from custom_components.danfoss_ally_cloud.api._tuya import http as http_mod
from custom_components.danfoss_ally_cloud.api._tuya.http import (
    TuyaApiError,
    TuyaHttpClient,
    encrypt_password,
    login,
    md5_as_base64,
)


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _client():
    return TuyaHttpClient("sk", "sid", "ecode", "ck", "dev")


def test_request_result_dict():
    c = _client()
    with patch.object(c.http, "post", return_value=FakeResp({"result": {"a": 1}})) as post:
        out = c.request("tuya.m.x", "1.0", {"k": 1}, extra_params={"gid": 5})
    assert out == {"a": 1}
    # le corps est sérialisé en form-urlencoded, gid passé en paramètre non signé
    _, kw = post.call_args
    assert "data" in kw and kw["timeout"] == 20.0


def test_request_raw_renvoie_enveloppe():
    c = _client()
    env = {"result": {"a": 1}}
    with patch.object(c.http, "post", return_value=FakeResp(env)):
        assert c.request("api", "1.0", raw=True) == env


def test_request_erreur_enveloppe():
    c = _client()
    with (
        patch.object(c.http, "post", return_value=FakeResp({"errorCode": "X", "errorMsg": "boom"})),
        pytest.raises(TuyaApiError),
    ):
        c.request("api", "1.0")


def test_request_resultat_chiffre():
    c = _client()
    env = {"result": "CHIFFRE"}
    with (
        patch.object(c.http, "post", return_value=FakeResp(env)),
        patch.object(http_mod, "decrypt_response", return_value=json.dumps({"result": {"ok": 1}})),
    ):
        assert c.request("api", "1.0") == {"ok": 1}


def test_request_erreur_interne_chiffree():
    c = _client()
    env = {"result": "CHIFFRE"}
    with (
        patch.object(c.http, "post", return_value=FakeResp(env)),
        patch.object(http_mod, "decrypt_response", return_value=json.dumps({"errorCode": "E"})),
        pytest.raises(TuyaApiError),
    ):
        c.request("api", "1.0")


def test_close():
    c = _client()
    c.close()  # ne lève pas


def test_md5_as_base64_est_hex():
    h = md5_as_base64("abc")
    assert len(h) == 32 and all(ch in "0123456789abcdef" for ch in h)


def test_encrypt_password_dechiffrable():
    key = RSA.generate(1024)
    chiffre = encrypt_password("secret", str(key.n), str(key.e))
    clair = PKCS1_v1_5.new(key).decrypt(bytes.fromhex(chiffre), None)
    assert clair == md5_as_base64("secret").encode("utf-8")


def test_login_ok():
    key = RSA.generate(1024)
    reponses = iter(
        [
            FakeResp({"result": {"token": "T", "publicKey": str(key.n), "exponent": str(key.e)}}),
            FakeResp({"result": {"sid": "S", "ecode": "E", "uid": "U"}}),
        ]
    )
    with patch("requests.Session.post", side_effect=lambda *a, **k: next(reponses)):
        res = login("e@x", "pw", "33", "sk", "dev", "ck")
    assert res == {"sid": "S", "ecode": "E", "chKey": "ck", "deviceId": "dev", "uid": "U"}


def test_login_erreur():
    with (
        patch("requests.Session.post", return_value=FakeResp({"errorCode": "BAD"})),
        pytest.raises(TuyaApiError),
    ):
        login("e@x", "pw", "33", "sk", "dev", "ck")
