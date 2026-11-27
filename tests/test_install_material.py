"""Derived installation material (api/_tuya/install.py). Synthetic vectors only."""

import hashlib
import hmac
import re

from custom_components.danfoss_ally_cloud.api import (
    app_install_material,
    app_sign_key,
    derive_ch_key,
    generate_device_id,
)
from custom_components.danfoss_ally_cloud.api._tuya import install


def test_derive_ch_key_formula_synthetic():
    """chKey = HMAC-SHA256(clientId, "<package>_<cert>").hex()[8:16], on synthetic inputs."""
    cert = ":".join(["AB"] * 32)
    expected = hmac.new(b"client", f"com.example.app_{cert}".encode(), hashlib.sha256).hexdigest()
    assert derive_ch_key("client", "com.example.app", cert) == expected[8:16]


def test_derive_ch_key_default_is_stable_8_hex():
    assert re.fullmatch(r"[0-9a-f]{8}", derive_ch_key())
    assert derive_ch_key() == derive_ch_key()


def test_app_sign_key_shape():
    package, cert, s1, s2 = app_sign_key().split("_")
    assert package == install.APP_PACKAGE == "com.danfoss.ally"
    assert cert == install.APP_CERT_SHA256
    assert re.fullmatch(r"([0-9A-F]{2}:){31}[0-9A-F]{2}", cert)
    assert len(s1) == 32 and len(s2) == 32


def test_generate_device_id_fresh_44_hex():
    a, b = generate_device_id(), generate_device_id()
    assert re.fullmatch(r"[0-9a-f]{44}", a)
    assert a != b


def test_app_install_material():
    m = app_install_material()
    assert m["sign_key"] == app_sign_key()
    assert m["ch_key"] == derive_ch_key()
    assert re.fullmatch(r"[0-9a-f]{44}", m["device_id"])
