# Real-hardware validation — results

**Dates:** 2026-11-18 / 2026-11-19 / 2026-11-20.
Real-hardware validation on a large real install (~99 heads, two homes). Anonymised: room names,
identifiers and site details replaced by neutral labels.
Plan: [`../real-validation-plan.md`](../real-validation-plan.md). Preheat curve reading (§3):
[`2026-11-preheat-curves.md`](2026-11-preheat-curves.md).

## Labels used in this report

| Label | Role |
|---|---|
| Building 1 / home 1 | First Danfoss home (holds Room A, Room B and most of the heads named here) |
| Building 2 / home 2 | Second Danfoss home |
| Room A | Isolated head (no room), main test head |
| Room B | Room with two grouped heads (corridor), writable room entity |
| Head C | Building 2 head; manual mode; window stayed open on the morning test |
| Heads D, E, F | Building 2 heads; window opened then closed on the morning test |
| Head G | Building 2 head; setback 5 °C / comfort 12 °C |
| Heads H, I | Washroom heads, setback mode, comfort 18 °C |
| Head J | Manual mode, active setpoint 5 °C, comfort 21 °C |
| Heads K, L | Same profile as Head J (manual, active 5 °C, comfort 21 °C) |
| Head M | Comfort = active = 5 °C; preheat OFF |
| Head N | Building 2 head, valve almost always fully open |
| Head P | Preheat OFF |
| Head Q | Preheat OFF, switched ON in the controlled trial |
| Head R | Preheat ON, switched OFF in the controlled trial |
| Room S | Three-head room at 5 °C (frost protection); head #3 offline |
| Sensor T | A Danfoss room sensor (not a head) |
| Head U | Isolated head (no room) following its own weekly schedule; test head of the DP 118 / 119 trial |
| relay 1 / relay 2 | Danfoss relays of Building 1 / Building 2 |
| Head V | Isolated head (no room), in comfort 08:30–17:30 on weekdays; test head of the 2026-11-20 trials (batch C, tunnel settings) |
| Area X | Home Assistant area holding four Danfoss heads paired directly to Zigbee2MQTT and one Danfoss room sensor (a transition test) |

Entity ids are written with placeholders, e.g. `switch.<room_a>_child_lock`.

---

Interactive session of 2026-11-18. The owner was present; the Danfoss iPhone app is the reference
view. Follows `../real-validation-plan.md`. Claude reads HA (through the HA admin and Danfoss
connectors) and MQTT (through an MQTT connector); the owner reads the app. Pass = the three views
agree.

## Prerequisites §0

| Prerequisite | State |
|---|---|
| `danfoss_ally_cloud` integration loaded (on the HA host, a Raspberry Pi) | ✅ `loaded` |
| deviceId distinct from the MCP connector's (coexistence, PR #59) | ✅ `distinct_device_id = true`, both sessions hold |
| MQTT publishing: mode / source / base topic | ✅ enabled during the session: `mqtt_mode = discovery` (was `off`), `mqtt_source = cloud`, base `danfoss_ally_cloud` |
| Mosquitto broker reachable | ✅ on the HA host, port 1883, mosquitto 2.1.2 |
| `enable_local` | ✅ true (preheat testable) |
| `enable_vacation_write` | ⛔ false — vacation gated (W-6 / TARGET 2 not tested) |
| `enable_head_unbind` | ⛔ missing from the options — §2b not exposed |

Write performed: `mqtt_mode off → discovery` (write batch, explicit approval from the owner).

### Publishing structure confirmed (discovery, source cloud)
- State: `danfoss_ally_cloud/<devId>` → JSON `{temperature, setpoint, battery, valve_opening, window_open}`
- Availability: `danfoss_ally_cloud/<devId>/availability` → `online` / `offline`
- 198 topics (2 per device). Discovery configs under `homeassistant/<component>/danfoss_<devId>_<key>/config`.
- ⚠️ False friend: 660 topics `danfoss_l/…` (and `*_local` entities) come from a **separate local
  bridge belonging to another project** on the same host, **not** from our integration. Excluded.

## Test head

- **Room A** (isolated head) — its own gateway.
- Entities of our integration: `climate.<room_a>_2`, `sensor.<room_a>_temperature_2`,
  `sensor.<room_a>_battery_2`, `sensor.<room_a>_valve_opening_2`,
  `sensor.<room_a>_fault_code`, `binary_sensor.<room_a>_window`,
  `binary_sensor.<room_a>_online`, `switch.<room_a>_child_lock`,
  `switch.<room_a>_open_window_detection_2`, `switch.<room_a>_pre_heating`.
- MQTT entities auto-created (discovery): `sensor.<room_a>_temperature_3`,
  `…_battery_3`, `…_valve_opening_3`, `sensor.<room_a>_setpoint`, `binary_sensor.<room_a>_window_2`.
- (MTrab's `danfoss_ally` entities, without suffix, and the bridge's `*_local` entities also coexist.)
- Type: "Danfoss Ally™ Radiator Thermostat". Firmware: ZigBee Module **0.2.2**;
  Product Version 1.0.0; RSSI **−75 dBm**.

## §1 — Read (R-1), 2026-11-18 ~20:12

| Quantity | App (ref.) | HA `danfoss_ally_cloud` | MQTT discovery | Verdict |
|---|---|---|---|---|
| Measured temperature | ~18.7 | 18.7 (`current_temperature` / `sensor…_temperature_2`) | `temperature` 18.7 | ✅ |
| Setpoint | **14** (setback) | attribute `setpoint` **21** (= comfort); `setpoints`={comfort 21, setback 14, manual 8, pause 5, holiday 14.5}; `mode`=setback | `setpoint` **21** | ❌ **MISMATCH** |
| Valve / heating | **not heating** | `valve_opening` 1 %; **`hvac_action` = heating** | `valve_opening` 1 % | ❌ **MISMATCH** (hvac_action) |
| Battery | — | 68 % | `battery` 68 | ✅ |
| Window open | — | `off` | `window_open` false | ✅ |
| Online | — | `on` | availability `online` | ✅ |
| Fault | — | `none` | (not published) | ✅ |

### Anomaly found (R-1) — single root cause
The "active" setpoint exposed by the integration does **not** take the current mode/slot into
account. In `setback` mode it should be the setback value (14), but the integration publishes
`comfort` (21), both in the climate's `setpoint` attribute **and** in the MQTT JSON `setpoint`.
The same error contaminates `hvac_action`: 18.7 °C compared with 21 (comfort) → `heating`. With the
real active setpoint (14) the room is above setpoint → it should be `idle`/`off` (the app confirms:
not heating, valve 1 %).

→ **Root cause confirmed by the raw statuses**: the cloud already exposes the right values; the
integration does not use them.
- `OccupiedSetpoint = 1400` (= 14.0 °C) = the real active setpoint → **to publish as `setpoint`**,
  instead of `temp_set` / `at_home_setting` (210 = comfort).
- `work_state = NoHeat` (and `pi_heating_demand = 1`) = the real heating state → **`hvac_action`
  must follow `work_state`**, instead of being recomputed locally (18.6 vs comfort 21 → wrongly
  heating).
- Other useful codes: `mode = leaving_home` (setback), `SetpointChangeSource = Schedule`,
  `at_home_setting=210`, `leaving_home_setting=140`, `holiday_setting=145`, `pause_setting=50`.

To fix in the coordinator/climate + `mqtt_publisher` (outside this validation session).
Directly affects W-1 (comfort write): interpret it accordingly.
→ Fix session started: `fix-consigne-active-hvac`, dedicated branch.

## §1 — Read R-3 (heat demand / valve), 2026-11-18 ~21:06

The owner raises Room A's setpoint to **21** (max = the head's upper bound `upper_temp`=210) in
manual mode. Baseline before: valve 1 %, `pi_heating_demand` 1, `work_state` NoHeat.

| View | Valve | pi_heating_demand | mode / active setpoint | work_state |
|---|---|---|---|---|
| Cloud **per-device route** (`danfoss_appareil`) | **82 %** | **82** | manual / 21 (`OccupiedSetpoint` 2100) | **Heat** |
| Cloud **list/bulk route** (`danfoss_appareils` with refresh) | **1 %** | — | setback / 14 (`consigne_active`) | — |
| HA `sensor…_valve_opening_2` | **1.0 %** (frozen, updated 20:10) | — | — | — |
| MQTT `valve_opening` | **1.0 %** (frozen) | — | — | — |

### Anomaly found (R-3) — source freshness
The coordinator polls **`async_list_devices`** (list/bulk route, [coordinator.py:57]), which **lags
badly**: several minutes after the change, and despite `refresh=true`, it still shows the schedule
state (setback / 14 / valve 1 %), while the **per-device** route (and the physical head) are at
manual / 21 / valve **82 %**. The MCP connector reads the per-device route → fresh.
Consequence: fast-changing values (valve, demand) — and the **write round-trips** (W-1…W-5) — are
not reflected in time in the integration or in MQTT.
→ Separate from the R-1 mapping bug. Option: for recently commanded heads, query the per-device
route (more API calls), or accept the latency and document it. To decide (API load vs
responsiveness), outside this session.

**Clarification (fix session, Frida capture of the Tuya SDK):** the bulk payload
`tuya.m.my.group.device.list` **does contain** DP 171 (`OccupiedSetpoint`, hundredths /100) and DP 3
(`work_state` Heat/NoHeat), next to DP 2/16/118/119/170. So the **R-1 mapping fix works on the
bulk route** (the per-device route is not needed to *select* the active setpoint). The capture even
shows the R-1 case: head at_home, DP 171=2100, DP 3=NoHeat, valve DP 170=2.
⚠️ Do not confuse: the **presence** of these DPs in the bulk payload ≠ their **freshness**. R-3
remains a freshness problem of the `device.list` endpoint (values lag behind the per-device route),
independent of the mapping. Both are needed for good responsiveness.

R-3 verdict: **valve/demand do rise on the real head + per-device cloud route (82 %)**, but there is
a **HA/MQTT mismatch** due to bulk-route latency. To reconfirm later by re-reading whether the bulk
route catches up.

## §1 — Read R-2 (window detection), 2026-11-18

**Validation finding:** the **Danfoss iPhone app does not show** the per-head "window open" flag.
So the reference view has **no counterpart** for `window_open`: this line cannot be validated
against the app. The flag exists on the cloud side (`window_state` in the raw status) and is exposed
by HA (`binary_sensor.<room_a>_window`) and MQTT (`window_open`). Validation falls back to cloud
(per-device route) ↔ HA ↔ MQTT, without the app leg.

**Postponed to the next morning (2026-11-19):** when the site opens, morning airing naturally puts
**several valves** into window-open — an opportunistic R-2 test with no manipulation, on several
heads, comparing cloud ↔ HA ↔ MQTT. To group with preheat §3 (P-1…P-3), also read on the morning
curves, and with a re-check of the bulk latency (R-3: see whether HA/MQTT caught up with the valve).

### R-2 — result 2026-11-19 (morning airing) ✅

At 08:06, `danfoss_sante` reports **4 heads** with window open (Building 2): Head C, Head D,
Head E, Head F. MQTT `window_open` = **true** for all 4 → cloud ↔ MQTT agreement **4/4** (valve 1 %
everywhere, heating off). Version in place = **pre-fix** (main not deployed).

**Transition captured (no manipulation)** between 08:06 and 08:14, end of airing:

| Head | window_open (MQTT) | valve | |
|---|---|---|---|
| Head E | true → **false** | 1 % → **98 %** | window closed, heating resumed |
| Head D | true → **false** | 1 % → 56 % | same |
| Head F | true → **false** | 1 % → 12 % | same |
| Head C | true (unchanged) | 1 % | stays open (control) |

**Fresh per-device route** confirmation on Head E: `fenetre_ouverte=false`,
`window_state=close`, `ouverture_vanne=98`, `pi_heating_demand=98`, `work_state=Heat` → **matches
MQTT**.

**R-2 verdict: ✅** the flag goes `true→false` **and** the valve reopens, consistent between the
integration (MQTT) and the fresh cloud. No app leg (flag not shown — established the day before).

**R-3 observed live:** at 08:14, `danfoss_sante` (**bulk** route) **still lists all 4** with window
open, including Head E, already closed according to the per-device route + MQTT. A clear
illustration of the `device.list` latency → for a live transition, trust the **per-device route +
MQTT**, not `danfoss_sante`. (PR #66, targeted freshness, merged but gated off / not deployed.)

**Setpoint note:** MQTT `setpoint` = 21 everywhere is **not** evidence of the R-1 defect this
morning: `OccupiedSetpoint` = 2100 (21 °C), and the active morning slot **is** 21
(comfort/at_home). The R-1 defect only shows when active ≠ comfort (see Room A the day before:
active 14 vs comfort 21).

## §1 — Extent of the R-1 bug across the fleet (autonomous tests, 2026-11-18 ~21:51)

Comparison of **active setpoint (cloud, `consigne_active`)** vs **published MQTT `setpoint`**, on a
discriminating sample of 8 heads (varied modes and setpoints):

| Head | mode | active setpoint (cloud) | MQTT `setpoint` | verdict |
|---|---|---|---|---|
| Room A | setback | 14 | 21 | ❌ |
| Head G | setback | 5 | 12 | ❌ |
| Head H | setback | 7 | 18 | ❌ |
| Head I | setback | 12 | 18 | ❌ |
| Head C | manual | 21 | 21 | ✅ (comfort = active) |
| Head J | manual | 5 | 21 | ❌ |
| Head M | setback | 5 | 5 | ✅ (comfort = active) |
| Head N | setback | 14 | 21 | ❌ |

**Conclusion**: MQTT always publishes the **comfort/at_home** setpoint (a per-room value: 21, 18,
12…), never the **active** setpoint. They only coincide when comfort = active. At the evening
reading, **~95 of the 99 heads are in `setback` mode** → the R-1 mismatch affects **almost the whole
fleet**. Confirms a deterministic bug (setpoint selection), not an isolated case. Serves as the
**baseline for re-checking after PR #65 is merged**.

## §1 — R-1 re-validation after deploying the fix (2026-11-19 ~08:45) ✅

**Deployment**: `danfoss_ally_cloud` deployed to the Pi at 08:27:50 (write batch, connector tool
`ha_composant_deployer_preparer`, source = branch `docs/real-validation-plan` = commit `67b6c1e`,
R-1 code identical to PR #65). Core restart started at 08:30 (task: config ✅, restart ✅ 141 s,
last step "HA back up" ❌ `state = None` after 600 s — a **false negative of the checker**: HA
`running`, integration `loaded`, new code active). **Not on the Pi**: #66 (R-3), #63/#64 (unbind) —
gated off.

**Method pitfall**: the obvious test heads were **not discriminating** this morning — Room A and
Head G are in the comfort slot (`OccupiedSetpoint` = comfort; Head G = 12 °C and
`work_state=Heat`). The connector's `danfoss_appareils` reported Head G as "setback / 5" at 08:36:
**stale** (bulk route). Discriminating heads were picked from the raw cloud reading of 08:43
(`OccupiedSetpoint` ≠ `at_home_setting` **and** `work_state` disagreeing with temp vs comfort):

| Head | cloud state (08:43) | MQTT `setpoint` yesterday | MQTT `setpoint` now | HA `hvac_action` |
|---|---|---|---|---|
| Head J | manual, active **5**, comfort 21, 14.4 °C, NoHeat | **21** ❌ | **5** ✅ | **idle** ✅ |
| Head K | manual, active **5**, comfort 21, 14.2 °C, NoHeat | — | **5** ✅ | — |
| Head L | manual, active **5**, comfort 21, 14.1 °C, NoHeat | — | **5** ✅ | — |

**R-1 verdict: ✅** published setpoint = active setpoint (DP 171), `hvac_action` = `work_state`.

Remarks (not blocking, possible follow-ups):
- HA attribute `setpoints.setpoint` = **21**: it is the raw per-DP table (`_SETPOINT_DPS`, key
  `setpoint` = DP 16 / `temp_set`), not the active setpoint → misleading name.
- The **head** climate has `supported_features: 0` → HA does not expose `temperature`: the active
  setpoint is only visible in HA through the MQTT entity `sensor.<head>_setpoint`.
- Connector restart checker: `state = None` for 600 s while HA was running.
- Origin of the 08:30 restart not established (neither the validation session nor the connector,
  according to their reports).

## Deployment of full `main` (2026-11-19 ~08:40–08:58) ✅

- `main` (`f9827b5`: R-1 #65, R-3 #66, unbind #63/#64) **put on the Pi around 08:4x** by another
  session (direct approval from the owner), from a clean checkout of `origin/main`.
  The confirm **expired on the client side**: the files were pushed (token then "already used"),
  but **no entry in the connector's log** → untracked deployment, identified afterwards by comparing
  fingerprints (the 08:27 batch = `67b6c1e`; the Pi = `main`, 41 identical files; a preview from
  `67b6c1e` proposed ~14).
- **Core restart** at 08:55:15 (owner's approval): config ✅ 34 s, restart ✅ 155 s. Just before,
  re-checked that the disk = `main` (no deployment in between). The confirm also expired on the
  client side, but the detached task ran.
- **Proof that `main` is loaded**: the options form now exposes `post_command_refresh` (R-3) and
  `enable_head_unbind` (missing the day before), both `false`.
- Origin of the 08:30 restart: most likely another session working on another integration on the
  same host (a backup and another add-on's options changed at 08:27).

- **R-3 option enabled**: `post_command_refresh` false → **true** at 09:08 (write batch, owner's
  approval), other options unchanged. A first attempt (08:59) was dropped with no effect: it waited
  on the lock held by the faulty restart checker. Integration reloaded → `loaded`; MQTT still
  correct (Head J `setpoint` 5, `online`). R-3 still **to validate** with a write round-trip (W-x).

## §2 — W-1 (comfort setpoint) + R-3 validation, 2026-11-19 ~09:21 ✅

Test room **Room B** (pid `03wvrwpv`, 2 heads, corridor; Room A has no writable room entity).
Lever: `climate.set_temperature` on the **room** climate `climate.<room_b>` (comfort mode → the
group's durable `at_home` setpoint) — this is the path that calls `note_commanded` (R-3). Write
21 → **20.5** at **09:20:54** (write batch, owner's approval). Room at ~21.7 °C, no noticeable
effect.

| Time | Per-device cloud (#1/#2) | HA room climate | MQTT `setpoint` (2 heads) | Bulk route (connector) |
|---|---|---|---|---|
| T0 + ~10 s | `at_home_setting` 205 ✅, `OccupiedSetpoint` still 2100 | `setpoints.comfort` 20.5, `temperature` 21 | 21 / 21 | — |
| ~09:22–09:23 | `OccupiedSetpoint` **2050** | `temperature` **20.5** (updated 09:22) | **20.5 / 20.5** ✅ | consigne_active **21** (stale) |

- **W-1 ✅**: the written comfort setpoint appears in the cloud, HA and MQTT.
- **W-7 (W-1) ✅**: MQTT reflects the new active setpoint ~2 min after the write.
- **R-3 ✅**: the integration reflects the change within ~1–2 readings (90 s scan), while the bulk
  route still shows 21 at the same moment — recovery through the per-device route works. (The day
  before, without R-3, a round-trip on Room A was never reflected.)
- **R4 ✅**: the room's weekly schedule, re-read after the write = **identical** to the reference
  state (Mon/Tue/Thu/Fri 08:30–17:30 comfort; Wed/Sat/Sun empty). To cross-check in the app.
- Head-specific delay: the active setpoint (DP 171) only switches after the head syncs
  (`at_home_setting` written immediately, `OccupiedSetpoint` ~1–2 min later).
- Code inconsistency found: the comfort/setback `number` entity (`DanfossRoomSetpoint`) does the
  same write **without** `note_commanded` → no R-3 on that path.
- **Restore**: back 20.5 → **21** at 09:23:54 (write batch, owner's approval). At ~09:26: cloud
  `at_home_setting` 210 / `OccupiedSetpoint` 2100, HA target 21 (updated 09:25), MQTT 21 / 21,
  schedule still identical to the reference. Second R-3 round-trip ✅ in ≤ ~2 min.

## §2 — W-2 (setback setpoint), 2026-11-19 ~09:42 ✅ (with a transient effect)

Same room (Room B). All rooms are in the comfort slot from 08:30 to 17:30 → no room in setback to
make the active setpoint switch; W-2 done through the entity `number.<room_b>_setback_setpoint`
14 → **13.5** (path without R-3).

- 1st attempt (09:28:35) **lost with no effect**: it waited on the lock held by a core restart
  started by another session (deployment of another integration on the same host, 09:27:58), and
  was dropped at 09:33:35. Write collision between sessions on the Pi, reported.
- 2nd attempt **09:42:15** (write batch, owner's approval).

| Time | Cloud (#1 and #2) | HA `number` | MQTT `setpoint` |
|---|---|---|---|
| T0 + ~15 s | `leaving_home_setting` **135** ✅; ⚠️ `OccupiedSetpoint` **1350**, `SetpointChangeSource` = **Externally** (mode `at_home`, `temp_set` 210) | **13.5** ✅ | 21 |
| ~09:45 | `leaving_home_setting` 135; `OccupiedSetpoint` **2100**, source **Schedule** | 13.5 | 21 ✅ |

- **W-2 ✅**: setback setpoint written (cloud + HA).
- **MQTT ✅**: stays at 21 (room in comfort); the transient excursion was not published (bulk).
- **R4 ✅**: schedule identical to the reference.
- ⚠️ **Undocumented behaviour**: publishing the setback (`{"109": …, "119": …}`) makes the head
  apply the setback value **immediately** as the current setpoint (source `Externally`), even in a
  comfort slot; rewriting the schedule (R3) brings it back to the slot ~1–3 min later. No thermal
  effect observed (corridor at ~21.5 °C). To add to the contract (§4.2, "Setback setpoint" row);
  hypothesis: DP 109 = "now" setpoint, DP 119 = setback setting.
- **Restore**: setback 13.5 → **14** at 09:46:06 (write batch, owner's approval). At ~09:49: both
  heads `leaving_home_setting` 140, `OccupiedSetpoint` 2100 (source Schedule), schedule identical.
  (HA unavailable at the same moment: a new deployment of the other integration + core restart at
  09:48 by the other session.)

## §2 — W-3 (child lock, DP 30), 2026-11-19 ~09:59 ❌ not applied

**Isolated** head Room A (no room; the integration's switches write per head through
`tuya.m.custom.wkf.settings.change`, resType 1, `gwId = meshId`). Reference: `child_lock` true
(cloud, HA `on`, app "enabled"). `switch.turn_off` at **09:59:01** (write batch, owner's approval).
Pi lock checked free before (the other integration's restart finished at 09:51).

| Time | Cloud `child_lock` | HA switch | App (owner) |
|---|---|---|---|
| T0 + ~10 s | true | on (updated 09:50) | — |
| T0 + ~3 min | true (head active: 20.9 °C, Heat, valve 39 %) | on | **enabled** |
| T0 + ~10 min | true (21 °C, valve 36 %) | on | — |

- **W-3 ❌**: request accepted (service `ok`, no error raised), **never applied** to the head after
  10 min (beyond the R7 delay of 5–10 min for settings).
- **Consistency ✅**: the three views stay aligned on the real state (locked) — the integration
  does not lie (no optimistic state).
- Matches the warning in the code (`async_write_setting`: "real effect to confirm; some settings via
  this path did not reach all isolated heads"): first real-hardware data point, **negative**, for
  `gwId = meshId` addressing on an isolated-head setting.
- Nothing to restore; **to re-check later** (a late application is possible → re-lock).
- W-4 (window detection, DP 116): the cloud **switch** uses the same path; the
  `set_window_detection` **service** goes through the local tunnel.

### W-3 — diagnosis (2026-11-19 ~10:13–10:24)

Hypothesis: since PR #35 (`c6511a6`), the integration writes settings with **`gwId = meshId`**
(justified by an earlier trial that was about a **schedule** write), while the MCP connector uses
**`gwId = devId`** (validated once on real hardware: screen orientation on an isolated head).

Discriminating test (owner's approval): the same DP 30 → false write on Room A through the connector
(`danfoss_tuya_reglage_*`, `gwId = devId`) at ~10:13; request accepted (`reponse: true`).

| Time | Cloud `child_lock` | Head active? |
|---|---|---|
| T0 | true | yes |
| T0 + ~4 min | true | yes (valve 36 %) |
| T0 + ~10 min | **true** | yes (20.9 °C, Heat, valve 35 %) |

**Conclusion**: it also fails with `gwId = devId` → **addressing is not the cause**.
`tuya.m.custom.wkf.settings.change` does not apply (or not reliably) the settings of an **isolated**
head — consistent with the connector's finding of 15/11 (DP 116: 0/7 isolated heads in 8 min).
What works: the **per-room** setting (`s.m.dev.group.dp.publish`, grouped heads) and the **local
tunnel**. The local read of Room A does not expose the child lock (no on-head proof possible for
DP 30).

Consequences / follow-ups for the integration:
- the `child_lock` / `window_detection` switches of **isolated heads** must not show as writable
  until this path is proven ("unavailable rather than lying" principle); for window detection,
  route to the local tunnel;
- for **grouped heads**, write the setting through the room (group publish, proven) instead of
  per-head `settings.change`;
- the contract §4.2 and the `async_write_setting` warning must be updated with this result.
Nothing to restore (no write applied); check later that none is applied late.

## §2 — W-4 (window detection, DP 116) through the local tunnel, 2026-11-19 ~10:22 ✅

Isolated head Room A (its gateway). Integration service
`danfoss_ally_cloud.set_window_detection {target: {type: device, id}, enabled: false}` — written
through the **local tunnel** (not `settings.change`). Called through the Supervisor: **no**
`not_admin` refusal. 10:22:44, write batch (owner's approval); response in 0.1 s.

| View | Before | After | Delay |
|---|---|---|---|
| Head (local read, authoritative) | `detection_fenetre` true | **false** | immediate (re-read at T0 + ~20 s) |
| Cloud (per-device route) | `window_toggle` true | **false** | < 1 min |
| HA `switch…_open_window_detection_2` | on | **off** (updated 10:25) | ~2.5 min |
| App | (owner) | to confirm | |

- **W-4 ✅** through the local path, where the cloud path (W-3, `settings.change`) applies nothing.
- The head then **reports** the setting up to the cloud: the HA switch (which reads the cloud)
  follows on its own.
- Inconsistency window of ~2.5 min where the HA switch still shows `on` while the head is `off`
  (this path does not call `note_commanded` → no R-3; the bulk route catches up).
- The rest of the head is unchanged (schedule, setpoints, settings re-read locally).
- **Restore**: re-enabled at 10:28:35 (write batch, owner's approval) → head `detection_fenetre`
  true (re-read immediately), cloud `window_toggle` true, HA `on` (updated 10:28, < 1 min this
  time). W-3 check along the way: `child_lock` still **true** (neither of the two
  `settings.change` writes was applied late).

## §2 — W-5 (override, then back to schedule), 2026-11-19 ~10:34–10:49 ✅

Scope: the W-5 **that the integration exposes** — `set_override` / `clear_override`, through the
local tunnel (DP 171 "setpoint now", until the next schedule change; **no** manual mode, so R4 does
not apply). The scenario "manual → `restore_schedule` (rewrite the schedule, then `at_home`)" is not
covered here (the integration does not expose switching to manual).

Isolated head Room A (its gateway), comfort slot 21. Head schedule read locally before
(Mon/Tue/Thu/Fri 00:00→14, 08:30→21, 17:30→14; Wed/Sat/Sun 14).

| Step | Head (local, authoritative) | Cloud | MQTT | HA head climate |
|---|---|---|---|---|
| Before | setpoint 21, source 1 (schedule) | `OccupiedSetpoint` 2100 | 21 | — |
| `set_override 19` 10:34:13 (write batch) | **19**, source 2 (external) at T0+~20 s; schedule **identical** | **1900**, `Externally` | **19** (≤ ~3 min) | `hvac_action` idle (21 > 19) |
| `clear_override` 10:46:37 (write batch, 4.7 s) | **21**, source 2; schedule **identical** | **2100**, `Externally`, `work_state` Heat | **21** (≤ ~2.5 min) | — |

- **W-5 ✅**: the override applies in the head in ~20 s; returning to schedule restores the planned
  setpoint (21); **the head's schedule is never modified** (re-read locally).
- The source stays "external" after `clear_override`: expected (the override equals the schedule
  setpoint and expires at the next change, 17:30). **To re-check after 17:30**: back to source
  schedule.
- **W-7 (W-5) ✅**: MQTT follows within a few minutes; this path does not call `note_commanded`
  (no R-3). The head climate does not show the setpoint (UX limit already noted).
- Access: call through the Supervisor accepted (no `not_admin` refusal), like W-4.

## §3 — Preheat (P-1…P-3), curves of 2026-11-19 — see [`2026-11-preheat-curves.md`](2026-11-preheat-curves.md)

Read-only, by a dedicated session (no write). Summary:
- **P-1 ✅**: 70 usable heads with preheat ON; valve ≥ 10 % from 52 to 448 min before the slot
  (median 252 min); the cloud "Pre-Heating" flag (MTrab) goes ON at the same time.
- **P-2 ✅ (2 heads)**: Head P and Head Q (preheat OFF) open at 08:34 (slot + 4 min), with no
  anticipated ramp. Limit: already OFF before the window → the switch → 0x0025 write path is **not**
  validated.
- **P-3 ✅ partial**: preheat switch `unavailable` head by head when the tunnel does not answer
  (online = on, no fake ON/OFF); total tunnel outage not observed.
- Annexes: preheat very early (up to 7 h 50; temperature rising from ~06:00, boiler room?); orphan
  switch entities to clean up.
- **Controlled trial started** (owner's approval): preheat OFF on Head R (write batch) and ON on
  Head Q (write batch), 10:58, ~7 s each through the tunnel. **Switch → 0x0025 write validated on
  real hardware**: re-read locally right away, Head R `pre_chauffage` true → **false**
  (`mode_programmation` 3 → 1), Head Q false → **true** (1 → 3), schedules and setpoints unchanged;
  still in place at ~11:04 (no rollback).
  HA switches updated only at **11:11** (~13 min): the state comes from the local survey (15 min,
  ~8 s/head), no optimistic state after a write.
  To read on **Friday 20/11** (08:30 slot): Head R must stay closed until ~08:30 without the cloud
  flag; Head Q must open before 08:30 with the flag. Then **restore** (Head R ON, Head Q OFF) after
  09:00.

## Deployment of `main` `f1cf051` (#67 + #68), 2026-11-19 ~11:14 ✅

Owner's approval ("Deploy right away", during working hours). Clean checkout of `origin/main`
(detached worktree, HEAD `f1cf051`, not dirty), Pi lock free. Deployment 11:14:33 (write batch,
+0 ~4 −32 caches, check OK on 41 files), then core restart (confirm expired on the client side,
detached task ran). Integration `loaded`.

- **#67 ✅** on `climate.<room_a>_2`: `active_setpoint` 21, `temperature` 21 now exposed
  (`supported_features` 0 → **1**), `setpoints.temp_set` 21 + deprecated alias `setpoint`.
- **#68 ✅** (relays per building, "Offline"): checked visually by the owner in the panel —
  relay 2 under Building 2, relay 1 under Building 1, both "Offline".

## Deployment of `1.1.0-rc1` (`b246f6d`, #69 per-room / tunnel settings), 2026-11-19 ~12:20

Owner's approval. Clean checkout of tag `1.1.0-rc1` (= `main` `b246f6d`, manifest 1.1.0, not
dirty), lock free. Deployment 12:20:22 (write batch, +0 ~5 −32 caches, OK on 41 files), then core
restart (confirm expired on the client side, task ran).

#69 routing checked on the entities:
- Room A (isolated): `switch…_child_lock` **unavailable** ✅; window detection `write_path:
  local`, `write_scope: head` ✅.
- Room B (room, 2 heads): `child_lock` `write_path: room`, `write_scope: room`,
  `room_head_count: 2` ✅.

**Write through the room (W-3 fixed)**: `switch.turn_off` on `switch.<room_b>_1_child_lock` at
12:25:23 (write batch, owner's approval).
- Cloud: `child_lock` **false on BOTH heads** from T0 + ~15 s ✅ (where per-head
  `settings.change` failed after 10 min).
- HA: switch **#2 → off** (updated 12:25) ✅, but switch **#1 (the one actuated) still `on`**
  (updated 12:23) at the same moment ⚠️ — the written entity lags behind its neighbour. To watch /
  fix before the final `1.1.0`.
- App ✅ (owner: Room B as expected). Version **1.1.0** shown in the panel ✅ (owner).
- **Restore**: `switch.turn_on` #1 at 12:26:00 (write batch) → cloud `child_lock` **true on both
  heads** immediately ✅. HA at 12:26: #2 `on` ✅ but #1 `off` (= the value of the previous write);
  **#1 resyncs to `on` at 12:27** (next reading).
- **Finding**: the **actuated** entity is **one write behind** for ~1 reading (the refresh that
  follows the write reads its head before the cloud has taken it; the neighbouring head, read in the
  same refresh, is right). Transient (~1 min), not blocking; preferably to fix before the final
  `1.1.0` (optimistic state after a successful write, or a delayed re-read).
- **W-3 ✅ through the room** for grouped heads; isolated head: child lock unavailable (no proven
  path), window detection through the tunnel (W-4 ✅).

## Deployment of `1.1.0-rc2` (`50b4ed3`, #73 R-3 settle delay), 2026-11-19 ~13:19 ✅

Owner's approval. Clean checkout of tag `1.1.0-rc2` (= `main` `50b4ed3`, manifest 1.1.0, not dirty;
only addition vs rc1: #73). Deployment 13:19:01 (write batch, +0 ~2 −32 caches, OK on 41 files),
then core restart (confirm expired on the client side, task ran; HA back at 13:21). R-3
(`post_command_refresh`) ON.

Test (owner's approval): `switch.turn_off` on `switch.<room_b>_1_child_lock` (room, 2 heads) at
13:22:04 (write batch).

| Time | Switch #1 (actuated) | Switch #2 | Cloud #1 |
|---|---|---|---|
| T0 + ~3 s | on (updated 13:21) | — | — |
| T0 + ~20 s | **off** (updated 13:22) ✅ | **off** (updated 13:22) | `child_lock` false |

- **#73 ✅**: the actuated switch agrees within ~15–20 s (settle delay), instead of being one write
  behind until the next reading (rc1 finding, 12:25–12:27).
- **Restore**: `switch.turn_on` at 13:23:01 (write batch) → at T0 + ~22 s, switches #1 and #2
  **on** (updated 13:23), cloud `child_lock` true ✅ — same behaviour in the reverse direction.

## Tuya cloud MQTT listening probe (R&D, PR #71 not merged), 2026-11-19 ~13:48–14:04 ✅ coexistence

Owner's approval, a single session on the Pi (the R&D session stepped back). Code audited before
deployment: the probe (`CloudMqttListener`) has **no send path**; the MQTT write path present in the
same commit (`CloudMqttLink`, `cloud_mqtt` path of the switches) is **closed twice**
(`enable_cloud_mqtt` OFF by default, link wired to `None`). CI green.

- `cb05109` deployed 13:48 (write batch) + restart; then `3313f7f` (same code + 2 log lines for the
  verdict, to read it without the diagnostics) 13:52 (write batch) + restart.
- The owner opens the Danfoss app on iPhone; option `cloud_mqtt_probe` → true at 13:58:03 (write
  batch).
- **13:59:34 — `cloud-mqtt probe: CONNACK rc=0 (Connection Accepted.)`** with the integration's own
  session (distinct deviceId).
- **iPhone app: still connected** (owner).
- Option → false at 14:04:16 (write batch) → `cloud-mqtt probe stopped (unload): connack_rc=0
  received=426 decoded=426 last_error=None` (≈ 4 min 40 of listening, 100 % of frames decoded).

**Verdict: connection is PER SESSION** — the broker accepts the integration's session in parallel
with the app's, without kicking it out. The MQTT channel (read, and later writing the settings of
isolated heads) is **viable**; the decoder holds on 426 real frames.
Hygiene: the paho thread name (`paho-mqtt-client-<client id>`) exposes the MQTT client id in the HA
log (the diagnostics redact it) — to fix.
Back: rc2 `50b4ed3` redeployed at 14:04:19 (write batch, +0 ~7 −36: probe code removed); core
restart by the owner. **Checked ~14:10**: integration `loaded`, the `cloud_mqtt_probe` /
`enable_cloud_mqtt` options have disappeared from the form (rc2 loaded), R-3 still ON; options
fingerprint identical to the one before the probe.
Hygiene fix applied by R&D: paho thread renamed (commit `e0334bc` on #71).

## §2 — W-6 (vacation "away", TARGET 2), 2026-11-19 ~14:12–14:16 ✅

rc2 on the Pi. The owner confirms in the app: **no vacation scheduled** on Building 1 (required:
`cancel_vacation` applies to the whole home). Test designed **with no thermal effect**: a Saturday
(schedule already in setback 14 °C all day), 14.5 °C = the heads' current `holiday_setting`, a
single room (corridor).

- `enable_vacation_write` → true at 14:12:48 (write batch, owner's approval).
- `set_vacation` at 14:14:35 (write batch): home 1 (Building 1), rooms = Room B,
  2026-12-05 08:00 → 2026-12-05 18:00, 14.5 °C → response ok in 1.6 s.
- **HA, immediately**: `binary_sensor.<home_1>_holiday_active` attribute `detail` =
  `{startDate 2026-12-05, startTime 08:00, endDate 2026-12-05, endTime 18:00, temperature 145,
  roomList [Room B], isRunning false, vacationType 3}` (dates sent as YYYYMMDD); `sensor…_holiday_setpoint` 14.5.
- **App ✅** (owner): vacation visible on Room B, dates and temperature as expected.
- `cancel_vacation` at 14:15:34 (write batch) → ok; HA at 14:15: `holiday_active` **off**, no
  more `detail`, `holiday_setpoint` unknown ✅.

- `enable_vacation_write` → **false** at 14:16:09 (write batch): back to the default state.

**W-6 verdict ✅** (plan.leave + cancel validated on real hardware, immediate HA round-trip). Still
untested: `set_vacation_at_home` (plan.athome) and `end_vacation` (leave.now, vacation in
progress).

⚠️ **Defect**: `binary_sensor…_holiday_active` turns **on** for a **scheduled** vacation
(`isRunning: false`) — it treats "detail not empty" as "active". Fix: `is_on =
detail.isRunning` (and expose "scheduled" separately). Note: `vacation.detail` therefore also
contains scheduled vacations (the initial empty detail did prove that no vacation was scheduled).

## First Tuya cloud MQTT write (DP 30, isolated head), 2026-11-19 ~14:26–14:35 ✅

Code `0e39fc0` (PR #71 draft, never merged; = rc2 + gated MQTT write path). Audit before
deployment: `MQTT_WRITE_DPS = frozenset({30})` (any other DP refused before encoding); only
`CloudMqttLink.publish_dp` publishes to the heads, reached only by a switch on the `cloud_mqtt`
path (option ON + link present + DP ∈ {30} + **isolated** head of a verified model — a grouped head
goes through the room, tested before). CI green.

- Deployment 14:26:28 (write batch, +2 ~10 −32) + restart (14:26:31). Option `enable_cloud_mqtt`
  present and OFF; Room A child-lock switch `unavailable` (no path).
- Baseline Room A: `child_lock` **true** (V0). Note: Room A's comfort changed 21 → 20.5 during the
  day **by the owner from the app** (no write by the connector) — confirmed.
- `enable_cloud_mqtt` → true at 14:31:59 (write batch). **Point 1**: `binary_sensor.cloud_mqtt_link`
  **on** (14:33:28); log `cloud-mqtt link: CONNACK rc=0` (thread `danfoss-cloud-mqtt-link`, no
  client id); Room A switch `on`, available, `write_path: cloud_mqtt`, `write_scope: head`.
- **Write** `switch.turn_off` Room A at 14:34 (write batch, owner's approval) → service **with no
  error** in 0.5 s (= confirmation, protocol-4 echo or cloud re-read — not distinguished in the
  log). **Point 2**: cloud `child_lock` **false** within a few seconds (reported by the head; vs
  W-3 `settings.change`: never), HA switch `off` (14:34); **app AND physical head unlocked**
  (owner); no other Room A setting changed; app not kicked out.

**Verdict: ✅ first Tuya cloud MQTT write validated on real hardware** — DP 30 of an isolated head
applies through MQTT (where `settings.change` fails). Also validates the inbound path end to end.

Restore after the first MQTT write: Room A re-locked through MQTT at 14:36 (write batch, cloud
`child_lock` true, switch `on`). `enable_cloud_mqtt` → false at 14:40:46 (write batch, queued
behind an HA restart started by the other integration's session at 14:37:37 — collision, no
damage). Went back **directly to rc3** (instead of rc2) on the owner's decision.

## Deployment of `1.1.0-rc3` (`0541a5b`, #74 fixes), 2026-11-19 ~14:43 ✅ (quick check)

Clean checkout of tag `1.1.0-rc3` (= `main`, manifest 1.1.0). Deployment 14:43:35 (write batch,
+0 ~16 −36: MQTT code removed) + core restart. Read-only check:
- integration `loaded`; **no** `danfoss_ally_cloud` **error line** in the log at startup;
- MQTT options (`enable_cloud_mqtt`, `cloud_mqtt_probe`) **gone** from the form; R-3 ON;
- `binary_sensor.cloud_mqtt_link`: no longer provided → it stayed in the registry as an **orphan**;
  **deleted** at 14:57:25 (write batch, owner's approval, orphan check OK);
- `holiday_active` **off** on both homes with the attribute **`scheduled: false`** (fix #74);
- Room A climate available (`active_setpoint` 20.5); Room A child-lock switch `unavailable`
  (expected: isolated head, no proven path without MQTT); Room A locked (V0) on the cloud side;
- preheat: switches available, trial in progress (Head R `off`, Head Q `on`) until Friday;
- version **1.1.0** shown in the panel ✅ (owner).
Writes of the #74 fixes (R-3 on `number`, preheat re-read, scheduled vacation): covered by unit
tests, real-hardware validation at the next window.

**Defects found in the connector tooling** (to report to the HA admin connector):
- a confirm that expires on the client side **loses the log entry** although the write happened;
- the "HA back up" restart checker returns `state = None` for 600 s while HA is running (false
  negative, task marked as failed);
- `reconnect_session_connector` cannot reload a healthy stdio MCP server: a new tool only appears
  after a manual restart of the server.

## Supervised cloud-MQTT first writes (DP 116, 18, 120, 27), 2026-11-19 ~21:05–22:05

Procedure: `docs/first-write-procedure.md`. One isolated test head on a verified model (not the
head of the DP 30 trial), the owner at the keyboard with the Danfoss app open, one explicit
go-ahead per write. One DP opened at a time through `cloud_mqtt_supervised_dps`, on that head only
(`cloud_mqtt_supervised_head`). Independent read-back: the head read through the **local tunnel**
by the MCP connector, which does not go through the cloud; then the app.

Build: the DP 116 "on" write ran on `1.2.0-rc1`, every later write on `1.2.0-rc2` (another session
installed it and restarted Home Assistant in between; the cloud-MQTT candidate code is the same in
both). Options found and left: `enable_cloud_mqtt` off, no supervised DP, no trial head,
`cloud_mqtt_probe` on.

Baseline of the head (cloud and tunnel agreeing unless noted): window detection off, bounds
35 / 5 °C, pause setpoint 5 °C (cloud only), current setpoint 5 °C, child lock off. The cloud
showed comfort 21 / setback 17 where the head held 5 / 5.

| DP | Write | Tunnel | Cloud (per-device) | App | Restore |
|---|---|---|---|---|---|
| 116 window detection | off → on | **on** | on | on | off, tunnel **off** |
| 18 upper bound | 35 → 34.5 | **34.5** | 34.5 | 34.5 | 35, tunnel **35** |
| 120 pause setpoint | 5 → 5.5 | no attribute known | 5.5 | 5.5 | (kept for the next step) |
| 27 lower bound, alone | 5 → 5.5 (pause already 5.5) | **5.5** | 5.5, pause unchanged | 5.5 | — |
| 27 + 120, one frame | 5.5 → 6 (above the pause) | **6** | 6, pause **6** | 6 / pause 6 | bound 5 (tunnel **5**), then pause 5 by DP 120 |

- **Armed entity**: on the trial head `write_path: cloud_mqtt`, `write_trial: true`; the same
  switch of another isolated head kept `write_path: local`. The bound and pause `number` entities
  appeared when their DP was opened and were removed when it was closed.
- **Confirmation**: every call returned without error in 0.4–0.7 s, which fits the gateway's echo
  (the cloud fallback only starts after 15 s). The source was not read from the logs (not at debug
  level): "confirmed by echo" is an inference. The per-device fallback was therefore not exercised.
- **Neighbours**: after each write the other settings of the head, read through the tunnel, were
  unchanged. The other heads were not re-read one by one.
- **DP 120 is the weaker proof**: no tunnel attribute is known for the pause setpoint, so the app's
  settings screen (and the cloud) are the only read-backs, and both have been seen holding values
  the head does not have. The DP 27 + 120 frame gives a second, still indirect, observation.
- **Lower bound and current setpoint**: with the bound raised to 5.5 then 6, the head's current
  setpoint stayed at 5 °C (tunnel): a head does not re-clamp its current setpoint when the lower
  bound rises above it.
- **Lower bound and pause setpoint**: lowering the bound back to 5 left the pause setpoint at 6; it
  was restored by its own write. Whether the app itself publishes DP 120 with DP 27 when the bound
  rises above the pause setpoint was **not** observed: the rule stays this project's reading.

**Verdict: ✅ DP 116, 18 and 27 (alone and with DP 120) proven on Tuya cloud MQTT; DP 120 proven on
app + cloud evidence only.**

### DP 118 + 16 and DP 119 — not run ❌ (precondition not met)

The sheets require the head to be in a comfort slot. The test head was not following a schedule
with slots (tunnel: a flat 5 °C schedule on the seven days, operation mode 3, preheat on; cloud:
mode `manual`, empty schedule). Attempt to prepare it, each step on the owner's go-ahead:

| Time | Step | Result |
|---|---|---|
| 21:40 | `set_schedule` on the head: one comfort slot that evening | accepted by the cloud |
| 21:42–21:47 | three tunnel reads | flat 5 °C schedule, unchanged |
| 21:47 | `restore_schedule` (seven days, then `at_home`) | accepted by the cloud |
| 21:50, 21:53 | two tunnel reads | unchanged; cloud mode still `manual` |
| 21:54 | `set_schedule` with the day emptied (clean-up) | accepted by the cloud |
| 21:55 | tunnel + cloud | head in **manual at 21 °C**, heat demand, mode 0, preheat off, empty schedule |
| 21:55 | `set_override` 5 °C (tunnel) | current setpoint 5 °C; mode 3, preheat on, flat **21 °C** schedule |
| ~21:58 | manual mode at 5 °C set by the owner in the app | manual 5 °C, mode 0, preheat off, empty schedule, valve closed |
| 22:01 | `set_override` 5 °C (tunnel) | no change in two reads |

No frame carrying DP 118, 16 or 119 was sent. What this run does establish:

- **HTTP schedule writes on an isolated head in manual mode did not act within the 5 minutes of
  R7** and showed on the head more than ten minutes later, as a switch to manual at the comfort
  setpoint — not as the schedule that was written. Which of the three calls produced it cannot be
  told apart. A schedule write "accepted" by the cloud must not be read as "not applied" after five
  minutes on such a head: a late effect is possible.
- `restore_schedule` over HTTP did not bring this head back to its schedule.
- The integration has no proven way to write an isolated head's durable setpoint: the manual
  setpoint was corrected in the app.

**State left on the test head**: setpoint 5 °C, valve closed, bounds, window detection, pause
setpoint and child lock as found; but plain manual (operation mode 0, no schedule, preheat off)
where it was found in mode 3 with a flat 5 °C schedule and preheat on. How the found state had been
produced is not known, and it was not recreated. To re-read through the tunnel the next morning.

**Re-read the next morning (2026-11-20 ~08:40), two reads, nothing written**: the head is back in
the state it was found in, without any further write. Tunnel: operation mode 3, preheat on, a flat
5 °C schedule on the seven days, current setpoint 5 °C, bounds 35 / 5 °C, window detection off.
Cloud (per-device): manual setpoint 5 °C, pause setpoint 5 °C, setpoint source "Schedule", no heat
demand, valve 1 %. So the "found" state is what an isolated head in manual at X °C settles into by
itself: mode 0 with an empty schedule right after the manual write, then, some time during the
following hours, mode 3 with a flat schedule at X and preheat back on. When that happens (a fixed
delay, or the day change at 00:00) was not observed. Two consequences: an operation mode of 3 with
the schedule bit set does not by itself mean the head follows a schedule with slots — read the
schedule; and neither late schedule write of the evening left a trace on the head.

**To run the two remaining trials**: an isolated head that already follows a schedule, during one
of its comfort slots, in daytime. (Run the same night and the next morning on another head: see
the section after the incident below.)

### Incident — Home Assistant restarted by other sessions during the trial

Home Assistant was restarted three times by other sessions while the trial was armed (21:06,
21:10, 22:02). The first fell between the DP 116 "on" write and its restore: the restore waited
163 s for the write lock, then ran after the restart and was read back through the tunnel. No write
was lost, but the "one driver of the live install at a time" rule did not hold. The options stayed
armed across the restarts, as designed.

## Supervised cloud-MQTT first writes (DP 119, DP 118 + 16), 2026-11-19 ~23:00 – 2026-11-20 ~08:40

Procedure: `docs/first-write-procedure.md`. Build `1.2.0-rc4` (commit `c8fa583`). Test head:
**Head U**, an isolated head on a verified model that follows its own weekly schedule — comfort
slots 08:30–17:30 on four days, transitions 00:00 → 14 °C, 08:30 → 21 °C, 17:30 → 14 °C. Its
schedule was **not** touched to prepare the trial (a schedule write pushes the whole week, R2, and
would have blurred the very question asked). The owner at the keyboard with the Danfoss app, one
explicit go-ahead per step. One setting opened at a time on that head only. Independent read-back:
the head read through the **local tunnel** by the MCP connector (weekly schedule, current setpoint
`0x0012`, setpoint source, schedule mode, preheat `0x0025`).

Options found and left: `enable_cloud_mqtt` off, no supervised DP, no trial head,
`cloud_mqtt_probe` on (same options fingerprint before and after).

Baseline (tunnel, cloud per-device route and Home Assistant agreeing): comfort 21 °C, setback
14 °C, current setpoint 14 °C (night, setback period), bounds 5 / 21 °C, schedule mode 3, preheat
on, setpoint source "schedule", child lock on.

**Armed entity**: on Head U the setting's number showed `write_path: cloud_mqtt`,
`write_scope: head`, `write_trial: true`; another isolated head had no comfort or setback number,
and its pause number (proven DP) carried no trial marker.

### DP 119 — setback 14 → 13.5 → 14 °C, during a setback period ✅

| Time | Step | Schedule: setback transitions | Schedule: comfort | Current setpoint | Source |
|---|---|---|---|---|---|
| 23:00 | baseline | 14 | 21 | 14 | schedule |
| 23:03:46 | write 13.5 (returned ok in 0.6 s) | | | | |
| +15 s | | 14 | 21 | 14 | schedule |
| +1 min 15 | | **13.5** (00:00 and 17:30, seven days) | 21 | 14 | schedule |
| +5 min | | 13.5 | 21 | **13.5** | schedule |
| +15 min | | 13.5 | 21 | 13.5 | schedule |
| 23:19:06 | restore 14 (ok in 0.6 s) | | | | |
| +1 min 30 | | **14** | 21 | **14** | schedule |
| +5 min | | 14 | 21 | 14 | schedule |

Cloud (per-device route): `leaving_home_setting` already at the new value 15 s after each write;
`OccupiedSetpoint` followed the head's current setpoint, `SetpointChangeSource` "Schedule". Home
Assistant: setback and active setpoint agreeing at each step. App (owner): setback 13.5, then 14.
Schedule mode 3 and preheat on at every read.

### DP 118 + 16 — comfort 21 → 20.5 °C outside a comfort slot, 20.5 → 21 °C inside one ✅

After re-arming (23:39) the "Cloud MQTT link" sensor stayed "connecting" for about a minute before
"connected" (a few seconds at 23:02); the write was sent once it was connected.

| Time | Step | Schedule: comfort transitions | Current setpoint | Source |
|---|---|---|---|---|
| 23:39 | baseline | 21 | 14 | schedule |
| 23:41:48 | write 20.5 (ok in 0.7 s) | | | |
| +15 s | | 21 | **20.5** | **external** |
| +1 min 15 | | **20.5** (08:30, the four days) | 20.5 | external |
| +5 min | | 20.5 | **14** | **schedule** |
| +15 min | | 20.5 | 14 | schedule |
| night | head left at comfort 20.5, trial armed | | | |
| 08:29 | | 20.5 | 14 | schedule |
| 08:30:36 | comfort slot started | 20.5 | **20.5** | schedule |
| 08:30:45 | restore 21 (ok in 0.6 s) | | | |
| +15 s | | 20.5 | **21** | external |
| +50 s | | **21** | 21 | external |
| +5 min | | 21 | 21 | **schedule** |

Cloud: `at_home_setting` and `temp_set` at the new value 15 s after each write;
`SetpointChangeSource` "Externally" then "Schedule", following the head; `work_state` "Heat"
while the current setpoint was at the comfort value at night, "NoHeat" once it fell back. Home
Assistant and the app (owner: comfort 20.5, then 21) agreeing. Setback transitions, bounds,
schedule mode 3 and preheat on unchanged at every read.

What the two trials establish:

- **An isolated head rewrites its own schedule transitions**, comfort and setback alike, about a
  minute after the write. No schedule rewrite is needed (R3 is a rule for rooms). The 08:30
  transition, which applied the value written the evening before, confirms it from the head's own
  behaviour.
- **DP 16 sets the current setpoint at once** (source "external"); the head returns to its
  schedule within five minutes. Outside a comfort slot that means a few minutes of heat demand at
  the comfort value, then the setback value again; inside one, the value stays.
- **DP 119 alone does not set the current setpoint at once**; in a setback period the head aligns
  by itself one to five minutes later.
- **The settings block** posted after each write (`{"1", "118", "119", "121"}`) did not change the
  real preheat.
- **Confirmation**: every call returned in 0.6–0.7 s, which fits the gateway's echo; as before the
  source was not read from the logs.
- Seen at 08:30, before the restore write: the cloud's `switch_state` went from true to false at
  the same time as the head's "preheat in progress" flag. It follows the end of the head's
  anticipation, not the write.

Not covered: a head in manual mode or without a schedule; DP 119 written during a comfort slot;
the per-device fallback of the confirmation; the other heads were not re-read one by one.

**State left**: Head U as found (tunnel read after disarming: comfort 21, setback 14, current
setpoint 21 in its comfort slot, source "schedule", mode 3, preheat on). Options as found.

**Verdict: ✅ DP 118 + 16 and DP 119 proven on Tuya cloud MQTT for an isolated head following its
schedule.**

## §3 — online vs update_time (autonomous spot-check)

- Room A (online) → MQTT availability `online` ✅.
- **Room S head #3** (offline head, `danfoss_sante`) → MQTT availability **`offline`** ✅ →
  availability does follow `online`, not `update_time`.
- Sensor T (**sensor**) and relay 1 (**relay**) → availability topic **missing**: these categories
  are **not published** in discovery (the integration publishes heads; sensors/relays are outside
  the MQTT scope). Worth noting, not a defect.

## R-3 — addendum (lost transient)

Re-read of Room A ~21:51: back on schedule (`setback`, `OccupiedSetpoint` 1400, valve 1 %,
`work_state` NoHeat). The manual peak (21 / valve 82 %) of ~21:06 **was never reflected** by the
integration or MQTT (bulk route): it appeared and disappeared between two visible polls. Confirms
that fast variations go under the radar of the bulk route.

## Session state (2026-11-18, evening)

- **Done**: §0 (prerequisites + discovery enabled), R-1 (2 mismatches: setpoint + hvac_action),
  R-3 (bulk route latency). Head firmware recorded.
- **Postponed to the next morning**: R-2 (windows during airing), P-1…P-3 (preheat curves),
  bulk latency re-check.
- **Suspended**: writes W-1…W-7 — not very conclusive as long as (a) the mapping fix is not merged
  and (b) the bulk latency is not settled (round-trips are not visible in time).
- **Gated / not tested**: W-6 vacation (TARGET 2, option off), §2b unbind (TARGET 3, not exposed).
- **R-1 fix**: session `fix-consigne-active-hvac` — **coded, tests green** (407 passed, coverage
  93.45 %, ruff OK), **not committed**, waiting for review/commit by the owner.
  Mapping: DP 171 → (fallback: mode+settings) → DP 16. R-3 (freshness) left out of this PR.
- **To restore**: Room A left in manual 21 during R-3 → to put back on schedule.
- **Config**: `mqtt_mode=discovery` left on for the next morning's observation.

---

## Preheat night trial read-out, 2026-11-20 ~10:00 — trial voided by a night-time revert

Read only (HA history of `danfoss_ally_cloud`, then a tunnel read of both heads at ~10:00).

- **Reverted with no write from us**: the preheat switches, fed by the local survey, show Head R
  **off → on at 04:54:52** and Head Q **on → off at 04:55:02** (two reads of the same survey pass,
  10 s apart). No write batch in the connector's journal that night.
- **Tunnel read at ~10:00**: Head R programming mode 3, preheat on; Head Q programming mode 1,
  preheat off; schedules and setpoints unchanged. Both heads were already back to their original
  state: nothing to restore.
- **Morning curves**, consistent with the reverted state: Head R (preheat back on) valve ≥ 10 % at
  07:12, 78 min before its slot; Head Q (back off) valve ≥ 10 % at 08:35, the slot + 5 min, no early
  ramp.
- **Likely cause**: the tunnel write of 0x0025 did not touch the cloud's DP 1, which kept its
  original value (also seen on the official `danfoss_ally` integration's switches, unchanged all
  night). The gateway may re-impose its cached value at a night-time resync. To confirm; if so, a
  tunnel-only preheat write does not hold (`../preheat-tunnel-durability.md`).

## Deployment of `1.3.0-rc3` (`015fdf5`, #121 → #124) and tunnel settings trial, 2026-11-20 ~14:20–15:07 ✅

Files copied from the tag (the Marketplace still refuses `update.install`), core restart 14:20,
integration `loaded`, clean log.

**Read only (batches A/B, card by area)** — Head V: the new sensors agree with the official
`danfoss_ally` integration (radiator covered off/off, programming mode `schedule_with_preheat` /
preheat on, mounting mode off/off, window state `closed` / window off). The five settings sensors
disabled by default are disabled. No trial entity while the trials are closed. Panel: the rc3 bundle
is served, other areas hidden by default. A room card by area mounted in memory (nothing saved) on
an area holding two `danfoss_ally` thermostats lists them without controls, also with
`allow_foreign_writes: true` (duplicate guard). ⚠️ Bundle URL `?v=1.3.0` identical for every rc: a
forced reload was needed (fixed by #126).

**Tunnel settings trial (#124), Head V, one setting armed at a time, owner present.** Initial
values read through the tunnel: radiator covered off, offset 0, regulation speed 1, valve exercise
Saturday 10:00.

| Time | Write | `trial_result` | Tunnel read-back |
|---|---|---|---|
| 14:41 | radiator covered off → on | confirmed_by_tunnel | on |
| 14:42 | on → off | confirmed_by_tunnel | off |
| 14:47 | offset 0 → +0.1 (raw 1) | confirmed_by_tunnel | 1 |
| 14:47 | → 0 | confirmed_by_tunnel | 0 |
| 14:48 | offset 0 → +0.5 (raw 5) | confirmed_by_tunnel | 5 |
| 14:50 | → 0 | confirmed_by_tunnel | 0 |
| 14:57 | speed 1 → 2 | confirmed_by_tunnel | 2 |
| 14:58 | → 1 | confirmed_by_tunnel | 1 |
| 15:03 | valve exercise day Saturday → Sunday (time kept) | confirmed_by_tunnel | Sunday 10:00 |
| 15:04 | time 10:00 → 11:00 (day kept) | confirmed_by_tunnel | Sunday 11:00 |
| 15:05 | day → Saturday, then time → 10:00 | confirmed_by_tunnel ×2 | Saturday 10:00 |

Nothing else changed on the head after each write. Closed at 15:05.

- **No independent source**: the app does not show the offset; the official integration's
  "radiator covered" switch stayed off while the head read on. As with preheat, the cloud may
  ignore tunnel-only writes and re-impose its value: hold over time not established.
- **Window state** read `quarantine` (0) after the radiator-covered toggle; read `closed` again at
  16:02 after a restart. Not persistent.

## Batch C (cloud MQTT), Head V, 2026-11-20 ~15:08–15:22

Armed: `enable_cloud_mqtt` on, Head V designated, one DP at a time. Closed 15:22 (`enable_cloud_mqtt`
back off): trial entities removed, link back to listen-only.

- **DP 101 (viewing direction) — refused before anything was sent.** The per-device cloud route
  (`smartlife.m.device.get`) gave no DP 101, so there was no confirmation source; nothing published.
  Cause found: that route carries the DPs under `dataPointInfo.dps` (fixed in #125, 1.3.0-rc4). To be
  re-run with the owner at the head's display.
- **DP 133 (orientation) — validated both ways.** Mapping established before writing: head mounted
  horizontally, app horizontal, tunnel `0x4014 = false`, cloud `Horizontal` → false = horizontal
  (Zigbee2MQTT's reading confirmed).

| Time | Write | `trial_result` | Delay | Tunnel | Cloud |
|---|---|---|---|---|---|
| 15:20 | horizontal → vertical | confirmed_by_tunnel | 22 s | true | Vertical |
| 15:21 | vertical → horizontal | confirmed_by_tunnel | 17 s | false | Horizontal |

Nothing else changed on the head; the cloud follows (unlike the tunnel-only writes).

- **Incident**: another session restarted the HA core at 15:13:57. A first write sent 2 s after the
  core came back found no entity yet: nothing sent (checked). Re-run at 15:20.

## `1.3.0-rc4`, then `1.3.0`, Head V, 2026-11-20 ~15:55–17:05

`1.3.0-rc4` (`040cf8a`) copied at 15:52, core restart; the owner then updated to `1.3.0` through
HACS (~16:20): the code on the host is identical to the `1.3.0` tag (deploy preview: 0 added,
0 modified). Bundle check: a single Lovelace resource `danfoss-ally-cloud.js?v=1.3.0-<hash>`, the
hash matching the shipped bundle; the side panel loads the same URL (#126).

**Setpoint offset, +2.5 °C for 10 min** (V0 = 0). 16:02:44 → +2.5 (raw 25, confirmed_by_tunnel);
16:13:16 → 0 (confirmed_by_tunnel). Temperature 21.0 → 20.9 → 21.2 °C, valve 38 → 42 → 52 %. The
reported temperature does not jump: the offset does not shift the measurement.

**Setpoint offset, +2.5 °C for 30 min** (V0 = 0, setpoint 21 °C). 16:34:47 → +2.5 (raw 25,
confirmed_by_tunnel); 17:05:07 → 0 (confirmed_by_tunnel); trial closed 17:05:17.

| Time | Valve (tunnel) | Temperature |
|---|---|---|
| 16:32 | 41 % | 21.4 |
| 16:37 | 37 % | 21.3 |
| 16:42 | 52 % | 21.5 |
| 16:47 | 62 % | 21.8 |
| 16:52 | 72 % | 22.3 |
| 16:57 | 84 % | 22.5 |

The head heats above its setpoint while the measurement does not jump: **the offset raises the
regulation target**, as Zigbee2MQTT's `regulation_setpoint_offset`. Direction confirmed; scale
(raw 25 = 2.5 °C?) not proven, no plateau reached in 30 min. User-facing consequence: with an
offset set, the displayed setpoint no longer says how warm the room gets.

**Hold of a tunnel-only setting overnight.** 16:25:15 valve exercise day Saturday → Sunday (time
10:00 kept), confirmed_by_tunnel; trial closed 16:25:33; independent tunnel read (Danfoss MCP
connector) at 16:26: Sunday 10:00, everything else unchanged. **To read on 2026-11-21 morning**:
Sunday = the head keeps a tunnel-only setting; Saturday = the cloud re-imposes it, as with preheat.
Then restore Saturday 10:00.

**Room card by area on Zigbee2MQTT heads (Area X).** The five Zigbee2MQTT devices were put in the
area through the HA admin connector (a new area tool). The card, mounted in memory, lists the four
heads with temperature, action, setpoint and badges read from their Zigbee2MQTT entities (battery,
valve…); read only by default, "Cooler / Warmer" with `allow_foreign_writes`. Nothing written. The
heads regulate on the room sensor (`external_measured_room_sensor` ≈ 17.4 °C) and heat at full valve
while their own measurement reads 20–24 °C; the card did not show the room sensor → #128. On an
area with two Tuya thermostats the card works the same way.
