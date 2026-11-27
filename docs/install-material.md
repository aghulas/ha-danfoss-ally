# Installation material (path 1a): derived, not captured

The Tuya mobile API behind the Danfoss Ally app requires three values on every request besides the
session (`sid`/`ecode`): `sign_key`, `deviceId` and `chKey`. Until 2.0.9 the user had to capture
them once from the app's traffic (mitmproxy / frida). They are now **derived by the library**
(`api/_tuya/install.py`), so onboarding only asks for **email, password and country**.

## What the three values really are

Established by static analysis of the app (decompiled SDK + native `libthing_security.so`), not by
guesswork:

| Value | Nature | How it is obtained |
|---|---|---|
| `chKey` | App-wide constant | `HMAC-SHA256(key=clientId, msg="<package>_<SHA-256 fingerprint of the APK signing certificate, upper-case colon hex>")`, hex characters 8 to 16. The server recomputes it for the `clientId`; a wrong value is refused with `ILLEGAL_CLIENT_ID`. |
| `sign_key` | App-wide constant | `"<package>_<certificate fingerprint>_<s1>_<s2>"`. `s1` and `s2` are the app's own secret, shipped inside the public APK; the same for every user of a given app build. |
| `deviceId` | Client-generated | 44 hex characters drawn by the client and never registered. The cloud keys the session on it, so each client generates its own once and keeps it. |

Nothing is registered server-side at first launch: the earlier belief that `chKey` was a
per-installation key came from the `ILLEGAL_CLIENT_ID` refusal of random values.

## Evidence

- Offline: the derived `chKey` and the rebuilt `sign_key` are byte-identical to the values captured
  from a real installation (checked in the private reverse-engineering workspace; the test suite
  here only uses synthetic vectors plus shape checks).
- Real cloud, 2026-11-27, pre-login request (`thing.m.user.username.token.get`, no password):
  a never-seen `deviceId` + the derived `chKey` → accepted, response decrypted; same request with a
  wrong `chKey` → `ILLEGAL_CLIENT_ID`.
- A random 44-hex `deviceId` with a full login was already in production use by `danfoss2mqtt`
  (`ensure_device_id`).
- **Not yet recorded here**: a full email/password login through the new config-flow path on a real
  account. Record it in `docs/validation/` when done.

## Behaviour

- **Config flow** (`Danfoss Ally Cloud — account`): email, password, country. The integration builds
  the material (`app_install_material()`), validates it with a real login and stores it in the
  entry (`sign_key`, `device_id`, `ch_key`), exactly where captured values used to live. Existing
  entries are untouched.
- **Manual fallback**: tick *Enter the installation secrets manually (advanced)* to get the former
  three-field step. Use it only if sign-in is refused although the credentials are right.
  Reauth and reconfigure still accept replacement values.
- **`danfoss2mqtt`**: `sign_key` / `ch_key` default to the derived values when a username and
  password are configured; explicit options or `DANFOSS_SIGN_KEY` / `DANFOSS_CH_KEY` still win.
- **Coexistence**: every client has its own `deviceId`, so the integration, the Danfoss app and the
  MCP connector keep separate sessions (`docs/architecture.md`).

## Limits

- The constants belong to **Danfoss Ally for Android 1.4.3** (`APP_VERSION`). Danfoss can rotate
  `s1`/`s2` with a new build and retire the old ones server-side; the symptom would be a refused
  sign-in with correct credentials. Remedy: update the constants in `api/_tuya/install.py`, or use
  the manual fallback meanwhile.
- `s1`/`s2` are Danfoss's application secret, not a user secret. They are embedded on purpose
  (owner decision, 2026-11-27); the user's password, `sid`/`ecode` and gateway keys remain secrets
  that are never logged. `sign_key` is still redacted from diagnostics.
