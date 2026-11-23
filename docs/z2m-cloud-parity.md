# Zigbee2MQTT heads — parity with what the Danfoss cloud and gateway do

**Status: design, direction approved by the owner on 2026-11-23** — room coordination moves to a
standalone coordinator on MQTT (§6). Nothing here is implemented by this document; each write
stage of §7 still needs its own supervised trial. It answers
three questions for heads paired to a Zigbee2MQTT coordinator, with no Danfoss gateway and no
cloud: which functions did the cloud and the gateway provide *above* the head, how to provide each
of them again, and where that logic should run.

Every statement carries its level of proof:

- **[R]** established in this repository (code, or a real-hardware record under `docs/`);
- **[Z]** read in Zigbee2MQTT's documentation or sources (`zigbee2mqtt.io/devices/014G2461.html`,
  `zigbee-herdsman-converters` `src/devices/danfoss.ts`, `src/converters/toZigbee.ts`, fetched
  2026-11-23) — not observed on our hardware;
- **[H]** hypothesis, to settle on real hardware with the owner present.

## 1. Summary

**What a head loses when it leaves the gateway.** A head alone keeps regulating, keeps its weekly
schedule in memory, detects its own open window and exercises its valve. Everything that involves
*more than one device* or *a calendar* was done by the gateway or the Danfoss cloud: the room
(shared setpoints, schedule and settings), the room sensor feed, load balancing between the heads
of a room, holidays, the boiler relay's heat demand, the re-imposition of settings, the alerts.

**Where it stands.** The Companion already holds a first version of four of these for
Zigbee2MQTT heads (`companion_rooms.py`): virtual rooms, setpoint fan-out, room sensor feed, load
mean. Two more are written and not reachable (schedule fan-out, heat-demand list). None has a
write-up under `docs/validation/`. The two periodic feeds are each behind a Companion option,
closed by default (§4).

**Recommendation.** Move room coordination out of Home Assistant into a **standalone room
coordinator on MQTT**, a sibling of `danfoss2mqtt`: same package, same add-on repository, same
dialect, same `bridge/rooms` and `bridge/request` topics. The Companion goes back to what
`docs/companion-contract.md` says it is for both bridges: a reader that creates entities and
forwards commands. The Companion's own virtual rooms stay as they are until the coordinator has
taken over each function, one supervised trial at a time, then are retired (§6, §7).

## 2. Functions above the head

"Head alone" is what the head does with no gateway, per [Z] unless noted.

| # | Function | What the cloud / gateway does, and how | Proof | Head alone |
|---|---|---|---|---|
| 1 | **Room = group** | A room is a Tuya schedule-group; one publish (`s.m.dev.group.dp.publish`) reaches every head. A grouped head is only written through its room | [R] `docs/interface-contract.md` §1, §4.2 | No notion of room |
| 2 | **Room setpoints** (comfort, setback, pause) | Room DPs 118, 109 + 119; the schedule must be rewritten after a change (R3), or the head reverts at the next transition | [R] contract R3, §4.2 | One current setpoint (`occupied_heating_setpoint`); the schedule's transitions carry their own values |
| 3 | **Weekly schedule** | Stored in the cloud per room, pushed whole to every head (R2); at most six transitions a day, beyond which the head silently loses the day (R1) | [R] contract R1, R2 | Holds a ZCL weekly schedule and follows it by itself; accepts `weekly_schedule` and `clear_weekly_schedule` on `/set` although the property is not exposed [Z] |
| 4 | **Modes** (schedule, manual, pause, `at_home` / `leaving_home`) | DP 2. `manual` erases the head's schedule (R4); the others are cloud-side labels (R5); back to schedule = rewrite the schedule | [R] contract R4, R5, R6 | `programming_operation_mode` (`setpoint`, `schedule`, `schedule_with_preheat`, `eco`); changing it does **not** clear the schedule [Z] |
| 5 | **Room-wide settings** | Child lock (DP 30), window detection (116), upper bound (18), preheat (1) published to the room apply to **every** head | [R] contract §4.2 (two-head room, 2026-11-19) | Each setting is a per-head attribute |
| 6 | **Preheat and its re-imposition** | The real lever is attribute `0x0025` bit 1; the cloud reprograms the head when the app toggles it, and puts a head back to the cloud's value overnight | [R] `docs/preheat.md` | `programming_operation_mode = schedule_with_preheat`; nothing re-imposes it |
| 7 | **Load balancing** | The room's mean load (attribute `0x4040`, DP 107) is identical on every head of a room while each head reports its own estimate (`0x404A`, DP 108): "presumably written by the gateway" | [R] `docs/cloud-mqtt-channel.md` §6, §7 (observation; the writer is inferred) | Reports `load_estimate`; with `load_balancing_enable` on, "the gateway must update `load_room_mean`" [Z] |
| 8 | **Room sensor 014G2480** | Heads of a room with a sensor receive DP 140 (`room_sensor`) and DP 141 (`sensor_avg_temp`), together | [R] `docs/cloud-mqtt-channel.md` §6 (six heads of one room; that DP 141 is that sensor is likely, not established) | Regulates on `external_measured_room_sensor` while it is fed; resets it to −8000 by itself after 35 min (`radiator_covered` true) or 3 h (false) [Z] |
| 9 | **Open window across a room** | Not observed. The head exposes an input, `window_open_external` | [H] no record that the gateway propagates a window between heads | Own detection (`window_open_feature`, `window_open_internal`) |
| 10 | **Holidays** | Server-side plan per home and room list (`solution.wkf.vacation.*`): away at a fixed temperature, or at home following Saturday | [R] contract §4.5 (`plan.leave` and `cancel` validated; the rest not) | No calendar. `day_of_week = away_or_vacation` concerns valve exercise only [Z] |
| 11 | **Boiler relay 014G2400** | The Danfoss server switches the relay from the heat demand of the rooms linked to it; there is no manual on/off | [R] contract §4.6 | Publishes `heat_required` and `pi_heating_demand`; `heat_available` is a writable input whose effect is unclear [Z] |
| 12 | **Alerts** | The app's message center: low battery, device added or removed, firmware | [R] `docs/message-center.md` | `battery`, `system_status_code`, availability |
| 13 | **Clock** | Not studied on the gateway side | — | Zigbee2MQTT writes the time cluster at configure, on every device announce and every 24 h [Z] |
| 14 | **Room management, pairing, firmware** | Cloud routes for rooms (§4.7); pairing over Tuya cloud MQTT | [R] contract §4.7, `docs/roadmap.md` | Pairing, removal and OTA are Zigbee2MQTT's own |

Two things the cloud does *to* the heads have no equivalent to rebuild, because the cause is gone:
the lag of the bulk list route, and the overnight return to a cached value. What replaces the
second is a deliberate reconciliation (§5.5).

## 3. Zigbee2MQTT facts that shape the design

- **No group write.** A Zigbee2MQTT group command is a broadcast; broadcasts are not buffered for
  sleeping end devices, and the Danfoss converter queues its writes for the "sleepy TRV" precisely
  because of that. Thermostat is not a bindable cluster [Z]. A room is therefore a **fan-out of
  per-head writes**, each verified on that head's own state topic.
- **Two setpoint writes.** `occupied_heating_setpoint` is the "aggressive" user change (sent
  twice); `occupied_heating_setpoint_scheduled` is the same attribute written without the
  aggressive valve response, "meant for scheduled changes" [Z].
- **External sensor timing.** `radiator_covered` true (room-sensor mode): write at least every
  30 min, at most every 5 min or 0.1 °C; reset after 35 min. False (offset mode): at least every
  3 h, at most every 30 min or 0.1 °C [Z].
- **Load balancing.** Zigbee2MQTT gives no formula, cadence or timeout. The 15-minute cadence in
  `companion_rooms.py` ("Danfoss gateway cadence") has no source in this repository [H].
- **Reporting.** Zigbee2MQTT configures reporting for temperature, setpoint, mode, valve, status
  code and battery only. `load_estimate`, `heat_required`, window and preheat states arrive when
  the head decides to report them [Z]; the cloud capture shows the head does report its load
  estimate often [R].
- **Schedule read-back.** Recent converters expose `schedule_<day>` text properties (read and
  write, up to six transitions) [Z]; whether the installed Zigbee2MQTT has them is to check.
- **Boiler relay 014G2400 is not supported by Zigbee2MQTT** (no definition) [Z]. A relay stays on
  a Danfoss gateway, where only cloud rooms can be linked to it.

## 4. What the Companion does today, and the gap

Code read at `main` (2.0.3): `companion_rooms.py`, `mqtt_companion.py`, `companion_adapter.py`,
`services.py`, `__init__.py`. Rows 3, 7 and 8 and point 1 below are as of the stage 0 hardening
(§7), which changed code only: nothing in it was tried on real hardware.

| # | Function | Zigbee2MQTT lever | Companion today [R] | Gap |
|---|---|---|---|---|
| 1 | Room | none; fan-out | Virtual rooms (`companion_set_room` / `companion_delete_room` services, admin only), stored in Home Assistant storage; a room `climate` | No UI; rooms exist only inside Home Assistant; `native_rooms` is one dictionary for all prefixes, so a second bridge publishing `bridge/rooms` would overwrite the first |
| 2 | Room setpoint | `occupied_heating_setpoint` per head | Fan-out from the room `climate` (`async_set_room_setpoint`). Reported working on one four-head room on 2026-11-22, owner present; not recorded under `docs/validation/` | QoS 0 publish, no per-head verification, no retry, no write job; comfort and setback are stored but have no entity |
| 3 | Weekly schedule | `weekly_schedule` on `/set` | `async_set_room_schedule` exists, **called by nothing**. It refuses the whole request, before storing or sending anything, when a day needs more than six entries (the 00:00 entry included, so at least as strict as R1) | Never sets the programming mode; no read-back; never tried |
| 4 | Modes | `programming_operation_mode` | Read only | No room mode |
| 5 | Room-wide settings | per-head `/set` | Per-head switches and numbers only | No room-level setting, no drift detection |
| 6 | Preheat | `programming_operation_mode` | Per-head switch | No room-level value, nothing checks it holds |
| 7 | Load balancing | `load_room_mean`, `load_balancing_enable` | Option `companion_feed_load_mean`, **off by default**. When on: mean of the members' `load_estimate`, written every 15 to 18 min or on a change of 25, for rooms of two heads or more where **every** configured member reports `load_balancing_enable` on (unknown counts as off) | Never tried on real hardware; effect of a stale mean unknown, and closing the option writes nothing, so the heads keep the last mean they received |
| 8 | Room sensor | `external_measured_room_sensor`, `radiator_covered` | Option `companion_feed_external_sensor`, off by default (kept on for an entry that already had a room with a sensor, see point 1). When on: sensor temperature written per head on a change of 0.2 °C or when that head's last write is 20 min old, never twice within 5 min; one −8000 when the sensor goes offline. Evaluated on a 6-min timer, so the keep-alive lands at 24 to 26 min, under the 30 min of room-sensor mode [Z] | Still timer-driven, not triggered by the sensor's messages; ignores `radiator_covered` (the room-sensor cadence is used in both modes, more often than offset mode asks for); timing not verified on real hardware |
| 9 | Window across a room | `window_open_external` | Nothing | To decide (§5.7) |
| 10 | Holidays | none | Reads `danfoss2mqtt/bridge/holidays` only | Nothing for Zigbee2MQTT rooms |
| 11 | Heat demand | `heat_required`, `pi_heating_demand` | `rooms_calling_for_heat` exists, **called by nothing** | No entity, no consumer |
| 12 | Alerts | state topics | Repairs issues for faults, for both bridges | Low battery and long-open window not covered |
| 13 | Clock | Zigbee2MQTT | Nothing needed | Check once on a real head |

Three points deserve attention before any new work:

1. **The two periodic feeds were open by default until stage 0.** Defining a virtual room with a
   sensor started writes of `external_measured_room_sensor` and `load_room_mean` to every member,
   every 15 minutes, with no option to close them, against the project's rule that a new write
   is closed until its supervised trial (`docs/architecture.md`, "Rules for adding a route").
   Each feed now has its own Companion option, off by default. One exception, so that an upgrade
   does not silently cut a feed heads are regulating on: at the first start after the upgrade,
   an entry that already stores a virtual room with a sensor gets the sensor option stored **on**
   (logged as a warning); every other entry gets it stored off. The load mean has no such
   carry-over: an install that was writing it stops on upgrade, and its heads keep the last mean
   received (what they do with it is open, §8). Neither feed has a supervised trial yet.
2. **A feed was already running before the Companion.** On 2026-11-21 the Zigbee2MQTT heads of
   the trial area regulated on an external room sensor (`external_measured_room_sensor` = 1403,
   `docs/validation/2026-11-real-hardware-validation.md`). What wrote that value is not recorded
   here. Two feeders on one head must not coexist; identify it before the next step.
3. **The other bridge is short of the contract too.** `docs/companion-contract.md` §3 lists
   `bridge/relays`, `bridge/alerts` and `bridge/request/<action>` for room, schedule and holiday
   operations; the standalone `danfoss2mqtt` daemon publishes `bridge/rooms` and
   `bridge/holidays` and answers `refresh` only. Whatever request vocabulary the coordinator
   defines should be the one `danfoss2mqtt` grows into.

## 5. Proposal, function by function

One model for all of them: the coordinator keeps a **desired state per room** in its own store,
derives per-head writes from it, and publishes what the heads **report**, never what it asked.

### 5.1 Rooms and configuration

- **Who defines a room**: the coordinator's store (one JSON file in the add-on's data folder),
  changed only through `bridge/request/room/*` (create, rename, set members, set sensor, delete).
  The Companion's panel and services call those requests, as they call the cloud's room routes
  today. A room lists its heads by Zigbee address and names the bridge prefix they live on.
- **A room object** on `<prefix>/bridge/rooms` has the shape `danfoss2mqtt` already publishes
  (`group_id`, `name`, `home_id`, `members`, `temperature`, `humidity`, `setpoint`, `setpoints`,
  `mode`, `heating`, `schedule`), plus `desired` (what was asked) and `drift` (heads that differ).
- **Single owner per head.** A head belongs to at most one room, and only the coordinator writes
  the room-managed properties of a member. The Companion's telemetry loop skips any head that a
  bridge-published room contains.

### 5.2 Setpoints

Room setpoint change → one `/set` per member, in sequence, each confirmed by that head's state
topic within a timeout, retried a bounded number of times, reported per head (`applied`,
`mismatch`, `unreachable`) as the existing `WriteJob` does. Values are validated first (0.5 step,
within every member's bounds). A user change uses `occupied_heating_setpoint`; a change the
coordinator makes on its own (holiday edge, reconciliation) uses
`occupied_heating_setpoint_scheduled`.

### 5.3 Weekly schedule, comfort and setback

- The room's schedule (seven days of comfort slots, with the comfort and setback values) lives in
  the coordinator's store, in the `Schedule` shape of `docs/interface-contract.md` §3.2.
- A write is refused before any send when a day needs more than six transitions (R1, the same
  count as `api/schedule.py`); nothing is truncated.
- Each head receives the seven days, then `programming_operation_mode`. The head then follows the
  schedule **by itself**: a stopped coordinator changes nothing.
- A comfort or setback change rewrites the schedule on every member: the transitions carry the
  values, exactly R3.
- Verification: read the schedule back once after a write (`schedule_<day>` where the installed
  Zigbee2MQTT has it, else a `getWeeklySchedule` read), then once a week at most.

### 5.4 Modes and holidays

- Room modes: `schedule`, `manual` (one setpoint held), `pause` (the pause setpoint held). They map
  to `programming_operation_mode` and a setpoint. Zigbee2MQTT says a mode change keeps the
  schedule [Z]; on the cloud path it erases it (R4). **[H] to settle first**: if it holds, back to
  schedule is one mode write; if not, it is a schedule rewrite, as on the cloud.
- A holiday is a coordinator calendar entry: start, end, temperature, room list. At the start the
  rooms go to a held setpoint, at the end back to schedule. The coordinator **reconciles at every
  start**, so a holiday edge missed while it was stopped is applied late, not lost. "At home,
  follows Saturday" is left for later.

### 5.5 Room-wide settings, preheat, reconciliation

Child lock, window detection, setpoint bounds and preheat become room values, fanned out like a
setpoint. Reconciliation replaces what the cloud did by re-imposing: the coordinator compares each
member's **reported** state with the room's desired state (no extra radio traffic), rewrites a
differing head at most once an hour and three times in a row, then stops and flags the head as
drifting. A head changed by hand on its dial is therefore either brought back or shown, never
silently fought forever.

### 5.6 Room sensor and load balancing

- **Sensor feed.** Triggered by the sensor's own messages, not a timer: write when the value moved
  by 0.2 °C and the last write to that head is over 5 minutes old; keep-alive every 20 minutes
  when `radiator_covered` is true, every 2 hours when false. A sensor that is offline or silent
  for 30 minutes stops the feed and one −8000 is written. **If the coordinator stops, the head
  resets the value by itself after 35 minutes or 3 hours and regulates on its own sensor** [Z]:
  degraded, not dangerous.
- **Load mean.** Only for rooms of two heads or more where every member has
  `load_balancing_enable` on. Mean of the valid `load_estimate` values, written every 15 minutes
  or on a significant change. What a head does with a mean that is no longer refreshed is unknown
  [H]: until the trial says otherwise, a clean stop writes −8000 (undefined) to the members.

### 5.7 Open window, heat demand, alerts

- **Window.** Off by default. When on, a head reporting `open` sets `window_open_external` on the
  other members, cleared when it closes or after a maximum duration. There is no proof the
  Danfoss gateway does this [H]; the lever is real [Z]. It also opens the way to door and window
  contacts later.
- **Heat demand.** The coordinator publishes `<prefix>/bridge/heat_demand` (retained): rooms
  calling for heat, highest valve opening, a timestamp, and a validity period. A consumer treats
  an expired or missing message as "unknown" and applies its own safe default; the coordinator's
  last-will clears it. The consumer (boiler integration, or an automation) is outside this
  project; the Companion exposes the value as a sensor. The 014G2400 relay itself cannot follow
  Zigbee2MQTT rooms (§3).
- **Alerts.** Stay in the Companion (Repairs), extended to low battery and a window open for too
  long, for both bridges alike. Nothing for the coordinator to do.

### 5.8 Radio and battery budget

Every write wakes a battery head. Rules: one queue per head, at most one room-managed write per
head every 5 minutes (sensor value and load mean share one `/set`), a global rate cap, writes
staggered across rooms, nothing sent when the reported value already matches. Order of magnitude
for 100 heads in room-sensor mode with load balancing: about 3 keep-alives and up to 4 load
writes per head and hour, shared where possible — several hundred writes an hour for the site.
Battery effect is unknown [H]: measure it on the pilot room over two weeks before widening.

## 6. Where it should run

| Criterion | (i) Companion (Home Assistant) | (ii) Standalone coordinator on MQTT | (iii) Zigbee2MQTT external extension | (iv) Automations / blueprints |
|---|---|---|---|---|
| Runs while Home Assistant restarts or is being updated | **No**; every integration update restarts it | **Yes** (own add-on or container) | Yes | No |
| Symmetry with `danfoss2mqtt` | No: the Companion reads one bridge and orchestrates the other | **Yes**: rooms come from a bridge on both sides | Partly | No |
| Other consumers (MCP connector, a second Home Assistant) see the rooms | No (Home Assistant storage) | **Yes** (`bridge/rooms`) | Yes | No |
| Distribution | HACS, already there | Add-on repository and PyPI, already there for `danfoss2mqtt` | A JavaScript file in Zigbee2MQTT's data folder; disabled by default since 2.11 [Z] | Blueprint import, per room |
| Testability | Home Assistant test harness | Plain Python, the daemon's test style | Poor: internal, unversioned API [Z] | Poor |
| Write safety (validation, verification, closed by default) | Possible | **Possible, in one place** | Possible, inside the radio process | Not realistic |
| Blast radius of a bug | Home Assistant | Its own process | **Zigbee2MQTT itself** | One room |
| Cost | Lowest: the code exists | A new deliverable to build and operate | A second language and toolchain | Lowest to start, highest to maintain |

**Decision: (ii)**, approved by the owner on 2026-11-23. The deciding points:

1. **Home Assistant restarts are routine here** — every integration release needs one. With (i),
   each of them stops the sensor feed and the load mean; with a calendar function, it can miss a
   holiday edge. The coordinator must not share a process with the user interface.
2. **The contract already says so.** The Companion is meant to read bridges. Orchestrating
   Zigbee2MQTT heads from inside it creates a second code path for every room function and makes
   the two bridges look different to everything above them.
3. **Heads are autonomous for the vital part.** Setpoint and schedule live in the head; what the
   coordinator adds degrades gracefully when it stops (§5.3, §5.6). That holds for (ii) only if
   it is designed in, and it is easier to prove in a small standalone process.

Rejected: (iii) puts project code inside the process that carries the radio, on an API with no
stability guarantee; (iv) cannot validate, verify or coordinate, and is kept only for what it is
today — a stop-gap for one sensor feed (`blueprints/automation/danfoss_ally_cloud/`).

**Shape of (ii).** A second entry point in the `pydanfoss-cloud` package (it already holds
`rooms.py`, `schedule.py`, `writes.py` and `z2m_contract.py`), shipped as a second add-on in the
`danfoss2mqtt` add-on repository. It subscribes to the Zigbee2MQTT prefix, and publishes under
**its own prefix** — never inside Zigbee2MQTT's namespace — `bridge/state` (with a last-will),
`bridge/rooms`, `bridge/holidays`, `bridge/heat_demand`, and `bridge/request/*` with
`bridge/response/*`. The package name says "cloud" and this part is not: accepted for now, a split
into its own package is a later, mechanical step.

Changes on the Companion side, all small: keep rooms per prefix instead of one dictionary; route a
room write to the owning bridge's `bridge/request`; show a room's write entities unavailable when
its bridge is offline; skip its own telemetry for heads a bridge room contains.

## 7. Plan

Each stage ships alone. "Trial" means a supervised write on real hardware with the owner present,
on one room, read back from the heads, recorded under `docs/validation/`
(`docs/first-write-procedure.md`).

| Stage | Content | Real hardware |
|---|---|---|
| 0 | Before anything: find what fed the external sensor on 2026-11-21; record the 2026-11-22 Companion validation under `docs/validation/`; put the Companion's two feeds behind an option and fix the sensor keep-alive (30 / 45 min against a 35-min reset). **Code part done** (options, keep-alive, load-balancing gate, schedule refusal; §4), not tried on real hardware; the two read-only items remain | Read-only check |
| 1 | Coordinator, **read only**: room store, `bridge/rooms` aggregates, heat demand, drift report. Companion reads it (rooms per prefix) | None (no write) |
| 2 | Room setpoint fan-out with per-head verification and write jobs | Trial: one room, both setpoint properties |
| 3 | Room sensor feed, event-driven, both `radiator_covered` modes | Trial, including the stop test: coordinator stopped, the head back to −8000 at 35 min |
| 4 | Weekly schedule, comfort / setback, programming mode | Trial: write, read back, watch the next morning's transitions; **settle whether a mode change keeps the schedule** |
| 5 | Room-wide settings, preheat, reconciliation | Trial: preheat held over one night with no cloud; a head changed by hand |
| 6 | Load balancing | Trial on a two-head room: valve openings with and without the mean; what a stale mean does |
| 7 | Holidays, then open window across a room | Trial each |
| 8 | Retire the Companion's virtual rooms (migration of the stored rooms to the coordinator) | On-site cutover |

The order follows what is already live (2, 3), then what a re-paired head has lost outright (4),
then what only matters at scale (5, 6, 7).

## 8. Open questions

- Does `programming_operation_mode = setpoint` keep the schedule on our firmware, as Zigbee2MQTT
  says? (Stage 4.)
- What does a head do with a `load_room_mean` that stops being refreshed, and at what cadence did
  the gateway write it? A cloud-MQTT listen on a gateway room would give the cadence, read-only.
- Does the Danfoss gateway propagate an open window between the heads of a room, and does it
  write `heat_available` from the relay state?
- Are the `schedule_<day>` properties present in the installed Zigbee2MQTT?
- Battery cost of the feeds on a head (§5.8).
- Who consumes the heat demand on this site: the boiler integration, or nobody yet?
