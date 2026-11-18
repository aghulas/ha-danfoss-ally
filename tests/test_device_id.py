"""Distinct-deviceId coexistence (CIBLE 1): derivation + CloudClient wiring.

The Tuya cloud keys a path-1a session on the request ``deviceId``; giving the integration a
distinct, stable deviceId (same sign_key/chKey) lets it coexist with the app and the MCP connector
without logging each other out. See docs/architecture.md. Synthetic values only (no real secret).
"""

from __future__ import annotations

from custom_components.danfoss_ally_cloud.api import derive_distinct_device_id
from custom_components.danfoss_ally_cloud.api.client import CloudClient

_CAPTURED = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2"  # synthetic, 44 chars


def test_derive_is_distinct_and_same_length():
    derived = derive_distinct_device_id(_CAPTURED)
    assert derived != _CAPTURED
    assert len(derived) == len(_CAPTURED)


def test_derive_is_stable():
    # Must NOT change across calls/restarts (rapid re-logins trip Tuya's anti-flood).
    assert derive_distinct_device_id(_CAPTURED) == derive_distinct_device_id(_CAPTURED)


def test_derive_marker_changes_result():
    # A different client marker yields a different, still-stable id.
    assert derive_distinct_device_id(_CAPTURED, "ha") != derive_distinct_device_id(_CAPTURED, "x")


def test_derive_keeps_prefix_rewrites_tail():
    derived = derive_distinct_device_id(_CAPTURED)
    assert derived[:-8] == _CAPTURED[:-8]  # only the trailing characters are rewritten
    assert derived[-8:] != _CAPTURED[-8:]
    assert all(c in "0123456789abcdef" for c in derived[-8:])  # hex tail


def test_derive_short_and_empty_are_safe():
    assert derive_distinct_device_id("") == ""
    short = derive_distinct_device_id("abcd")
    assert len(short) == 4 and short != "abcd"


def test_client_uses_derived_id_when_enabled():
    client = CloudClient(
        username="u",
        password="p",
        country_code="33",
        sign_key="k",
        device_id=_CAPTURED,
        ch_key="c",
        distinct_device_id=True,
    )
    assert client._device_id == derive_distinct_device_id(_CAPTURED)
    assert client._device_id != _CAPTURED
    # The derived id flows to the low-level HTTP client used for every request.
    assert client._build_client().device_id == derive_distinct_device_id(_CAPTURED)


def test_client_uses_verbatim_id_by_default():
    client = CloudClient(
        username="u",
        password="p",
        country_code="33",
        sign_key="k",
        device_id=_CAPTURED,
        ch_key="c",
    )
    assert client._device_id == _CAPTURED
    assert client._build_client().device_id == _CAPTURED
