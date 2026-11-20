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
| **Tuya cloud MQTT** | The app's MQTT broker, protocol 2.3 frames keyed by the gateway localKey | DP publish to an **isolated** head, applied in under a second and confirmed by the gateway's echo (child lock, window detection, setpoint bounds, pause setpoint, 2026-11-19; comfort and setback setpoints, 2026-11-19/20). Inbound DP reports are pushed and decode. | One connection per session. Proven DP by DP (eight so far); every other DP needs its own supervised write. Inbound coverage (which heads, which DPs, how often) not measured yet. |
| **Local tunnel** | LAN, Zigbee tunnel DP 198→199 through the gateway | The head's own truth: real weekly schedule, preheat (attribute 0x0025), setpoint override (DP 171), window detection, valve exercise | Slow (seconds per head, surveyed on a long period), a head may not answer for a while, needs LAN access to the gateways |

Status of the cloud-MQTT channel: validated on real hardware and on `main`, behind the option
`enable_cloud_mqtt`, **off by default**. Its write path carries the child lock, window detection,
the setpoint bounds and the pause, comfort and setback setpoints of an isolated head
(`api.writes.MQTT_WRITE_DPS`, each proven by its own supervised write, on 2026-11-19 and
2026-11-20); preheat (DP 1, confirmed by the tunnel only) is implemented as a candidate, closed
until its supervised write; a diagnostic entity reports the link state. Wire format: `docs/cloud-mqtt-publish.md`; procedure for a first
write of a new DP: `docs/first-write-procedure.md`. With the option off, an isolated head's child
lock, bounds and setpoints have no path (the switch is unavailable, the numbers are absent, and
the head's thermostat is read-only).

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
  tunnel. **That write alone is not durable** (2026-11-20): four heads whose bit differed from the
  cloud's DP 1 were back at the cloud's value within one night. Finding and change plan:
  `docs/preheat-tunnel-durability.md`.
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
| Comfort / setback setpoint | Cloud HTTP: room publish, then rewrite the room schedule (R3) | Cloud MQTT when enabled and connected (proven 2026-11-19/20 on a head following its schedule), followed by the settings block over HTTP, as the app does; otherwise no `number` entity and a read-only thermostat. Two entry points, one write: the head's `number` entities (comfort or setback, chosen by the entity) and the head's thermostat (the setting of the mode the cloud reports, below). The comfort write is refused when the head is not in a schedule mode. The head rewrites its own schedule transitions: no schedule rewrite |
| Pause setpoint | No path | Cloud MQTT when enabled and connected (proven 2026-11-19, read back in the app and the cloud only); otherwise no entity |
| Weekly schedule | Cloud HTTP | Cloud HTTP, **only for a head following its schedule** (proven 2026-11-17); refused otherwise. Back to schedule: no proven route, refused (`docs/isolated-head-schedule-writes.md`) |
| Child lock | Cloud HTTP: room publish (applies to **every** head of the room) | Cloud MQTT when enabled and connected; otherwise unavailable |
| Window detection | Cloud HTTP: room publish (whole room) | Local tunnel when the head answers locally; otherwise cloud MQTT when enabled and connected (proven 2026-11-19); otherwise unavailable |
| Setpoint bounds (upper, lower) | No path yet | Cloud MQTT when enabled and connected (proven 2026-11-19); otherwise no entity |
| Preheat | Local tunnel (0x0025) | Local tunnel (0x0025). Cloud MQTT (DP 1) is a **candidate**, closed: on the trial head only, written over cloud MQTT and confirmed by the tunnel read alone; the state always comes from the tunnel |
| Viewing direction (DP 101), orientation (DP 133) | No path | **Candidates**, closed: on the trial head only, cloud MQTT; orientation confirmed by the tunnel flag 0x4014 and shown from it, viewing direction confirmed by the per-device route (`docs/viewing-orientation-trial.md`); no entity otherwise |
| Radiator covered (0x4016), setpoint offset (0x404B), regulation speed (0x4020), valve exercise day / time (0x4010 / 0x4011) | **Not proven**, closed: local tunnel on the trial head only (grouped or isolated) | Same |
| Setpoint override until the next schedule change | Local tunnel (DP 171) | Local tunnel (DP 171) |
| Valve exercise day and time | Local tunnel | Local tunnel |
| Holiday, room management, relay binding, unbind | Cloud HTTP (holiday and unbind behind options) | — |
| Pairing | Out of scope: permit-join travels over MQTT and needs a physical action on site | — |

A setting switch states its route in its attributes (`write_path`, `write_scope`,
`room_head_count`), so the user sees when a write will touch the whole room.

**Thermostat of an isolated head.** Read-only while `enable_cloud_mqtt` is off: a setpoint change
is refused with a clear error. With the option on and the link connected, in the modes `at_home`
and `leaving_home`, a setpoint change writes over cloud MQTT the **setting of the mode the cloud
reports**: comfort (DP 118 + 16) for `at_home`, setback (DP 119) for `leaving_home`, then the
settings block over HTTP; the value is checked against the head's own bounds first. This is the
write of the head's setpoint numbers, with nothing added. The entity says what a write would do in
its attributes: `write_path` (`cloud_mqtt` or `none`) and, when a write is possible,
`write_setting` (`comfort` or `setback`).

The reported mode is a label (R5): it does not say whether the head is in a comfort slot of its
schedule. A comfort write made outside a comfort slot still changes the comfort setting, and its
DP 16 sets the head's current setpoint at once: the head asks for heat for 1 to 5 minutes, then
goes back to its schedule's value by itself (real hardware, 2026-11-19). The thermostat's target
temperature stays the **active** setpoint (DP 171), so after such a write it shows the schedule's
value again, not the value written; the comfort setting is in `setpoints.comfort`.

Order for an isolated head's setting: (1) a DP under **supervised trial** on cloud MQTT goes through
cloud MQTT, so the trial exercises the channel it is meant to prove and the tunnel stays free to
read the result back; (2) the **local tunnel** when it has a proven write for that setting and the
head answers locally — it reaches the head directly, with no cloud in between; (3) **cloud MQTT**
for a DP proven on it; (4) otherwise unavailable.

### Rules for adding a route

- A channel is "proven" for an operation only after a supervised write on real hardware, read back
  from a source that does not depend on the channel written (the local tunnel when it exposes the
  value, otherwise the app and the head itself).
- One DP at a time. A new DP on the cloud-MQTT channel does not inherit the proof of another DP.
  In code: a DP is first a **candidate** (`api.writes.MQTT_CANDIDATE_DPS`), closed unless listed in
  the option `cloud_mqtt_supervised_dps` for its supervised write, and then only on the one head
  designated in `cloud_mqtt_supervised_head`; it becomes **proven** (`MQTT_WRITE_DPS`) in a change
  of its own (`docs/first-write-procedure.md`).
- Preheat is the known trap: cloud DP 1 over HTTP only changed the gateway cache. A DP 1 publish
  over cloud MQTT must be read back as attribute 0x0025 before it is trusted. Implemented as a
  closed candidate with that rule built in (`api.writes.MQTT_TUNNEL_CONFIRMED_DPS`: the echo and
  the cloud read are refused as confirmation). Supervised write of 2026-11-20: **not passed** —
  the publish changed the cloud's DP 1 and not the head, although the app's own toggle does reach
  it. The tunnel stays the only preheat route: `docs/cloud-mqtt-preheat-proposal.md`. It is an
  incomplete one: the head takes the value, then goes back overnight to the value the cloud holds
  (`docs/preheat-tunnel-durability.md`).
- Viewing direction (DP 101) and orientation (DP 133), batch C of the Zigbee2MQTT alignment, are
  closed candidates with their own confirmation and never the echo: DP 133 is in
  `MQTT_TUNNEL_CONFIRMED_DPS` (the head's flag 0x4014 read through the tunnel); DP 101, which the
  tunnel cannot read, is in `MQTT_CLOUD_CONFIRMED_DPS` (the per-device route, the head's display
  being the trial's proof). Their entities exist only while their trial is armed
  (`docs/viewing-orientation-trial.md`).
- Radiator covered, setpoint offset, regulation speed and valve exercise (batch C2) are written
  through the **local tunnel**, as Zigbee2MQTT writes the same attributes. Each is closed unless
  ticked in `local_supervised_settings`, and then only on the one head of
  `local_supervised_head` (`local_write.py`). The head is read back through the tunnel after each
  write; that read is the head's own answer but uses the channel written, so the trial adds the
  app and the head as independent sources (`docs/tunnel-settings-trial.md`).
- After a successful write, the entity shows what the channel returns (echo or re-read), with a
  timeout and a clear error. No optimistic state.

### Open questions

- **Cloud MQTT as a read source.** If the pushed DP reports cover the whole fleet, they could
  replace the post-command per-device read and allow a longer polling period. To measure first:
  which heads and DPs are reported, and how often. The listen-only option `cloud_mqtt_probe` does
  that measure (`docs/cloud-mqtt-coverage.md`); its 24 h run on a real install is pending.
- **Account exposure.** A long-lived broker connection from a client that is not the app is more
  visible than spaced HTTP polling. The channel stays opt-in, with backoff and a clean shutdown.
- **Isolated-head comfort and setback setpoints on a head in manual mode.** Proven on a head
  following its schedule (2026-11-19/20): the head rewrites its own schedule transitions, and the
  accompanying DP 16 sets the current setpoint at once before the head returns to its schedule
  within five minutes. Not observed: the same write on a head in manual mode or without a
  schedule, where nothing is known to bring the current setpoint back. Until it is, the comfort
  write is refused unless the cloud reports the head in a schedule mode.
- **Back to schedule for an isolated head in manual mode.** Observed on 2026-11-19: a schedule
  write and `restore_schedule` over HTTP, both accepted, had not reached such a head after five
  minutes; an effect appeared more than ten minutes later and left the head in manual mode, at
  the cloud's comfort value. What the app does to bring an isolated head back to its schedule is
  not established; do not rely on the HTTP path for it. Since then both are refused before any
  send: a schedule write to an isolated head that is not following a schedule, and
  `restore_schedule` on any isolated head (`docs/isolated-head-schedule-writes.md`, with the
  timeline and the trials that would settle it).
- **Thermostat comfort write outside a comfort slot.** The isolated head's thermostat picks
  comfort or setback from the reported mode (a label, R5). Whether a comfort write should be
  refused when the head's active setpoint shows it is not in a comfort slot is not decided; today
  it is sent, and the entity states which setting it changes (`write_setting`).

## Entities follow the topology at runtime

Rooms and memberships change while Home Assistant runs (room management actions, or the Danfoss
app). The `climate` and `number` platforms listen to the coordinator and adjust their entities on
each update, with no reload of the entry:

| Change seen in the topology | Effect |
|---|---|
| A room appears | Its thermostat and its comfort / setback numbers are created (numbers: verified products only) |
| A head leaves its room (isolated) | It gets its own thermostat; with `enable_cloud_mqtt` on and a link, its bounds and setpoint numbers |
| A head joins a room | Its own thermostat and its isolated-head numbers are removed from the registry |
| A room is gone | Its thermostat and numbers are removed from the registry, **on positive evidence only** |

Adding is safe on any poll. Removing a room's entities deletes the entity ids, names and areas the
user set, so it needs proof: `DanfossCoordinator.room_retired` is true only when the last device
list was **complete** (every home answered), the last topology read was **complete** (every home
that lists rooms also gave their members), and that topology no longer lists the room. A room that
merely drops out of `coordinator.rooms` (one home did not answer, so none of its heads is in the
list; or a degraded topology read) keeps its entities, unavailable, and they come back by
themselves at the next complete read. A head's own thermostat is removed when the topology places
the head in a room, which is positive by nature.

## Layers

- `api/client.py` — cloud API (path 1a): session, devices, DPs, rooms, schedules.
- `api/keys.py` — fetching the gateways' localKey (replaces emulator/Frida; verified on real
  hardware).
- `api/local/tunnel.py` — Zigbee tunnel DP 198→199 (tinytuya): real schedule, attribute 0x0025, real
  attributes.
- `api/writes.py` — value validation and the verified-model guard-rail before any write.
- `api/mqtt_publish.py`, `api/mqtt_client.py` — Tuya cloud MQTT: frame codec and credential
  derivation; the link (one connection per entry, own session, reconnect, write confirmation,
  optional listen-only mode).
- `mqtt_coverage.py` — listen-only measure of what the cloud-MQTT broker pushes (aggregates per
  head and per DP, served by the diagnostics).
- `switch.py` — picks the path of a setting write (`room`, `cloud_mqtt`, `local`, `none`) per head
  and setting.
- `mqtt_write.py` — the one cloud-MQTT write routine shared by the entities: validate, publish,
  confirm (echo, else per-device read), clear error otherwise.
- `coordinator.py` — conservative cloud polling, per-device overlay for recently commanded heads,
  overlay of the local truths; room topology and `room_retired` (above).
- Platforms: `climate` (room thermostat; isolated head's thermostat, written over cloud MQTT when
  enabled), `sensor` (battery, valve, heat request, fault code),
  `binary_sensor` (online, window), `number` (room setpoints; an isolated head's bounds and
  setpoints over cloud MQTT), `switch` (child lock, window, preheat).
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
