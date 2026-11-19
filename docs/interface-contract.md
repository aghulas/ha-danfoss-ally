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
  "inconsistent": false,
  "battery": 90,
  "valve_opening": 40,
  "heat_request": true,
  "window_open": false,
  "window_detection": true,
  "child_lock": false,
  "faults": [{ "code": "E14", "bit": 13, "label": "low battery", "action": "…" }]
}
```
- `schedule_active`, `preheat`: decoded from DP 172 (R6); `null` if the DP is absent.
- `inconsistent`: `mode_displayed` is `at_home` or `leaving_home` while `schedule_active` is `false`
  (head left in manual without the app knowing).
- `mounting`: DP 149 (head in mounting mode, not regulating).
- Status fields (all **read only**, decoded from the device DPs, `null` when the DP is absent):
  `battery` (%, DP 34), `valve_opening` (%, DP 170 `pi_heating_demand`), `heat_request` (DP 162),
  `window_open` (DP 25), `window_detection` (DP 116), `child_lock` (DP 30). `faults` is the decoded
  fault list (DP 45 / DP 184, same table as ZHA/Z2M); `E14`/`E15` mark low / critical battery. These
  were surfaced on `HeadState` in 0.6.0 (axis D) so the UI can show per-head battery / valve / window
  / fault; they add **no** cloud call (all come from `tuya.m.my.group.device.list`, §4.3).

### 3.4 Room (`Room`)

```json
{
  "id": "13000000",
  "name": "Room 1",
  "home": "Home",
  "product_id": "03wvrwpv",
  "heads": [ /* HeadState */ ],
  "comfort": 21.0,
  "setback": 14.0,
  "temperature": 20.4,
  "setpoint": 21.0,
  "mode": "at_home",
  "heating": true,
  "online": true,
  "writable": true,
  "climate_entity_id": "climate.room_1"
}
```
- `temperature`, `setpoint`, `mode`, `heating`, `online`: the aggregated room state (same values the
  room `climate` entity exposes). Added in 0.6.0 (axis D) so the room card shows the live climate
  without a second round-trip; read only.
- `writable`: the room's product is in `WRITE_VERIFIED_PRODUCTS` (setpoint write allowed on the
  room `climate`). `climate_entity_id`: the room thermostat's entity id (resolved from the entity
  registry, `unique_id = group_id`), or `null` if not registered yet. The room card uses it to call
  the **existing, already-validated** `climate.set_temperature`; it introduces no new write path.

### 3.4b Holiday (`Holiday`, read only)

```json
{
  "home": "Home",
  "gid": "13000000",
  "active": true,
  "scheduled": false,
  "detail": { "startDate": "…", "endDate": "…", "temperature": 150, "isRunning": true }
}
```
- `active`: a holiday is **in progress** — the record's `isRunning` flag. `vacation.detail` also
  returns a **planned** holiday (real hardware 2026-11-19), so a non-empty record is **not** enough.
  `null` if a record lacks a readable `isRunning` (unknown rather than guessed).
- `scheduled`: a holiday is on record but not started yet (`detail` non-empty, `isRunning` false).
- `detail`: the cloud's holiday record, passed through unmodified (fields vary; may be `null`).

### 3.4c Boiler relay (`Relay`)

```json
{
  "device_id": "<devId>",
  "name": "Boiler relay",
  "home": "Home",
  "on": true,
  "online": true,
  "rooms": [{ "room_id": "13000000", "name": "Room 1", "linked": true }]
}
```
- `on`: DP `1`, read only in contract (§4.6).
- `rooms`: every eligible room with whether it currently drives the relay (`linked`). Writing
  `linked` goes through `set_relay_room` (§5.2), gated on real-hardware validation.

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

### 3.6 Fleet overview (`FleetOverview`, read only)

Building / fleet snapshot for the side panel (§8). Aggregated **entirely from the coordinator's
cached state** — no extra cloud call (added in 0.6.0, axis D).

```json
{
  "homes": [
    {
      "gid": "13000000",
      "name": "Home",
      "holiday_active": false,
      "gateways": [
        { "device_id": "<devId>", "name": "Gateway", "online": true }
      ],
      "rooms": [
        {
          "id": "13000000",
          "name": "Room 1",
          "head_count": 3,
          "offline": 0,
          "low_battery": 1,
          "heating": true,
          "window_open": false,
          "inconsistent": 0,
          "faults": 1
        }
      ],
      "relays": [
        { "device_id": "<devId>", "name": "Boiler relay", "on": true, "online": true, "linked_rooms": 2 }
      ]
    }
  ],
  "totals": {
    "homes": 1, "gateways": 1, "rooms": 1, "heads": 3,
    "offline": 0, "low_battery": 1, "heating": 1, "faults": 1, "relays_on": 1
  }
}
```
- Per room: `offline` / `low_battery` / `inconsistent` / `faults` are counts over the member heads;
  `low_battery` counts heads with an `E14`/`E15` fault **or** `battery` ≤ 10 %; `heating` is true if
  any member head requests heat (`heat_request`) or the aggregated room is heating; `window_open` is
  true if any member head reports an open window.
- Per relay: `linked_rooms` is the number of rooms **linked** to the relay (that drive it), not the
  number calling for heat. A relay is listed under the home that holds the majority of its linked
  rooms; the relay → room link carries Tuya *room* ids (type 4), so rooms are matched to homes by
  normalised name (case-folded, alphanumerics only). With a single home every relay belongs to it.
- `totals` sums the per-home figures (building-wide health at a glance); `relays_on` counts relays
  that are on **and online** (an offline relay's state is stale). Everything is **read only**.

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
version of the contract said `gwId = devId` for an isolated head). **Confirmed on real hardware on
2026-11-17** (C0b trial, an ungrouped test head): a schedule write targeting the head
with `gwId = meshId` was accepted by the backend **and reached the hardware** (the Monday comfort
slot appeared in the head's schedule, re-read through the tunnel). `gwId = devId` for a schedule
write is **not** proven and must not be reintroduced blindly.

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
| Setback setpoint | `{"109": 140, "119": 140}` (both together, like the app) | accepted; then R3. ⚠ also applies `v` **at once** as the current setpoint, see below |
| Manual mode | `{"2": "manual"}` | applied, **erases the schedule** (R4) |
| End of return to schedule | `{"2": "at_home"}` | display only (R4, R5) |
| Room settings | `{"1": bool}` preheat, `{"30": bool}` lock, `{"116": bool}` window, `{"18": 210}` upper bound | applied in 5 to 10 min |

**Setback publish side effect (real hardware, 2026-11-19, a two-head test room, setback 14 → 13.5).**
Publishing `{"109": v, "119": v}` makes the heads apply `v` **immediately** as their current setpoint
(`OccupiedSetpoint` = `v`, `SetpointChangeSource` = `Externally`), **even in a comfort slot**. The
schedule rewrite that follows (R3) brings the slot's setpoint back 1 to 3 min later (`Schedule`
source). No thermal effect was observed over that window, but a setback edit in a comfort slot
does dip the setpoint briefly. Working hypothesis: DP 109 = the "now" setpoint, DP 119 = the setback
setting proper (to confirm before publishing DP 119 alone).

Head settings (DP 30 child lock, DP 116 window detection) — **real-hardware result W-3
(2026-11-19)**:

- **Grouped head**: set through its **room** with the group publish above (`{"30": bool}` /
  `{"116": bool}`), the proven path. ⚠ The setting applies to **every head of the room**; the
  integration's switch says so (`write_path: room`, `write_scope: room`, `room_head_count`).
  Measured 2026-11-19 (DP 30, a two-head room): applied on **both** heads in the cloud at
  T0 + ~15 s, well under the 5–10 min of R7.
- **Isolated head**: `tuya.m.custom.wkf.settings.change` (resType 1) is **accepted but never
  applied** for DP 30 / DP 116: the test head stayed locked more than 10 min, with `gwId = meshId` (the
  integration) and with `gwId = devId` (the MCP connector) alike — **addressing is not the cause**.
  Consistent with the connector's 2026-11-15 survey (DP 116 applied on 0 of 7 isolated heads).
  An app capture (emulator + frida, 2026-11-19) explains it: the app uses `settings.change` only for
  its "Settings" block `{"1", "118", "119", "121"}` (sent whole, `gwId = devId`), and toggles
  DP 30 on an isolated head with a **DP publish over Tuya cloud MQTT** (`publishDps`, topic
  `smart/mb/out/<gateway devId>`, protocol 2.3 frame) — no HTTP call. That MQTT path is **not
  implemented** (follow-up).

  Second capture, same day, going through **every** settings screen of an isolated head: **every**
  head setting goes through `publishDps` on Tuya cloud MQTT (topic `smart/mb/out/<gateway devId>`),
  none through an HTTP write route:

  | Setting (app) | `publishDps` |
  |---|---|
  | Preheat | `{"1": bool}` |
  | Child lock | `{"30": bool}` |
  | Open-window detection | `{"116": bool}` |
  | Mounting (vertical / horizontal) | `{"133": "Vertical" \| "Horizontal"}` |
  | Viewing direction | `{"101": bool}` |
  | Upper bound | `{"18": 210}` |
  | Lower bound | `{"27": 50}` (with `{"120": …}` when the pause setpoint must follow) |
  | Comfort setpoint | `{"118": 205, "16": 205}` |
  | Setback setpoint | `{"119": 145}` |
  | Pause setpoint | `{"120": 50}` |

  For preheat and the setpoints (`1`, `118`, `119`, `121`) the app **also** sends
  `settings.change` with the whole block (cloud-side store of the workflow), in addition to the
  MQTT publish: that HTTP call alone is not the write to the head.
- Hence, on an isolated head: window detection is written through the **local tunnel** (§4.4,
  W-4 ✅) when it is active and the head answers locally; otherwise the switch is **unavailable**.
  Measured 2026-11-19 (DP 116): the tunnel write is **immediate** (read back from the head at
  T0 + ~20 s), and the head reports it to the cloud in under a minute (per-device route); the
  integration marks the head for the post-command per-device read (R-3) so HA follows one poll later.
  The child lock has no tunnel path (the local read does not expose it).
- **Isolated head via Tuya cloud MQTT (`enable_cloud_mqtt`, OFF by default — 1.2.0).** The app's own
  path (`publishDps`) is reproduced: a protocol-2.3 frame `{"data":{"cid":<node>,"dps":{…}},
  "protocol":5}` encrypted (AES-GCM) with the gateway's localKey, published on
  `smart/mb/out/<gateway devId>`, over one MQTT connection opened from the integration's **own
  session** (distinct deviceId — coexists with the app, proven 2026-11-19). The write is **confirmed**
  by the gateway's inbound protocol-4 `{cid,dps}` echo on `smart/mb/in/<gw>` (or a cloud re-read),
  with a timeout and a clear error — never optimistic. **Validated on real hardware 2026-11-19: DP 30
  (child lock) on an isolated test head, confirmed in the cloud, the app and on the head.** For now the MQTT
  path carries **DP 30 only** (`MQTT_WRITE_DPS`); other DPs are added one at a time after a supervised
  write. When the option is on and the link connected, an isolated head's child-lock switch routes
  here; otherwise the tunnel; otherwise unavailable. (Protocol details: docs/cloud-mqtt-publish.md.)
- `async_write_setting` remains only for the back-to-schedule `at_home` label of an isolated head
  (display only, R5).

### 4.3 State

`tuya.m.my.group.device.list` v1.0 (parameter `gid`) gives, per device, `dps["2"]` (displayed mode),
`dps["172"]`, `dps["149"]`, `dps["118"]`, `dps["119"]`. No extra call is needed for `HeadState`.

### 4.4 Local tunnel (Zigbee) — DP scales

Operations the cloud misses (one-off setpoint override, valve descaling, window-detection write,
multi-gateway survey) go through the **local Zigbee tunnel** (DP 198 → 199), implemented in
`api/local/tunnel.py`. The scales below are the ones observed on real hardware; they are the
reference, over the published product schema.

| DP / attribute | Meaning | Scale (over the tunnel) |
|---|---|---|
| DP 171 (`OccupiedSetpoint`) | one-off setpoint override ("now", outside the schedule) | **hundredths of °C (×100)**: `7.0 °C` → raw `700` |

> **DP 171 scale — hundredths, not `10⁰`.** The official product schema
> (`dp_schema_officiel.md`, see `docs/reuse.md`) announces a `10⁰` scale for DP 171; this is
> **wrong**. The integration and `pydanfoss_cloud.local.tunnel` (`setpoint_value` / `DP_SETPOINT`)
> encode the override in **hundredths of °C**, confirmed on real hardware on 2026-11-17 (C0 trial,
> a test head: an override to `7.0 °C` was published as raw `700` and read back by the
> head as `7`, idle — whereas a `10⁰` reading of `700` would have clamped to the upper bound and
> requested heat). Do not "correct" the code to the schema.

### 4.5 Holiday (read + gated write)

The holiday **read** and the holiday **set / exit** routes both run through the app's runtime
mini-program (`miniAppId=tygzekxso4ca8h1e0q`); the plaintext bodies were captured on 2026-11-18 and
replay on the bare path-1a channel (the MiniApp envelope fields — `channelType`, `miniAppId`,
`miniAppVersion` — are unsigned extras, confirmed for the reads and **to confirm on real hardware for
the writes**). R5 still holds: `holiday` published via DP 2 is only a **label**; these
`solution.wkf.vacation.*` routes are the real lever.

Read routes (replayed read-only by the MCP connector `vacances`):

| Operation | API | Version | Body | Returns |
|---|---|---|---|---|
| Holiday on record for a home (in progress **or planned**) | `tuya.m.solution.wkf.vacation.detail` | 1.0 | `{"homeId": "<gid>"}` | detail dict, `{}` if none |
| Rooms covered by the holiday | `tuya.m.solution.wkf.vacation.rooms.list` | 1.0 | `{"homeId": "<gid>"}` | list of rooms (optional) |

A non-empty `vacation.detail` means a holiday is **on record**, in progress **or planned**: measured
2026-11-19, a holiday planned two weeks ahead came back as `{startDate, startTime, endDate, endTime,
temperature: 145, roomList, isRunning: false, vacationType: 3}`. **`isRunning`** tells them apart
(§3.4b `active` / `scheduled`). The fields are otherwise passed through as read by the cloud (no
re-interpretation). DP 121 (`holiday_setting`) is the per-head
holiday setpoint, decoded already (§4.3, `setpoints.holiday`).

Write routes (captured 2026-11-18; **GATED** — see §5.2, `enable_vacation_write`, off by default).
Two modes (DP 2 `holiday` vs `holiday_sat`). Real-hardware status (2026-11-19):

- `plan.leave` ✅ and `cancel` ✅ — a holiday planned on **one room** (`roomIds` = that room only),
  `vacationType` 3, shown at once in `vacation.detail` (and in the app, dates and temperature as
  sent); `cancel` cleared it for the whole **home** (it takes no room list).
- `plan.athome` and `leave.now` — **not validated** on real hardware yet.

| Operation | API | Version | Body |
|---|---|---|---|
| Away (fixed temp) | `tuya.m.solution.wkf.vacation.plan.leave` | 1.0 | `{"startDate":"YYYYMMDD","startTime":"HH:MM","endDate":"YYYYMMDD","endTime":"HH:MM","temperature":"<tenths, string>","homeId":"<gid>","roomIds":"<csv roomId>","timeZoneId":"Europe/Paris"}` |
| At home (follows Saturday) | `tuya.m.solution.wkf.vacation.plan.athome` | 1.0 | `{"startDate","endDate","homeId","roomIds","timeZoneId"}` — no temperature/times |
| Cancel a planned holiday | `tuya.m.solution.wkf.vacation.cancel` | 1.0 | `{"homeId","timeZoneId"}` |
| End an in-progress holiday | `tuya.m.solution.wkf.vacation.leave.now` | 1.0 | `{"homeId","roomIds","temperature":<tenths, int>,"timeZoneId"}` |

- `temperature` is tenths of °C: a **string** in `plan.leave`, an **integer** in `leave.now`.
- A vacation is set per **home** (`homeId` = gid), scoped to a **`roomIds`** csv (the app sends all
  the home's rooms; the integration does the same unless given a room list).
- **Edit = re-post** `plan.leave`/`plan.athome` (idempotent per home); there is no separate edit
  route. `plan.athome` needs a Saturday program on the rooms (the app blocks it otherwise).

### 4.6 Boiler relay

A **boiler relay** is a standalone Zigbee switch (Tuya `category` `kg`, one per home), not attached to
a room/group. Its single DP `1` = on/off. The useful control is *which rooms drive it* (the relay
follows the heat demand of the rooms **linked** to it, a server-side Danfoss function).

| Operation | API | Version | Body | Notes |
|---|---|---|---|---|
| Relay state | `tuya.m.my.group.device.list` | 1.0 | `gid` (URL param) | filter `category == "kg"`; `dps["1"]` = on/off |
| Rooms driving the relay (read) | `m.life.solution.wkf.reference.room` | 1.0 | `{"devId": R, "gwId": R}` | `[{roomId, roomName, enable, cancel}]`; **linked** = `enable` and not `cancel` |
| Link / unlink a room (write) | `m.life.solution.wkf.reference.edit` | 1.0 | `{"devId": R, "gwId": R, "roomId", "status": "bind"\|"unbind"}` | one room per call; **real-hardware validation required** |

- `gwId == devId` of the relay (not a `meshId`) for both relay calls — observed on the app, proven on
  the read path (2026-11-15); the write (`reference.edit`) is captured and **validated on real
  hardware** (2026-11-18, unbind then rebind of a room on the relay — see §5.2).
- **There is no manual relay on/off in the app (confirmed 2026-11-18).** The relay state is
  **automatic**: the Danfoss server computes it from the heat demand of the rooms **linked** to the
  relay. The app offers no DP `1` on/off control at all; it only lets you choose which rooms drive the
  relay (`reference.edit`). So a device-level DP `1` publish is **not** merely uncaptured — it does not
  exist as an app action, and forcing it is **out of contract** (§7). Reading the DP `1` state is in
  contract; the only write lever is the room↔relay link.

### 4.7 Room management

A **room** is a Tuya room (`type` 4); grouping ≥ 2 heads of the same type into a room creates the
schedule-group (`type` 5) that §1 and §4.1 drive. Routes captured and **validated on real hardware**
by the MCP connector (`smartlife.m.*` family; the APK also exposes the `thing.m.*` twins):

| Operation | API | Version | Body | Returns |
|---|---|---|---|---|
| Room map (name ↔ roomId) | `m.life.group.room.map.get` | 1.0 | `{"gid": G}` | `{"rooms": [{id, name}]}` |
| Create a room | `smartlife.m.room.add` | 2.0 | `{"gid": G, "name": N}` | `{"id": roomId}` |
| Rename a room | `smartlife.m.room.update` | 1.0 | `{"roomId": R, "name": N}` | — |
| Delete a room | `smartlife.m.custom.wfk.room.dismiss` | 1.0 | `{"roomId": R}` | — (heads become ungrouped) |
| Set a room's heads | `smartlife.m.custom.wkf.device.relations.selected.save` | 1.0 | `{"bizs": [{"id": devId, "type": 6}], "onlyParent": true, "parentId": R, "parentType": 4}` | — |

- **Attach / detach REPLACE the whole member list**: the backend sends `current ∪ added` to attach and
  `current − removed` to detach; it snapshots the previous membership for restoration. The current
  members are read from the **schedule-group** membership (not by name), so they are correct even
  when the names below diverge. The write addresses the **room (type 4)** via `parentId`.
- **Room (type 4) vs implicit schedule-group (type 5).** Grouping ≥ 2 compatible heads creates an
  *implicit* schedule-group (`m.light.room.implicit.group.*`). When a room is created **through the
  API**, Tuya auto-labels that group `"<room name> Group"`, so the group name the integration tracks
  (from `group.device.group.list`, §4.1) can differ from the room name (from `room.map.get`). Rooms
  created **in the app** keep identical names. Observed on real hardware 2026-11-18.
- **Room ↔ schedule-group mapping is by name** (the only link the API exposes), tolerant of that
  `" Group"` suffix: the backend matches the room on the group name, then on the group name with a
  trailing `" Group"` removed.
- **`rename_room` renames the room (type 4) only.** The implicit schedule-group may keep its old
  `"<old name> Group"` label until Tuya re-derives it; the integration's room device name follows the
  group name, so it can lag a rename. No schedule-group rename API is known.
- These writes mutate the live account structure (regrouping/ungrouping heads changes shared
  schedules) → **real-hardware validation required** before use. create / rename / delete are
  validated on real hardware (2026-11-18, shipped in 0.5.0). **Attach / detach return in 0.6.1**; the
  replace-list effect on the implicit group is validated in situ on the running install (the
  room-vs-group duality above is the reason it could not be validated pre-release).

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
- **Holiday (read only)**: per home, a `binary_sensor` "holiday active" (on only while a holiday is
  **in progress**, `isRunning`; attribute `scheduled` for a planned one, `detail` the raw record)
  and a `sensor` "holiday setpoint" (the temperature of the holiday on record, in progress or
  planned, `null` if none). No holiday *write* entity (§4.5, §7).
- **Boiler relay (read only)**: per relay device (`category` `kg`), a `binary_sensor` "boiler relay"
  (DP `1`) and a `sensor` "rooms calling for heat" (count of linked rooms). No relay on/off *switch*
  (the device-level write is uncaptured, §4.6, §7); the room ↔ relay link is changed via
  `set_relay_room` (§5.2).

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
| `get_holiday` | — | `{"holidays": [Holiday]}` | read |
| `get_relays` | — | `{"relays": [Relay]}` | read |
| `get_overview` | — | `FleetOverview` (§3.6) | read |
| `get_room` | `target` (room) | `{"room": Room, "schedule": Schedule}` | read |
| `create_room` | `name`, `devices` (list of devId), `home` (optional gid) | `{"room_id": "…"}` | create a room + attach heads. The room must be created in the heads' home (else it stays empty): `home` selects it, otherwise it is inferred from the devices (a single shared home must resolve, else `ambiguous_home` → pass `home`) |
| `rename_room` | `target` (room), `name` | `{"room_id": "…"}` | rename |
| `delete_room` | `target` (room) | `{"room_id": "…"}` | delete (heads ungrouped) |
| `attach_heads` | `target` (room), `devices` | `{"room_id": "…", "heads": […]}` | add heads (replaces list) |
| `detach_heads` | `target` (room), `devices` | `{"room_id": "…", "heads": […]}` | remove heads |
| `set_relay_room` | `relay` (devId), `target` (room), `linked` (bool) | `{"relay": "…", "room_id": "…", "linked": bool}` | link/unlink a room to the boiler relay |
| `set_vacation` | `home` (gid), `start_date`/`start_time`/`end_date`/`end_time`, `temperature` (°C), `rooms` (optional), `time_zone` (optional) | `{"home", "mode": "away", …}` | **GATED** away holiday (`vacation.plan.leave`) |
| `set_vacation_at_home` | `home`, `start_date`, `end_date`, `rooms` (optional), `time_zone` (optional) | `{"home", "mode": "at_home", …}` | **GATED** at-home holiday (`vacation.plan.athome`) |
| `cancel_vacation` | `home`, `time_zone` (optional) | `{"home", "cancelled": true}` | **GATED** cancel a planned holiday (`vacation.cancel`) |
| `end_vacation` | `home`, `temperature` (°C), `rooms` (optional), `time_zone` (optional) | `{"home", "ended": true, …}` | **GATED** end a running holiday now (`vacation.leave.now`) |

`set_schedule` touches only the given days; the others stay as they are in the cloud. The room
write actions and `set_relay_room` refuse a non-administrator (`not_admin`); they are gated on
real-hardware validation (they mutate the live account / the boiler's heat demand).

The four `*_vacation*` actions are **doubly gated**: admin-only, **and** behind the
`enable_vacation_write` option (off by default) — they raise `vacation_disabled` until it is turned
on for a supervised real-hardware validation session. Values are validated before any send
(`YYYYMMDD` / `HH:MM`, chronological period, setpoint bounds).

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
| `danfoss_ally_cloud/holiday` | `entry_id` (optional) | `{"holidays": [Holiday]}` | all |
| `danfoss_ally_cloud/relays` | `entry_id` (optional) | `{"relays": [Relay]}` | all |
| `danfoss_ally_cloud/overview` | `entry_id` (optional) | `FleetOverview` (§3.6) | all |
| `danfoss_ally_cloud/room/get` | `target` | `{"room": Room, "schedule": Schedule}` | all |
| `danfoss_ally_cloud/room/create` | `name`, `devices` | `{"room_id": "…"}` | administrator |
| `danfoss_ally_cloud/room/rename` | `target`, `name` | `{"room_id": "…"}` | administrator |
| `danfoss_ally_cloud/room/delete` | `target` | `{"room_id": "…"}` | administrator |
| `danfoss_ally_cloud/room/attach` | `target`, `devices` | `{"room_id": "…", "heads": […]}` | administrator |
| `danfoss_ally_cloud/room/detach` | `target`, `devices` | `{"room_id": "…", "heads": […]}` | administrator |
| `danfoss_ally_cloud/relay/set_room` | `relay`, `target`, `linked` | `{…}` | administrator |
| `danfoss_ally_cloud/vacation/set` | `home`, `start_date`/`start_time`/`end_date`/`end_time`, `temperature`, `rooms`?, `time_zone`? | `{…}` | administrator (GATED) |
| `danfoss_ally_cloud/vacation/set_at_home` | `home`, `start_date`, `end_date`, `rooms`?, `time_zone`? | `{…}` | administrator (GATED) |
| `danfoss_ally_cloud/vacation/cancel` | `home`, `time_zone`? | `{…}` | administrator (GATED) |
| `danfoss_ally_cloud/vacation/end` | `home`, `temperature`, `rooms`?, `time_zone`? | `{…}` | administrator (GATED) |

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
| `unknown_room` | named room not found in the account |
| `unknown_relay` | relay devId not found |
| `unknown_home` | `create_room`: none of the given heads found in any home |
| `ambiguous_home` | `create_room`: the given heads span several homes |
| `unknown_head` | head devId not found when attaching/detaching |
| `empty_devices` | a room create/attach was given no head |
| `no_members_left` | detaching would leave the room with no head (use `delete_room`) |

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
- Declared elements: `danfoss-ally-schedule-card` (Schedule card) and, since 0.6.0 (axis D),
  `danfoss-ally-room-card` (Room card, §8) and the `danfoss-ally-panel` side panel (§8).
- The frontend calls **only** the commands of section 5.3 and the entities; never the cloud.
- A non-administrator user (`is_admin` false) sees the cards read-only.

## 7. Out of contract for now

Axis B (0.5.0) brought holiday **read** (§4.5), the boiler relay **read** + room↔relay **link**
(§4.6), and room management (§4.7) into the contract. Axis A (toward 1.0) brought the holiday
**write** (§4.5) in, **gated** behind `enable_vacation_write` (off by default); `plan.leave` and
`cancel` are validated on real hardware, `plan.athome` and `leave.now` not yet. What stays out:

- **Direct boiler-relay on/off (DP `1`, device level).** Confirmed 2026-11-18: the app has **no**
  manual relay on/off — the relay is server-driven from the heat demand of the linked rooms, so there
  is no such app action to mirror (not merely "uncaptured"). Only the relay *state read* and the
  room↔relay *link* (`reference.edit`, §4.6) are in contract. The integration exposes **no** relay
  on/off switch and holds **no** DP `1` forcing path.
- **Firmware management.** The subject of a later addition.

Axis D (0.6.0) brought the **UI layer** into contract: the per-room card and the side panel (§8).

## 8. UI layer (axis D, 0.6.0)

The axis-D UI is a **presentation layer over the existing read commands and validated writes** — it
adds **no new cloud/local write primitive**. Its only writes reuse already-validated paths:
`schedule/set`, `schedule/restore` (R4), and `climate.set_temperature` on the room thermostat
(`async_set_group_setpoint`, proven on real hardware 2026-11-16).

### 8.1 Room card (`danfoss-ally-room-card`)

One room at a glance and its day-to-day actions. Configured by `room_id` (= `group_id`). Reads
`room/get` (Room §3.4 + Schedule §3.2) and subscribes to `jobs/subscribe`.

- **Shows**: room name; current temperature, mode and active setpoint; comfort / setback chips; a
  compact 7-day schedule strip (reuses the Schedule card's rendering); per-head badges —
  online/offline, battery (with low-battery emphasis on `E14`/`E15` or `battery` ≤ 10 %), valve
  opening, window open, mounting, fault, schedule-active/inconsistent.
- **Actions** (administrator only, degrade to read-only otherwise): raise / lower the room setpoint
  by one step via `climate.set_temperature` on `climate_entity_id` — shown only when `writable` and
  the entity id is present, and in comfort/setback mode (the climate entity refuses other modes
  cleanly); "back to schedule" (R4) via `schedule/restore` when a head stopped following its
  schedule; and a link to open the Schedule card for full editing.
- Never calls the cloud directly; unknown/missing fields degrade (dashes, hidden actions).

### 8.2 Side panel (`danfoss-ally-panel`)

A building / fleet overview, **read-first**. Registered as a `panel_custom` from the integration
(`frontend.py`, once per instance, best-effort — a registration failure never blocks setup), with a
sidebar entry; `require_admin` is false (read-only view). Reads `overview` (§3.6) and `info`.

- **Shows**, per home: a holiday badge; the gateways and their online state; a room grid with each
  room's health (heads, offline, low battery, calling for heat, open window, inconsistent, faults)
  linking to that room; the boiler relays (on/off, online, number of rooms calling for heat). A
  totals header gives building-wide health at a glance.
- Read-only: it surfaces state and links out; any change is made from the room card or the entities.
