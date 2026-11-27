"""App-level "installation" material of the Danfoss Ally app (path 1a), derived instead of captured.

Reverse engineered statically from the app (see ``docs/install-material.md``). None of the three
values the Tuya mobile API requires is registered per installation:

- ``chKey`` is a pure function of public app constants:
  ``HMAC-SHA256(key=clientId, msg="<package>_<APK signing-cert SHA-256, colon hex>").hex()[8:16]``.
  The server recomputes it for the clientId (a wrong value is refused with ``ILLEGAL_CLIENT_ID``).
- ``sign_key`` is ``"<package>_<cert fingerprint>_<s1>_<s2>"``: the same string for every install
  of a given app build. ``s1``/``s2`` are the app's own secret, shipped inside the public APK.
- ``deviceId`` is 44 hex characters drawn by the client and never registered; the cloud keys the
  session on it, so each client generates its own ONCE and persists it.

The constants below belong to Danfoss Ally for Android {APP_VERSION}. A future app build may rotate
``s1``/``s2``: the config flow keeps a manual entry path for that case.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

APP_VERSION = "1.4.3"
APP_PACKAGE = "com.danfoss.ally"
APP_CLIENT_ID = "7kypwcaqcvw3uvr7u95a"
# SHA-256 fingerprint of the APK signing certificate (public: printed by `keytool -printcert`).
APP_CERT_SHA256 = (
    "80:22:ED:3D:A7:B7:13:A0:8D:37:C9:2B:DF:ED:02:4F:"
    "4D:96:FF:39:2D:DB:CD:7D:1A:D3:FD:91:E5:5E:11:52"
)
# App secret parts (t_s.bmp-derived secret, appSecret). Same for every user of this app build.
_APP_SECRET_1 = "hnvkc7huwhydtdcxdj9qttxuanutcxjw"
_APP_SECRET_2 = "nna5cyg4gqkf8frwkcte3pf4s8m4rj9w"

DEVICE_ID_LENGTH = 44


def derive_ch_key(
    client_id: str = APP_CLIENT_ID,
    package: str = APP_PACKAGE,
    cert_sha256: str = APP_CERT_SHA256,
) -> str:
    """Return the 8-hex channel key the cloud expects for this app (no capture needed)."""
    msg = f"{package}_{cert_sha256}".encode()
    return hmac.new(client_id.encode(), msg, hashlib.sha256).hexdigest()[8:16]


def app_sign_key() -> str:
    """Return the app-wide request-signing key. SECRET-like: never log it."""
    return f"{APP_PACKAGE}_{APP_CERT_SHA256}_{_APP_SECRET_1}_{_APP_SECRET_2}"


def generate_device_id() -> str:
    """Return a fresh 44-hex ``deviceId``. Generate once per client and persist it."""
    return secrets.token_hex(DEVICE_ID_LENGTH // 2)


def app_install_material() -> dict[str, str]:
    """Return ``{sign_key, device_id, ch_key}`` for a NEW client (fresh deviceId)."""
    return {
        "sign_key": app_sign_key(),
        "device_id": generate_device_id(),
        "ch_key": derive_ch_key(),
    }
