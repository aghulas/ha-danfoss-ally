# Boiler relay on Zigbee2MQTT — design

**Status: design only (2026-11-28).** Nothing here is implemented, paired or written. No stage below
starts without the owner's go-ahead, and each write stage follows
[`first-write-procedure.md`](first-write-procedure.md). This note continues
[`z2m-cloud-parity.md`](z2m-cloud-parity.md) (row 11 of its §2, and §5.7) and
[`roadmap.md`](roadmap.md) §5.

The boiler is the school's real heating. **Safety and fail-safe behaviour come before features**:
a relay that sticks off leaves classrooms cold and pipes at risk; a relay that sticks on wastes
energy but keeps the building warm. Each choice below is made with that difference in mind, and
the choices that depend on how the boiler is wired are left as questions for the owner (§8).

Proof levels, as in `z2m-cloud-parity.md`:

- **[R]** established in this repository or its sibling repositories (code, or a real-hardware
  record);
- **[D]** read in Danfoss's own published documentation (links in §2.1), not observed on our
  hardware;
- **[Z]** read in Zigbee2MQTT's sources or documentation (`zigbee-herdsman-converters` at commit
  `1cfe81de`, 2026-11-27), not observed on our hardware;
- **[H]** hypothesis, to settle on real hardware with the owner present.

## 1. Summary

- **Today** the two boiler relays sit on Danfoss gateways. The Danfoss side switches each relay
  from the heat demand of the rooms linked to it. There is no manual on/off in the app. We can
  read the relay's state and change which rooms are linked, and nothing else [R].
- **Zigbee2MQTT has no definition for this relay** [Z]. Danfoss says it can join "any Zigbee 3.0
  compliant Zigbee gateway" [D], so Zigbee2MQTT would most likely build an *automatically
  generated definition* from the clusters it finds at pairing (an on/off switch if it has
  `genOnOff`) [Z]. What it really exposes is only known after an interview on real hardware [H].
- **The relay has no logic of its own** that we could reuse: Danfoss describes it as a device that
  "is only ordered to turn ON or OFF" [D]. The demand logic must be rebuilt.
- **Recommendation:** put the relay logic in the room coordinator add-on
  (`danfoss-room-coordinator`), not in the Home Assistant integration, for the same reasons
  the rooms went there (it keeps running through Home Assistant restarts). It reads the heads of
  both bridges, so it covers the mixed fleet during the migration. It starts in **shadow mode**:
  it works out the relay state it would set and publishes that, and sends nothing. We compare that
  with what the cloud relay really does, for days, before anything is switched.
- **First stage to run (read only):** a passive multi-day observation of the cloud relays against
  their rooms' head demand, to measure the delays and the aggregation the Danfoss side really uses
  (§7, stage A). It needs no write, no pairing and no site visit.
- **The fail-safe question** (what the boiler does when the controller is gone) is for the owner
  and the boiler installer to decide. It probably means checking the wiring (§5.1). Nothing
  moves to Zigbee2MQTT before that is settled.

## 2. The device

### 2.1 Identity

| Item | Value | Proof |
|---|---|---|
| Product | Danfoss Ally™ Boiler Relay, mains 230 V~, volt-free change-over output 3(1) A at 250 V~ | [D] data sheet |
| Danfoss code number | **`014G2479`** | [D] data sheet, "Information to the User" |
| Code used in this repository | `014G2400` (`companion-contract.md` §2, `z2m_contract.RELAY_MODELS`) | [R] |
| Tuya cloud | category `kg`, product `ypieax1h`, one data point: DP `1` = on/off | [R] `interface-contract.md` §4.6 |
| Buttons | **PROG** (join, reset), **CH** (reset, **override**); factory reset = both buttons held 20–25 s | [D] data sheet |
| Terminals | `N`, `L` mains; `2` COM; `3` **ON** (COM–3 closed when heat is on, normally open); `4` **OFF** (COM–4 closed when no heat is requested, normally closed) | [D] data sheet |
| Radio | Zigbee 3.0, mains powered, so a Zigbee router | [D]; router role [H] (usual for a mains device) |

**`014G2400` is the Ally Gateway's code number**, not the relay's [D]: the Download Center files
`014G2400` under "Danfoss Ally™ Gateway". The repository uses `014G2400` as the relay's model
string, inherited from an early capture. This note does not change it. Correcting it is a separate,
small follow-up (§9).

Sources (fetched 2026-11-28):

- Data sheet, *Danfoss Ally™ Boiler Relay*, AI577838761338en-000101:
  `https://assets.danfoss.com/documents/latest/614241/AI577838761338en-000101.pdf`
- Quick guide, 014R0007: `https://assets.danfoss.com/documents/latest/511424/AN45455446162501-000202.pdf`
- *Information to the User (Danfoss Ally™ Boiler Relay)*, EU Data Act, AM546565335403en-010101:
  `https://assets.danfoss.com/documents/latest/562824/AM546565335403en-010101.pdf`. Danfoss says
  there that the relay "is only ordered to turn ON or OFF the relay controlling the boiler", stores
  only its network data and current state, and can be joined to any Zigbee 3.0 gateway. Its
  "Zigbee 3.0 API specification" is said to be on the Ally support page; it is not in the
  Download Center (searched 2026-11-28).
- *Danfoss Ally™ Radiator Thermostat Zigbee Cluster Specifications*, AM375549618098en-000201
  (the head, not the relay; used in §3):
  `https://assets.danfoss.com/documents/latest/602269/AM375549618098en-000201.pdf`

### 2.2 What Zigbee2MQTT exposes for it

- **No definition** for this relay in `zigbee-herdsman-converters`: nothing in `devices/danfoss.ts`
  (it covers heads `014G2461`, Icon, Icon2 and the `140F1170` floor thermostat), and no
  fingerprint `ypieax1h` anywhere in `src/` [Z]. There is no device page
  `zigbee2mqtt.io/devices/014G2479.html` (HTTP 404). No issue on the Zigbee2MQTT tracker asks for
  it (searched 2026-11-28).
- **A precedent:** the room sensor `014G2480`, Tuya product `mxzo5rhf`, is supported as a Tuya
  white-label with Zigbee manufacturer name `_TZ3000_mxzo5rhf` (`devices/tuya.ts`) [Z]. Danfoss
  sub-devices therefore probably carry their Tuya product id as a Zigbee manufacturer name. The
  relay would then show up as `_TZ3000_ypieax1h`, or another Tuya prefix [H].
- **Unknown devices get a generated definition.** Zigbee2MQTT generates a definition from the
  clusters an unknown device declares (`lib/generateDefinition.ts`): with an input `genOnOff`
  cluster this is an on/off switch with `state` (`ON` / `OFF` / `TOGGLE`), and with
  `startUpOnOff` support also `power_on_behavior` [Z]. The standard `state` converter also takes
  `on_time` / `off_wait_time`, which map to the ZCL command *On With Timed Off* [Z]. Whether the
  relay implements that command is unknown [H]. It matters for the fail-safe (§5.3).
- **Two risks** to rule out at the interview [H]: the relay may be a Tuya `0xEF00` (TS0601-style)
  device. Its single cloud DP would then travel in Tuya frames, and a generated definition would
  expose nothing usable without an external converter. Or it may expose Danfoss manufacturer
  attributes (an internal timeout, a fail-safe state) that only its API document describes.

**Own local logic:** none that we know of [D]. The relay does not subscribe to the heads' demand
by itself. Something above it decides. Whether it has a timeout of its own (for example falling
back to a state when it loses its coordinator) is not documented [H]; it is measured on the
bench in stage C.

## 3. What the cloud does today

### 3.1 Known

- The relay follows the heat demand of the rooms **linked** to it. The app has **no manual on/off**
  (confirmed 2026-11-18). Rooms are linked and unlinked through
  `m.life.solution.wkf.reference.edit`, validated on real hardware (2026-11-18). The link list is
  read through `m.life.solution.wkf.reference.room`. Code: `async_relay_rooms` / `async_relay_bind`
  in `pydanfoss_cloud/client.py`; contract: `interface-contract.md` §4.6 [R].
- The integration exposes the relay read only: a `binary_sensor` (DP `1`, unavailable while the
  relay is offline) and a sensor of linked rooms. `danfoss2mqtt` republishes the relay in the
  Zigbee2MQTT dialect (`state`, `relay_on`) and the linkage on `danfoss2mqtt/bridge/relays`
  (`companion-contract.md` §2, §3) [R].
- A head publishes the demand signals the Danfoss side can use [R]/[D]:
  - DP `162` `heat_supply_request` = Zigbee attribute `0x4031` *Heat Supply Request*, reported
    within 60 s of a change and at least every 12 h [D]. Zigbee2MQTT calls it `heat_required` [Z].
  - DP `170` = `pi_heating_demand` (valve opening, 0–100 %) [R].
  - DP `3` `work_state` (`Heat` / `NoHeat`), which Zigbee2MQTT derives into `running_state` [R]/[Z].
- The head also has an **input** from above: attribute `0x4030` *Heat Available*. "By default the
  heat is considered on if the gateway does not send any info about that." It works with
  `0x4059` *Heating System Mode*: in `auto`, the head switches itself to boiler mode for 48 h when
  it receives `Heat Available = false` [D]. Zigbee2MQTT exposes both, as `heat_available` (with the
  note "not clear how this affects operation") and `heating_system_mode` [Z].
- The head's schema has DP `138` `boiler_relay` (read only) and DP `139` `heat_status` (write)
  [R] `danfoss-app-capture/dp_schema_officiel.md`. Their meaning was never observed.
- The head's fault bit 11 is read as E12, "boiler relay communication lost", in the MCP connector
  [R]. The head specification describes E12 as raised "if lost coordinator more than 2 minutes",
  cleared on rejoin [D]. The two readings differ. On Zigbee2MQTT the head's coordinator is
  Zigbee2MQTT itself, so E12 should mean "Zigbee2MQTT lost", not "relay lost" [H].

### 3.2 Unknown

None of these is documented by Danfoss or observed by us:

1. **Where the rule runs**: on the Danfoss/Tuya server ("wkf" = workflow, an account-level route)
   or on the gateway. It decides what happens when the internet is down. [H]
2. **The aggregation**: is a room "calling" when any head reports `heat_supply_request`, or when a
   valve opens past some threshold? One room calling, or a count?
3. **The delays**: on-delay, off-delay, minimum on and off times, any anti-short-cycling.
4. **Loss of signal**: what the relay is set to when a linked head goes offline, when the gateway
   loses the cloud, or when the relay loses the gateway.
5. **What the gateway writes back to the heads**: does it set `0x4030 Heat Available` from the
   relay state, and does DP `138` / `139` carry that?

Points 2 and 3 can be measured **without writing anything** (stage A, §7): log every DP `1`
transition of each relay, and every DP `162` / `170` / `3` change of the heads of its linked rooms,
with timestamps, for several days, then read the delays and the rule off the log. Point 5 can be
watched the same way on DP `138` / `139`.

## 4. The function in Home Assistant's world, without the cloud

### 4.1 Where it lives

| Criterion | Room coordinator add-on (recommended) | Companion integration | HA automation / blueprint |
|---|---|---|---|
| Keeps running through Home Assistant restarts and updates | **Yes** | No: every integration release restarts it | No |
| Already holds the rooms and their members | **Yes** (`room_store.py`) | Partly (virtual rooms, being retired) | No |
| Already computes heat demand | **Yes** (`room_view.build_heat_demand`, `bridge/heat_demand`) | No (`rooms_calling_for_heat` is called by nothing) | — |
| Closed-by-default arming, write jobs, read-back | **Yes** (`armed_rooms`, `write_job.py`) | Possible | Not realistic |
| Testable without hardware | **Yes** (plain Python) | HA test harness | Poor |

**Decision proposed: the coordinator**, as a new *relay* object next to rooms, in the same store,
on the same request topics. This is the conclusion of `z2m-cloud-parity.md` §6, applied to the
relay. A boiler must not stop being controlled because the user interface restarts.

The Companion stays a reader: it shows the relay, its linked rooms, the coordinator's decision and
the alarms, and forwards the owner's override (§5.5) to the coordinator as a request. Home
Assistant is still the place for **notifications**: it is where the owner looks.

### 4.2 Inputs

| Input | Source | Use |
|---|---|---|
| `heat_required` (`0x4031`) per head | `zigbee2mqtt/<head>` [Z]; `danfoss2mqtt/<head>` (DP `162`) [R] | **Primary signal**: the head's own decision that it needs heat |
| `pi_heating_demand` per head | both bridges (Zigbee attribute `0x0008`, DP `170`) | Secondary: confirms a call, feeds the "valve wide open, relay off" alarm |
| `running_state` | both bridges | Not used to decide (it is derived from `heat_required` or the output state [Z]) |
| Head `availability` / `online` | both bridges | An offline head does not vote (as `_room_calls_for_heat` does today) |
| Room membership | coordinator store (Zigbee2MQTT rooms); `danfoss2mqtt/bridge/rooms` (cloud rooms) | Which heads belong to which linked room |
| Relay link list | coordinator store (new); seeded once from `danfoss2mqtt/bridge/relays` | Which rooms drive which relay |
| Relay `state` and `availability` | `zigbee2mqtt/<relay>` | The **reported** state, the only one ever shown |
| `heat_available` (`0x4030`) | — | **Not written.** The heads keep their default "heat available" [D]. Writing it is a later, separate stage, if ever (§9) |

**Mixed fleet.** During the migration a relay's linked rooms can be partly on Zigbee2MQTT and
partly on gateways. The coordinator today subscribes to one source prefix (`source_prefix`,
default `zigbee2mqtt`). The relay function needs it to also read the `danfoss2mqtt` prefix, read
only. That bridge already speaks the Zigbee2MQTT dialect, so a cloud head looks the same as a
local one [R]. Two consequences:

- A cloud head's demand arrives **minutes late** (the bridge polls the cloud, and the bulk route
  lags; `CLAUDE.md`). For a boiler this is acceptable, but the off-delay must be longer than that
  lag, or a cloud room's demand could switch the boiler off and on again.
- A cloud head going `online: false` is a fact about the cloud, not always about the head. Same
  rule as for a local head: it does not vote. If **every** head of the relay's rooms is unknown,
  the decision is "unknown" and the fail-safe applies (§5.2), never "no demand".

### 4.3 Aggregation and hysteresis (proposal, to be checked against stage A)

Per relay, every time an input changes and at least once a minute:

1. **Room demand.** A linked room *calls* when at least one of its online heads reports
   `heat_required = true`. The `pi_heating_demand` value is recorded but does not trigger a call
   by itself until stage A shows the Danfoss side does that. This is what `build_heat_demand`
   computes today, minus `heating`.
2. **Relay demand.** The relay is *wanted on* when at least `min_rooms_calling` linked rooms call
   (default 1).
3. **Unknown.** The input is unknown when no linked room has any online head with a fresh
   reading (fresh = reported within `input_stale_s`, default 2 h, longer than the head's reporting
   interval for `heat_required` but far shorter than its 12 h maximum). Unknown is never treated
   as "off" (§5.2).
4. **Hysteresis** (starting values, to be replaced by what stage A measures and what the boiler
   installer requires):

| Parameter | Start value | Why |
|---|---|---|
| `on_delay_s` | 120 | A single short `heat_required` blip does not start the burner |
| `off_delay_s` | 900 | Longer than the cloud bridge lag; rooms finishing a cycle do not stop the boiler |
| `min_on_s` | 600 | Against short cycling; most boilers want several minutes of burn |
| `min_off_s` | 300 | Same, on the other side |
| `max_switches_per_hour` | 4 | Hard cap: above it the relay stays in its current state and an alarm is raised |

Boilers usually have their own anti-short-cycling. These values sit on top of it and never
replace it. The owner and the installer set the real ones (§8).

### 4.4 Outputs

- `zigbee2mqtt/<relay>/set` `{"state": "ON" | "OFF"}`, only in *drive* mode (§7), confirmed by
  the relay's own state report within a timeout. On no confirmation, retry a bounded number of
  times, then raise an alarm. The coordinator never reports a state the relay has not reported.
- `<coordinator>/bridge/relays` (retained), in the shape `danfoss2mqtt` already publishes, plus the
  decision: `{"<relay>": {"rooms": [{"room_id", "name", "linked", "calling"}], "wanted": true |
  false | null, "reported": "ON" | "OFF" | null, "mode": "shadow" | "drive" | "override",
  "reason": "...", "ts": ..., "valid_for_s": ...}}`. The Companion reads it as it reads the
  cloud's today.
- `bridge/heat_demand` stays as it is (`z2m-cloud-parity.md` §5.7).

## 5. Safety

### 5.1 What the boiler installation must tell us first

Nothing below can be decided from software alone. Before any stage that switches a real boiler,
Rémi (with the heating installer if needed) should answer (§8):

- **Which terminals are used** at each relay: COM–ON (terminal 3, closed = heat) or COM–OFF
  (terminal 4, closed = no heat). And **which boiler input** they reach: room thermostat contact,
  external enable, or a heating-circuit pump.
- **What the boiler does with that input open**: heating off completely, or still frost
  protection and hot water? Weishaupt boilers usually keep their own frost protection, but that
  must be confirmed for these models and this wiring.
- **What else limits the boiler**: its own clock or weather compensation, a building management
  system, another thermostat in series.
- **Is there a manual bypass** at the boiler (a switch that forces the demand contact closed),
  usable by staff without tools?

### 5.2 Default state when something is down

Failures, from the controller's point of view:

| Failure | Relay keeps | What the controller does |
|---|---|---|
| Home Assistant down or restarting | Last command | Nothing changes: the coordinator is separate |
| Coordinator down | Last command (unless the relay has a timeout [H]) | Nothing; see the watchdog (§5.3) |
| Mosquitto down | Last command | Coordinator cannot read or command; on reconnect it re-evaluates and re-commands |
| Zigbee2MQTT down, or relay unreachable | Last command, or its own timeout [H] | Alarm; no state shown other than "unavailable" |
| Relay loses mains | De-energised: COM–OFF closed (terminal 4) [D] | Alarm when the relay goes unavailable |
| All heads' demand unknown | — | Apply `fail_state` (below) |

So **a relay with no timeout keeps its last state**, which may be off in cold weather. That is
the main risk, and the reason for the watchdog in §5.3.

**`fail_state`** is the state the controller asks for when its input is unknown. The proposal is
**ON** (heat) during the heating season. With ON, the boiler then regulates on its own controls
and the heads still close their valves room by room, so the cost is energy, not comfort or
pipes. OFF is defensible only if the boiler's own frost protection works with the contact open
(§5.1). This is the owner's call.

**Fail-safe in hardware (option, needs the installer).** Software alone cannot cover "the
coordinator died while the relay was off". Two hardware options would:

- **(a) Inverted wiring.** Wire the boiler demand to COM–OFF (terminal 4) and invert the logic:
  the relay is *energised* to block the boiler. Then a relay without power, or one that falls
  back to off, lets the boiler heat. This works only if the boiler treats that contact like a
  thermostat.
- **(b) Inverted wiring plus a timed command.** If the relay supports *On With Timed Off* [H],
  the coordinator sends "block the boiler for N minutes" and renews it every N/2 minutes while
  there is no demand. If the coordinator, Mosquitto or Zigbee2MQTT stops, the relay times out by
  itself and the boiler heats. This is a dead-man's switch held by the relay.

Both need a qualified installer and the boiler documentation. (b) also needs the bench test of
stage C. Without either, the fallback is the watchdog of §5.3 and the alarms of §5.4.

### 5.3 Watchdog and keep-alive

- The coordinator publishes `bridge/state` with a last-will (`offline`), as today [R]. The
  Companion raises a Repairs issue and a notification when it is `offline` for more than 5 minutes
  while a relay is in *drive* mode.
- **Keep-alive**: in *drive* mode the coordinator re-sends the wanted state every 15 minutes
  (within `max_switches_per_hour`, as it is the same state), so a relay that rebooted to a default
  is corrected within 15 minutes. It also re-sends at every coordinator start and every Zigbee2MQTT
  `bridge/state` `online`.
- **Independent watchdog in Home Assistant** (a template sensor or a small check in the Companion,
  not in the coordinator): if the relay reports OFF, its rooms have called for more than
  `alarm_off_with_demand_s` (30 min), and the outdoor temperature is below a threshold, notify.
  Home Assistant runs it in a different process from the controller, so the alarm still works
  when the coordinator is down.
- **Independent read-back** of the boiler. The `ebusd` add-on already reads the Weishaupt boilers
  (MCP `ebusd` connector). If one of their messages shows the external demand contact or the
  burner state, it can confirm, independently of Zigbee, that the boiler does what the relay says.
  Which message, if any, is to find in a read-only pass (§8).

### 5.4 Alarms

Each is a Home Assistant Repairs issue plus a notification, raised by the Companion from
`bridge/relays`, `bridge/state` and the relay's own topic:

1. Relay unavailable in Zigbee2MQTT for more than 10 minutes.
2. Commanded state not reported by the relay within 2 minutes after the retries.
3. Relay OFF while linked rooms call for more than 30 minutes (decision, wiring or relay fault).
4. Relay ON with no room calling for more than 2 hours (stuck relay, or a forgotten override).
5. `max_switches_per_hour` reached (short cycling held off).
6. Coordinator offline while a relay is in *drive* mode.
7. Decision unknown (§4.3, step 3) for more than 30 minutes: the fail state is applied.
8. Two writers: a `/set` to the relay that the coordinator did not send (seen as a state change it
   did not ask for). The same rule as "one producer per head attribute" in `z2m-cloud-parity.md`
   §4.

### 5.5 Manual override

- **Physical**: the relay's **CH** button is documented as an override [D]. What it does exactly
  (toggle, forced on, for how long) is measured on the bench in stage C [H]. A bypass at the boiler,
  if there is one (§5.1), is the override of last resort, and needs no software.
- **From Home Assistant**: a select `auto` / `force_on` / `force_off` per relay, forwarded to the
  coordinator as `bridge/request/relay/override`. Each forced state **expires** (default 4 h for
  `force_on`, 1 h for `force_off`) and goes back to `auto`. Administrator only, like the other
  write services. `force_off` is refused while the decision is "unknown" unless confirmed twice.
  An active override shows on the relay's card and as alarm 4 when it runs long.
- The override is the coordinator's state, published on `bridge/relays`. It survives a Home
  Assistant restart and is cleared at expiry even if Home Assistant is down.

## 6. Migration

### 6.1 Principles

- **One relay at a time**, and the one serving the least critical building first.
- **No two controllers on one boiler** unless they are wired so that it is safe (in parallel,
  i.e. OR: either relay can call for heat, neither can stop the other). Two relays driving the same
  contact through software is never allowed.
- The cloud relay keeps running until the local one has earned it: **shadow mode first**, with
  the decision compared against the real cloud relay for several days.
- **Rollback is always one known procedure away**, written down before the cut-over (§6.3).

### 6.2 Order

1. Stage A: observe the cloud relays (read only).
2. Stage B: build the relay object in the coordinator, closed, and run it in shadow mode against
   the cloud relays.
3. Stage C: a **spare** relay `014G2479` on the bench, paired to Zigbee2MQTT, connected to no
   boiler: interview, commands, timeouts, buttons, power cuts.
4. Stage D: the owner and the installer settle the wiring and `fail_state` (§5.1, §5.2).
5. Stage E: cut-over of the first relay, supervised, on site.
6. Stage F: a week of observation, then the second relay.

### 6.3 Cut-over and rollback for one relay (what Rémi does on site)

Before: record the relay's linked rooms (`danfoss2mqtt/bridge/relays` and the app), its
terminals, and the boiler's state. Choose a mild daytime slot in term time, with nobody relying
on a warm start that day, and staff told.

Cut-over:

1. Remove the relay from the Danfoss gateway in the app (or through the gated unbind,
   `roadmap.md` "Device lifecycle"). Note the time: from here the cloud no longer drives the
   boiler.
2. Factory-reset the relay (both buttons, 20–25 s [D]).
3. Open pairing on Zigbee2MQTT **only for this device's join**, press PROG, check the interview
   matches the bench relay of stage C, rename it in Zigbee2MQTT.
4. Close pairing. Arm the relay in the coordinator in *drive* mode, with only this relay listed.
5. Watch the first switch on and the first switch off, at the relay and at the boiler.

Rollback (target: under 15 minutes):

1. Disarm the relay in the coordinator.
2. Remove it from Zigbee2MQTT, factory-reset it, and add it back to the Danfoss gateway in the
   app ("Add sub-device").
3. Re-link its rooms (app, or `set_relay_room`), from the list recorded before.
4. Check in the app and on `danfoss2mqtt` that it follows demand again.

While the relay is between the two systems it keeps its last state. In cold weather, put it in
a known safe state first, with the CH override or the boiler bypass (§5.5).

## 7. Supervised trial plan

Each stage ships and runs alone, is closed by default, and ends with a record under
`docs/validation/` (no real identifiers or room names). Write stages follow
[`first-write-procedure.md`](first-write-procedure.md): the owner present and at the keyboard,
one device, a baseline read, an independent read-back, restore, disarm.

| Stage | Content | Writes | Gate to the next stage |
|---|---|---|---|
| **A** | Observe both cloud relays: DP `1` transitions, linked rooms' DP `162` / `170` / `3`, DP `138` / `139`, over ≥ 5 days including a weekend and a cold morning. Source: `danfoss2mqtt` topics and/or a cloud-MQTT listen (MCP `danfoss_mqtt_cloud_ecoute_*`) | **None** | Delays, aggregation and offline behaviour written down (§3.2 points 2–5), or recorded as not observable |
| **B** | Coordinator relay object (store, `bridge/relays`, decision, alarms), **shadow mode** only: computes `wanted`, sends nothing. Inputs from both prefixes. Synthetic tests. Then live in shadow against the cloud relays | **None** (no `/set` path armed) | Over ≥ 5 days, shadow `wanted` agrees with the cloud relay, every disagreement explained; alarms tested by simulation |
| **C** | **Bench**: spare relay paired to Zigbee2MQTT, a lamp or a meter on its contacts, no boiler. Interview (clusters, manufacturer name, generated exposes); ON/OFF with read-back; *On With Timed Off*; `power_on_behavior`; mains cut; Zigbee2MQTT stopped for 10 min, 1 h, 4 h (does it keep its state or time out?); CH and PROG buttons; coordinator *drive* mode on the bench relay only | Bench relay only | Behaviour on every failure of §5.2 measured; fail-safe option (§5.2 a/b or none) known to be possible or not |
| **D** | Owner and installer: wiring, `fail_state`, real hysteresis values, bypass. If the wiring changes, the installer does it | — (electrical work, not software) | Decisions recorded in this note (§8 answered) |
| **E** | Cut-over of relay 1 (§6.3), *drive* mode, owner on site, rollback ready. First on/off cycle watched at the boiler; `ebusd` read-back if available | Relay 1 | 24 h with no unexplained switch, no alarm left unanswered, rooms warm |
| **F** | Relay 1 in *drive* mode for a week, then relay 2 by the same procedure | Relay 2 | One week clean on each |

The first stage to run is **A**. It needs no code, no pairing, no write and no visit. Its result
decides the hysteresis values and whether shadow mode (B) can be judged.

## 8. Questions for Rémi

Installation (§5.1). These decide the fail-safe:

1. For each boiler, which relay terminals are wired (COM–ON 3, or COM–OFF 4), and to which boiler
   input (room thermostat contact, external enable, pump)?
2. With that input open, does the boiler keep frost protection, and hot water? Is there anything
   else in series (clock, building management, another thermostat)?
3. Is there a manual bypass at each boiler that staff can use? If not, is one wanted?
4. When the relay goes wrong, would you rather the boiler **heats** (cost: energy) or **stops**
   (cost: cold, frost risk)? The proposal is "heats" in the heating season.
5. Would the installer accept inverted wiring (§5.2 a), or the timed-command dead-man's switch
   (§5.2 b) if the bench shows the relay supports it?

Operation:

6. Minimum on and off times the boilers need, or should we take the installer's or the boiler
   manual's values?
7. Which relay goes first, and which building does it serve?
8. Should a single calling room start the boiler (`min_rooms_calling = 1`, as today we believe),
   or more?
9. Who gets the alarms (you only, or also the caretaker), and by which channel (HA app, mail)?

Hardware and tooling:

10. Can we buy one spare `014G2479` for the bench (stage C)? It also serves as a quick replacement.
11. Does any `ebusd` message show the external demand contact or the burner state? (A read-only
    look with the `ebusd` connector would tell.)
12. Do you have the relay's "Zigbee 3.0 API specification" Danfoss mentions on its support page?
    It would answer §2.2 before the bench.

## 9. Follow-ups, not in this design

- Fix the relay's code number in the repository: `014G2400` is the gateway; the relay is
  `014G2479` [D]. Keep `014G2400` as an accepted alias in `z2m_contract.RELAY_MODELS` for existing
  installs.
- Writing `heat_available` (`0x4030`) to Zigbee2MQTT heads from the relay state, and choosing
  their `heating_system_mode`, as the gateway may do (§3.2 point 5): only after stage A shows what
  the gateway does, and in its own trial.
- An external converter for the relay, if the generated definition is not enough (stage C), and
  then a definition contributed upstream to `zigbee-herdsman-converters`.
