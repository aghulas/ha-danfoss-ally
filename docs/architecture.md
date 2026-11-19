# Architecture

## Principle: three channels, one router

A head can be reached through **three channels**. None of them covers everything, and each has
operations it accepts without applying. The integration therefore routes **each operation to the
channel proven for it on real hardware**, and shows the entity **unavailable** when no proven
channel is up. It never falls back to a channel that merely accepts the call, and never shows an
optimistic state.

| Channel | Transport | Proven for | Known limits |
|---|---|---|---|
| **Cloud HTTP** (path 1a) | The app's signed HTTP API | Fleet read, **room-level** writes (setpoints, head settings of a grouped head, weekly schedule), holiday, room management, relay binding, unbind | `settings.change` on an **isolated** head is accepted and never applied. The bulk list route lags by minutes after a change. Mode labels and cloud DP 1 do not reach the head (below). |
| **Tuya cloud MQTT** | The app's MQTT broker, protocol 2.3 frames keyed by the gateway localKey | DP publish to an **isolated** head, applied in seconds and confirmed by the gateway's echo (child lock, 2026-11-19). Inbound DP reports are pushed and decode. | One connection per session. Proven for one DP so far; every other DP needs its own supervised write. Inbound coverage (which heads, which DPs, how often) not measured yet. |
| **Local tunnel** | LAN, Zigbee tunnel DP 198→199 through the gateway | The head's own truth: real weekly schedule, preheat (attribute 0x0025), setpoint override (DP 171), window detection, valve exercise | Slow (seconds per head, surveyed on a long period), a head may not answer for a while, needs LAN access to the gateways |

Status of the cloud-MQTT channel: validated on real hardware and on `main`, behind the option
`enable_cloud_mqtt`, **off by default**. Its write path carries the child lock only
(`api.writes.MQTT_WRITE_DPS`); a diagnostic entity reports the link state. Wire format:
`docs/cloud-mqtt-publish.md`; procedure for a first write of a new DP:
`docs/first-write-procedure.md`. With the option off, an isolated head's child lock is unavailable.

"MQTT" names two unrelated things in this project. **Tuya cloud MQTT** is a channel *to the heads*
(above). **MQTT publishing** (`mqtt_publisher.py`) sends the integration's state *to the user's own
broker*. This document always says which one it means.

### Where the cloud lies or does not act

Established on real hardware; these cases are why a single channel is not enough:

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
- Head settings of an **isolated** head (child lock, window detection): the HTTP `settings.change`
  call is accepted and never applied, whatever the addressing. The app itself writes them with a DP
  publish over Tuya cloud MQTT (contract §4.2).
- The bulk list route keeps returning the previous state for several minutes after a change, even
  when asked to refresh. The per-device route is fresher.

The same integration fetches the gateway keys, which serve both the local tunnel and the cloud-MQTT
frames, so neither channel asks anything more of the user.

## Routing

### Reads

| What | Source | Note |
|---|---|---|
| Fleet state (temperature, mode, valve, battery, window, faults) | Cloud HTTP, bulk list | Conservative polling. Lags after a change. |
| Active setpoint | Bulk list, DP 171 (`OccupiedSetpoint`) | Not the comfort setting: the setpoint of the current schedule slot or override. |
| Heating action | Bulk list, DP 3 (`work_state`) | Taken from the head, never recomputed from temperature vs setpoint. |
| A head just commanded | Cloud HTTP, per-device route, overlaid on the bulk state | Option `post_command_refresh`, bounded (see `docs/roadmap.md`, R-3). |
| Real weekly schedule, preheat state | Local tunnel survey | Unavailable per head when that head does not answer. The preheat survey runs in the background (never awaited by setup), one at a time, and publishes each head as it is read: a preheat switch is unavailable until its head has been read. |
| Connectivity | `online` | Never `update_time`. |

### Writes

| Operation | Grouped head (in a room) | Isolated head |
|---|---|---|
| Comfort / setback setpoint | Cloud HTTP: room publish, then rewrite the room schedule (R3) | No path yet; candidate for cloud MQTT |
| Weekly schedule | Cloud HTTP | Cloud HTTP |
| Child lock | Cloud HTTP: room publish (applies to **every** head of the room) | Cloud MQTT when enabled and connected; otherwise unavailable |
| Window detection | Cloud HTTP: room publish (whole room) | Local tunnel; otherwise unavailable |
| Preheat | Local tunnel (0x0025) | Local tunnel (0x0025) |
| Setpoint override until the next schedule change | Local tunnel (DP 171) | Local tunnel (DP 171) |
| Valve exercise day and time | Local tunnel | Local tunnel |
| Holiday, room management, relay binding, unbind | Cloud HTTP (holiday and unbind behind options) | — |
| Pairing | Out of scope: permit-join travels over MQTT and needs a physical action on site | — |

A setting switch states its route in its attributes (`write_path`, `write_scope`,
`room_head_count`), so the user sees when a write will touch the whole room.

### Rules for adding a route

- A channel is "proven" for an operation only after a supervised write on real hardware, read back
  from a source that does not depend on the channel written (the local tunnel when it exposes the
  value, otherwise the app and the head itself).
- One DP at a time. A new DP on the cloud-MQTT channel does not inherit the proof of another DP.
- Preheat is the known trap: cloud DP 1 over HTTP only changed the gateway cache. A DP 1 publish
  over cloud MQTT must be read back as attribute 0x0025 before it is trusted.
- After a successful write, the entity shows what the channel returns (echo or re-read), with a
  timeout and a clear error. No optimistic state.

### Open questions

- **Cloud MQTT as a read source.** If the pushed DP reports cover the whole fleet, they could
  replace the post-command per-device read and allow a longer polling period. To measure first:
  which heads and DPs are reported, and how often.
- **Account exposure.** A long-lived broker connection from a client that is not the app is more
  visible than spaced HTTP polling. The channel stays opt-in, with backoff and a clean shutdown.
- **Isolated-head setpoints.** The app publishes them over cloud MQTT; not yet attempted here.

## Layers

- `api/client.py` — cloud API (path 1a): session, devices, DPs, rooms, schedules.
- `api/keys.py` — fetching the gateways' localKey (replaces emulator/Frida; verified on real
  hardware).
- `api/local/tunnel.py` — Zigbee tunnel DP 198→199 (tinytuya): real schedule, attribute 0x0025, real
  attributes.
- `api/writes.py` — value validation and the verified-model guard-rail before any write.
- `api/mqtt_publish.py`, `api/mqtt_client.py` — Tuya cloud MQTT: frame codec and credential
  derivation; the link (one connection per entry, own session, reconnect, write confirmation).
- `switch.py` — picks the path of a setting write (`room`, `cloud_mqtt`, `local`, `none`) per head
  and setting.
- `coordinator.py` — conservative cloud polling, per-device overlay for recently commanded heads,
  overlay of the local truths.
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
