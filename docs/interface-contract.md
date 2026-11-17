# Interface contract — schedules, modes and rooms

This document fixes what the backend (Python, `custom_components/danfoss_ally_cloud/`) provides and
what the frontend (`frontend/`) consumes. **It is the only file shared between the two efforts**: any
change on one side that changes a shape described here goes first through a change to this contract.

It is based on real trials of 2026-11-16 (the app's API, re-read in the heads via the local tunnel).
The rules in section 2 are not preferences: each corresponds to an observed behaviour.

## 1. Vocabulary and identifiers

| Term | Cloud side | Identifier | In Home Assistant |
|---|---|---|---|
| Home | account "home" | `gid` (integer) | logical grouping, no device |
| Gateway | device, `category` `wg2` | `devId` | device (hub) |
| Room | schedule-group (type 5) | `group_id` (integer); product `pid` | **"room" device** (to create), identifier `(DOMAIN, "room_<group_id>")` |
| Head | device, `category` `wk` | `devId`; `meshId` = gateway; `nodeId` = Zigbee address | existing device, `via_device` = gateway |
| Isolated head | head with no room | `devId` | same; schedules itself (`resType` 1) |

A **grouped** head is scheduled and set only through its room. A room has at least two heads.

Head-to-room membership: `m.life.my.group.device.relation.list` v3.2, body `{gid}` → key `"5"`:
list of groups `{id, children: {"6": [{id: devId}, …]}}`. Room list:
`m.life.my.group.device.group.list` v4.3, body `{gid}` → `[{id, name, deviceNum, productId}]`.

## 2. Rules established on real hardware (to apply server-side, not only on screen)

**R1 — At most six transitions per day in a head.** Count of the transitions a day needs:
- each slot counts its start, unless it is `00:00`;
- each slot counts its end, unless another slot starts at that time (touching slots);
- if no slot starts at `00:00`, the head adds a "setback" transition at `00:00` **if it has room
  left** (at 6, it drops it and keeps, until the first slot, the previous evening's setpoint).

A day is **valid if this count is ≤ 6** (at most three separate slots). Beyond that, **the cloud
accepts and displays the schedule, but the head loses all the day's transitions**. The backend
refuses before any send.

> **Same hardware limit on both sides.** "R1 at the cloud level: ≤ 6 transitions/day, edge rule at
> `00:00`" (this document) and the local-tunnel wording of the MCP connector ("1 to 6 transitions,
> the 1st at `00:00`") describe **the same head constraint** (the Danfoss firmware keeps only six
> transitions per day, the first placed at midnight), seen respectively through the cloud API and
> through the schedule re-read in the head via the tunnel. They must stay consistent: a fix on one
> side (count, edge rule, maximum) must be carried to the other, not treated as a divergence to
> arbitrate.

**R2 — Writing one day pushes the whole week** to the heads, with the comfort / setback setpoints of
the moment.

**R3 — The schedule carries its own setpoints.** After any change to a room's comfort or setback
setpoint, the backend rewrites the schedule (one day is enough, R2). Without it the current setpoint
changes, but the transitions keep the old value and the head reverts to it at the next schedule
change.

**R4 — Manual mode erases the head's schedule.** The return to schedule consists of rewriting the
room's schedule (that is what acts on the head), then publishing mode `at_home` (so the cloud no
longer shows "manual"). Publishing `at_home` alone only changes the display.

**R5 — `at_home`, `leaving_home` and `holiday` published via DP 2 are only labels on the cloud
side.** The head keeps its schedule's setpoint. No "comfort / setback now" or "holiday" preset must
be wired on this call. The app's real call for these functions is not yet known.

**R6 — A head's real state is read from DP 172** (`operation_mode`, mirror of Zigbee attribute
0x0025): bit 0 = schedule active, bit 1 = preheat; 0 = manual. DP 2 (displayed mode) can say
"comfort" on a head left in manual.

**R7 — Delays.** Schedule, manual mode and room setpoint reach the heads in under 5 minutes
(measured on a lightly loaded gateway); room settings in 5 to 10 minutes. A write is therefore
"sent" immediately and "applied" later, or never (head offline).

## 3. Data models

All times are `HH:MM` strings over 24 h, from `00:00` to `23:59`. Days are named `mon`, `tue`,
`wed`, `thu`, `fri`, `sat`, `sun`. Temperatures are in °C, 0.5 step.

### 3.1 Target

```json
{ "type": "room", "id": "13000000" }
```
`type`: `room` (`id` = `group_id` as a string) or `device` (isolated head, `id` = `devId`).

### 3.2 Schedule (`Schedule`)

```json
{
  "target": { "type": "room", "id": "13000000" },
  "name": "Room 1",
  "comfort": 21.0,
  "setback": 14.0,
  "days": {
    "mon": [{ "start": "08:30", "end": "17:30" }],
    "tue": [{ "start": "08:30", "end": "17:30" }],
    "wed": [],
    "thu": [{ "start": "08:30", "end": "17:30" }],
    "fri": [{ "start": "08:30", "end": "17:30" }],
    "sat": [],
    "sun": []
  },
  "max_transitions_per_day": 6,
  "source": "cloud",
  "read_at": "2026-11-16T15:36:00+01:00"
}
```
- `days` always contains all seven days; an empty list = a day entirely in setback.
- Slots sorted, non-overlapping, `start < end`. Two slots may touch.
- `comfort` / `setback`: the room's setpoints (DP 118 and DP 119), read-only here; they are written
  via the `number` entities (section 5).
- `source`: `cloud` today; `local` and `zigbee` are reserved.

### 3.3 Head state (`HeadState`)

```json
{
  "device_id": "<devId>",
  "name": "Room 1 #2",
  "room_id": "13000000",
  "online": true,
  "mode_displayed": "at_home",
  "schedule_active": true,
  "preheat": false,
  "mounting": false,
  "inconsistent": false
}
```
- `schedule_active`, `preheat`: decoded from DP 172 (R6); `null` if the DP is absent.
- `inconsistent`: `mode_displayed` is `at_home` or `leaving_home` while `schedule_active` is `false`
  (head left in manual without the app knowing).
- `mounting`: DP 149 (head in mounting mode, not regulating).

### 3.4 Room (`Room`)

```json
{
  "id": "13000000",
  "name": "Room 1",
  "home": "Home",
  "product_id": "03wvrwpv",
  "heads": [ /* HeadState */ ],
  "comfort": 21.0,
  "setback": 14.0
}
```

### 3.5 Write tracking (`WriteJob`)

```json
{
  "job_id": "…",
  "kind": "set_schedule",
  "target": { "type": "room", "id": "13000000" },
  "status": "sent",
  "created_at": "…",
  "heads": [
    { "device_id": "<devId>", "status": "pending", "detail": null }
  ]
}
```
- Job `status`: `sent` (the cloud accepted) → `applied` (all heads verified) | `partial` |
  `unverified` (no verification possible) | `failed` (the cloud refused).
- Per-head `status`: `pending` → `applied` | `mismatch` | `unreachable` | `unverified`.
- Verification: for the mode, DP 172 on the next refresh; for the schedule, reading from the head
  via the local tunnel **if the local fallback is enabled**, otherwise `unverified`.
- Jobs are kept in memory (the last 50), not persisted.

## 4. Cloud calls (`api/` layer)

All go through `CloudClient._request(api, version, body)`. Shapes observed on the app and replayed
on real hardware.

### 4.1 Weekly schedule

Common body: `{"devId": R, "gwId": G, "pid": <product id>, "resId": R, "resType": T}`.

| Target | `R` (= `devId`/`resId`) | `G` (= `gwId`) | `T` (= `resType`) |
|---|---|---|---|
| Room | `group_id` (string) | `group_id` (= `R`) | 2 |
| Isolated head | `devId` | `meshId` (the head's gateway `devId`) | 1 |

For an isolated head, `gwId` is the **`meshId`** (the gateway), **not** the head's `devId`: this is
the shape observed on the app and **replayed on real hardware**, implemented by `_resolve_target` in
`api/client.py` (`gw_id = dev.mesh_id or devId`, falling back to the `devId` if the `meshId` is
missing). The code remains the reference; this table was aligned on it on 2026-11-17 (an earlier
version of the contract said `gwId = devId` for an isolated head). Caveat: the "isolated head" path
was observed on the app but not yet exercised end-to-end on real hardware (the trials of 2026-11-16
were on rooms) — to confirm in a trial on an ungrouped head.

| Operation | API | Version | Body (in addition to the common body) |
|---|---|---|---|
| Read | `tuya.m.custom.wkf.week.timer.list` | 1.0 | — |
| Clear a day | `tuya.m.custom.wkf.week.timer.delete` | 1.0 | `loops` |
| Create a day | `tuya.m.custom.wkf.week.timer.create` | 1.0 | `loops`, `periods` |

- `loops`: 7-character mask, **Sunday first**: `1000000` = Sunday, `0100000` = Monday, …
  `0000001` = Saturday. One day per call.
- `periods`: a **JSON string** of a list `[{"startTime": "08:30", "endTime": "17:30"}]`.
- Read response: a list (sometimes under the `data` key) of
  `{"loops": "0100000", "loopData": [{"startTime": 510, "endTime": 1050, "mode": "at_home"}]}` — times
  in **minutes since midnight**, `mode` `at_home` = comfort slot. A day absent from the response is
  empty.
- Writing a day = `delete` then, if slots remain, `create`. An empty day = `delete` only.

### 4.2 Room DPs

`s.m.dev.group.dp.publish` v1.0, body `{"dps": "<JSON string>", "groupId": <integer>}`.

| Use | `dps` | Real effect |
|---|---|---|
| Comfort setpoint | `{"118": 210}` (tenths of °C) | applied; then R3 |
| Setback setpoint | `{"109": 140, "119": 140}` (both together, like the app) | accepted; then R3 |
| Manual mode | `{"2": "manual"}` | applied, **erases the schedule** (R4) |
| End of return to schedule | `{"2": "at_home"}` | display only (R4, R5) |
| Room settings | `{"1": bool}` preheat, `{"30": bool}` lock, `{"116": bool}` window, `{"18": 210}` upper bound | applied in 5 to 10 min |

An isolated head is set via `tuya.m.custom.wkf.settings.change` (already in `async_write_setting`);
this path proved unreliable on grouped heads.

### 4.3 State

`tuya.m.my.group.device.list` v1.0 (parameter `gid`) gives, per device, `dps["2"]` (displayed mode),
`dps["172"]`, `dps["149"]`, `dps["118"]`, `dps["119"]`. No extra call is needed for `HeadState`.

## 5. What the integration exposes

### 5.1 Devices and entities

- One **device per room**, with: a `binary_sensor` "schedule active" (true if all its heads have
  `schedule_active`), `number` comfort setpoint and setback setpoint (write = publishing the DP +
  rewriting the schedule, R3), a `sensor` "inconsistent heads" (count).
- Per head: a `binary_sensor` "schedule active" (DP 172, diagnostic category).
- **Thermostat (`climate`)**: no `comfort` / `setback` / `holiday` preset tied to DP 2 (R5).
  **Durable setpoint write at the room level**: in modes `comfort` (`at_home`) and `setback`
  (`leaving_home`), changing the temperature publishes the setpoint on the group then rewrites one
  schedule day (R3) — the same path as the `number` entities above (`async_set_room_setpoint`,
  proven on real hardware 2026-11-16, PR #10). Outside these modes, or for an ungrouped head, the
  write fails cleanly (an error rather than a misleading value). The room's `number` entities offer
  the same setting, per room; the thermostat remains the per-head access.

### 5.2 Actions (services)

Domain `danfoss_ally_cloud`. Write actions **refuse a non-administrator user** (`Unauthorized`). All
take `config_entry_id` when several accounts are configured.

| Action | Fields | Response | Effect |
|---|---|---|---|
| `get_rooms` | — | `{"rooms": [Room]}` | read |
| `get_schedule` | `target`, `refresh` (bool, default false) | `Schedule` | read (cache, or cloud if `refresh`) |
| `set_schedule` | `target`, `days` (one or more days) | `WriteJob` | validate R1, write the given days |
| `copy_schedule` | `source`, `targets` (list), `days` (optional) | `{"jobs": [WriteJob]}` | copy the schedule |
| `restore_schedule` | `target` | `WriteJob` | R4: rewrite the 7 days then publish `at_home` |
| `get_write_job` | `job_id` | `WriteJob` | read |

`set_schedule` touches only the given days; the others stay as they are in the cloud.

### 5.3 WebSocket commands (for the frontend)

| Type | Fields | Response | Rights |
|---|---|---|---|
| `danfoss_ally_cloud/info` | — | `{"version": "<integration version>", "local_enabled": bool, "is_admin": bool}` | all |
| `danfoss_ally_cloud/rooms` | `entry_id` (optional) | `{"rooms": [Room]}` | all |
| `danfoss_ally_cloud/schedule/get` | `target`, `refresh` | `Schedule` | all |
| `danfoss_ally_cloud/schedule/validate` | `days` | `{"valid": bool, "errors": [Error], "transitions": {"mon": 3, …}}` | all |
| `danfoss_ally_cloud/schedule/set` | `target`, `days` | `WriteJob` | administrator |
| `danfoss_ally_cloud/schedule/restore` | `target` | `WriteJob` | administrator |
| `danfoss_ally_cloud/jobs/subscribe` | — | `WriteJob` events on every change | all |

The WebSocket commands and the actions share the same implementation: one function per operation.

### 5.4 Errors

Shape: `{"code": "…", "message": "…", "day": "mon" | null}`. The message is translated; the code is
stable.

| Code | Case |
|---|---|
| `invalid_time` | time outside `00:00`–`23:59` or malformed |
| `empty_or_reversed` | `start` ≥ `end` |
| `overlap` | two slots overlap |
| `too_many_transitions` | R1: count > 6 |
| `unknown_target` | unknown room or head |
| `grouped_device` | grouped head targeted directly: target its room |
| `not_admin` | write by a non-administrator user |
| `cloud_refused` | the cloud refused the call |
| `session_expired` | session to renew (re-authentication in progress) |

## 6. Embedded frontend

- Sources in `frontend/` at the repo root (TypeScript + Lit). The build produces **a single file**
  `custom_components/danfoss_ally_cloud/frontend/danfoss-ally-cloud.js`.
- The integration serves this folder at URL `/danfoss_ally_cloud/frontend/`
  (`async_register_static_paths`) and declares the Lovelace resource
  `…/danfoss-ally-cloud.js?v=<version>` (storage-mode dashboards; in YAML mode, the user adds it by
  hand — to document).
- Registration in `async_setup` (once per instance), never in `async_setup_entry`.
- On load, the frontend compares its version (injected at build) to `danfoss_ally_cloud/info`; if
  they differ, it offers to reload the page.
- Declared elements: `danfoss-ally-schedule-card` (Schedule card); later `danfoss-ally-room-card`
  and the `danfoss-ally-panel` panel.
- The frontend calls **only** the commands of section 5.3 and the entities; never the cloud.
- A non-administrator user (`is_admin` false) sees the card read-only.

## 7. Out of contract for now

Holiday (write unknown), one-off override outside comfort / setback modes (R5), room management
(create, rename, attach), boiler relay, firmware, full panel. Each will be the subject of an
addition to this contract. (The durable room setpoint, however, is now in the contract — see §5.1,
PR #10.)
