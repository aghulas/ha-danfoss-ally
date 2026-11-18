# Architecture

## Principle: cloud-first, local fallback

The cloud API covers most of the control. But we have established on real hardware cases where the
cloud **lies or does not act**, which must be handled locally:

- It is the **switch to manual mode** (DP 2 `manual`) that erases the head's schedule (R4).
  `at_home` / `leaving_home` published via DP 2 are only **labels** on the cloud side: the head
  keeps the setpoint from its schedule (R5). The comfort/setback switch and the return to schedule
  therefore go through rewriting the room's schedule, not a simple cloud write of the mode. Rules
  R1–R7 and calls: `docs/interface-contract.md`.
- Preheat: writing DP 1 on the cloud side only changes the gateway cache. The real lever is the
  Zigbee attribute **0x0025** (bit 0 schedule, bit 1 preheat), reachable only through the local
  tunnel.
- `update_time` is an event-driven registration timestamp: never infer freshness from it. `online`
  is authoritative for connectivity.

So: **cloud by default, local tunnel (optional) for the operations the cloud misses**. The same
integration fetches the gateway keys, so the local fallback stays internal, asking nothing more of
the user.

## Layers

- `api/client.py` — cloud API (path 1a): session, devices, DPs, rooms, schedules.
- `api/keys.py` — fetching the gateways' localKey (replaces emulator/Frida; verified on real
  hardware).
- `api/local/tunnel.py` — Zigbee tunnel DP 198→199 (tinytuya): real schedule, attribute 0x0025, real
  attributes.
- `coordinator.py` — conservative cloud polling + overlay of the local truths.
- Platforms: `climate` (setpoint, presets), `sensor` (battery, valve, heat request, fault code),
  `binary_sensor` (online, window), `number` (holiday, bounds), `switch` (child lock, window,
  preheat).
- `mqtt_publisher.py` — MQTT publishing, modes `discovery` / `zigbee2mqtt`, source `cloud` /
  `local`.
- `diagnostics.py` — strict secret redaction.

## Tuya session and coexistence with the MCP connector (distinct deviceId)

The `danfoss_ally_cloud` integration and the MCP connector `danfoss-ally-mcp` are configured from
the **same installation material captured from the app**: `deviceId`, `sign_key` and `chKey` (see
README, "Installation secrets"). The decisive question was what the Tuya server keys a path-1a
session on.

### What keys a session: the `deviceId` request param (proven)

A session indexes on the **`deviceId` request parameter** (the 44-char value passed to `login()`
and sent on every call), **not** on the account nor on the `chKey`. Proven on 2026-11-18 (capture
session): logging in with two deviceIds that differ by a few characters — same `sign_key`, same
`chKey`, same account — yields **two independent sessions** that coexist, each readable after the
other logged in. Earlier the two clients shared one deviceId, so Tuya saw a single installation and
a single session: whichever logged in last **invalidated the other's session**, producing a loop of
re-authentications and intermittent `session_expired` / refused calls on both sides (observed in
situ: the integration, active on the Pi with the shared deviceId, forced the app to re-login nine
times in one capture session).

> The `tuya-mcp` connector (building F radiators) was never affected: it goes through the Smart Life
> sharing SDK with its own `terminal_id`.

### The fix: the integration uses its own derived deviceId

The integration gives itself a **distinct, stable `deviceId`** (same `sign_key`/`chKey`), so it
keeps its own session and no longer collides with the app or the MCP connector. No second account
and no reverse-engineering of installation enrolment are needed — any well-formed deviceId distinct
from the others is accepted, because the signature is recomputed with the unchanged `sign_key`.

- `api.derive_distinct_device_id(device_id)` rewrites the trailing characters of the captured id
  with a deterministic `sha256`-derived hex tail: **stable** across restarts (never randomised per
  request — rapid re-logins trip Tuya's `REQUEST_TOO_FREQUENTLY` anti-flood), **unique** per
  installation, and distinct from the captured value the MCP keeps using.
- `CloudClient(..., distinct_device_id=True)` applies it; the integration passes the option
  `distinct_device_id` (default **on**, `CONF_DISTINCT_DEVICE_ID`). Turning it off reproduces the
  legacy shared-session behaviour, for debugging or rollback.
- Each path-1a client (integration, MCP, app) therefore ends up with its own deviceId and its own
  session. The MCP keeps the captured `secrets.json` deviceId; the real app has its own.

The old operational workaround — keeping the integration `disabled_by: user` on the Pi so the MCP
connector could hold the single shared session — is **no longer required** once this is deployed
and confirmed on real hardware (the integration keeps its session while the MCP keeps its own).

## Security

Session tokens and localKey are secrets: never in the logs, the diagnostics or the repository.
Conservative polling defaults (security of the user's real account). Robust re-authentication (Tuya
invalidates the session when the app reconnects).

## DP codes

Source of truth: `~/dev/danfoss-app-capture/dp_schema_officiel.md`. Pitfalls captured in `const.py`
(DP 18 = upper bound, 171 = setpoint, 114 = manual, 1 = preheat, 30 = child lock, 116 = window,
162 = heat request).
