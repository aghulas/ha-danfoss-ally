# Supervised first writes — procedure and sheets

One procedure and its sheets for every write that is not yet proven: DPs over Tuya cloud MQTT
(generic procedure and per-DP sheets), viewing direction and orientation, and head settings
through the local tunnel. Trial records: `docs/validation/2026-11-real-hardware-validation.md`.

A DP is **proven** on the Tuya cloud MQTT channel only after one supervised write on real hardware,
read back from a source that does not depend on that channel (`docs/architecture.md`, "Rules for
adding a route"). One DP at a time: a new DP does not inherit the proof of another.

This is the only step that writes to real hardware. **No publish happens before the owner's explicit
go-ahead, at the keyboard, with physical access to the test head.**

## How a DP is opened for its trial

| State | Where | Effect |
|---|---|---|
| Proven | `api.writes.MQTT_WRITE_DPS` | Open as soon as `enable_cloud_mqtt` is on |
| Candidate | `api.writes.MQTT_CANDIDATE_DPS` | Implemented, **closed**. Opens only when listed in the option `cloud_mqtt_supervised_dps` (empty by default), with `enable_cloud_mqtt` on, and **only on the one head chosen in `cloud_mqtt_supervised_head`** (none by default) |
| Anything else | — | Never sent on this channel |

A trial is confined to **one designated head**. Ticking a DP opens it on that head and nowhere
else: every other head keeps its normal routing, so an automation or a click on another head can
never go out through the channel under trial. With no
head designated, nothing is open, whatever is ticked.

While a candidate is open, the entity that writes it — on the trial head — shows `write_path: cloud_mqtt`,
`write_scope: head` and `write_trial: true`, and Home Assistant logs one warning at start-up naming
the DPs under trial. After a successful trial, the DP moves from the candidate set to the proven set
in a pull request of its own, and is removed from the option.

Every write on this channel, trial or not: the value is validated before sending, the DPs of one
setting go out in one frame, and the write is confirmed by the gateway's echo (inbound protocol-4
report, 15 s) or, failing that, by one read of the head through the per-device cloud route.
Otherwise the call raises a clear error. Nothing is ever shown that was not read back.
One exception, preheat (DP 1): the echo and the cloud read prove nothing for it, so its write is
confirmed by a read of the head through the local tunnel only (its sheet below). Viewing direction
(DP 101) and orientation (DP 133) do not accept the echo either; they have a sheet of their own
below.

Head settings written through the **local tunnel** rather than cloud MQTT (radiator covered,
setpoint offset, regulation speed, valve exercise) follow the same discipline with their own
options (`local_supervised_settings`, `local_supervised_head`) and their own sheet, below.

## Generic procedure

Preconditions:

- an **isolated** test head (in no room) on a verified model, `online`, with nobody relying on it,
  and **already in the state the sheet requires** (for a setpoint: following a schedule, in a
  comfort slot). Read its real state through the local tunnel first: the cloud can show a mode and
  setpoints the head does not hold;
- **one driver of the live install**: no other session or person restarts Home Assistant, changes
  its options or deploys a build while a DP is armed (on 2026-11-19 two restarts fell between a
  write and its restore; the queued calls ran afterwards, but nothing guarantees that);
- the Danfoss app open on that head's page (to observe, and to check the app is not logged out);
- physical access to the head;
- the independent read-back source of the DP's sheet below, working **before** the write;
- the build to deploy identified by its commit, deployed by the session that drives the live
  install.

Steps:

1. **Baseline.** Read the value in Home Assistant, in the app and through the independent source.
   They must agree. Record it as `V0`.
2. **Arm.** Turn `enable_cloud_mqtt` on, choose the test head in `cloud_mqtt_supervised_head` and
   tick the DP in `cloud_mqtt_supervised_dps`. The entry reloads. Check the "Cloud MQTT link"
   sensor is on, that the test head's entity shows `write_path: cloud_mqtt` with
   `write_trial: true`, and that the same entity of **another** isolated head does not.
3. **Write** the trial value of the sheet, once.
   - The call returns without error: a confirmation was seen (echo or per-device read).
   - The call raises "not confirmed": nothing is claimed. Read the head before any retry.
4. **Read back** through the independent source, then in the app, then on the head itself. All
   three must show the new value. A cloud or app value that changes while the independent source
   does not is the "accepted but not applied" failure: stop.
5. **Check the neighbours.** No other head, and no other setting of the test head, has changed.
6. **Restore** `V0` the same way, and read it back the same way.
7. **Disarm.** Untick the DP in `cloud_mqtt_supervised_dps` and set `cloud_mqtt_supervised_head`
   back to none (and turn `enable_cloud_mqtt` off unless it stays on for a proven DP).
8. **Record** the result (model, firmware, confirmation source, delays, what each source showed) in
   the local validation notes — never real device identifiers or room names in this repository.

Stop and restore at once if: the independent source does not show the change within about a minute
while the app does; a write raises; anything changes on another head; the app is logged out when
the link connects; or there is any doubt about being able to restore.

## Sheets

### DP 30 — child lock ✅ proven (2026-11-19)

Written on an isolated test head, confirmed in the cloud, in the app and physically on the head; no
other head or setting affected. No tunnel read exists for this setting: the head itself (its lock)
was the independent source.

### DP 116 — open-window detection ✅ proven (2026-11-19)

Written on an isolated test head (off → on → off), each step read back through the **local tunnel**
(the head's own window-detection setting, the read that validated the tunnel write, W-4), in the
cloud (per-device route) and in the app. No other setting of the head changed. Both calls returned
in under a second.

- **Routing now**: an isolated head's window detection is written through the **local tunnel** when
  it is enabled and the head answers locally (proven, immediate); cloud MQTT is the fallback when
  the tunnel is not available. The tunnel stays the first choice.
- The "on" write ran on 1.2.0-rc1 and the "off" write on 1.2.0-rc2 (Home Assistant was restarted
  for an update between the two); the cloud-MQTT write code is identical in both.
- **Not observed — the confirmation fallback.** When the gateway's echo does not come within 15 s,
  a write is confirmed by one read of the head through the **per-device** cloud route. None of the
  2026-11-19 writes exercised it: every call returned in under a second, which is consistent with
  the echo, and the debug log line naming the confirmation source ("confirmed by echo" /
  "confirmed by cloud") was not read. If a write is ever confirmed "by cloud", check that the head
  really holds the value; if one fails as "not confirmed" while the head did apply it, record how
  long the per-device route took to show the value.

### DP 18 — upper setpoint bound ✅ proven (2026-11-19)

Written on the same isolated test head (35 → 34.5 → 35 °C), each step read back as the head's
maximum setpoint through the **local tunnel** (thermostat attribute `0x0016`), in the cloud and in
the app's settings screen. No other setting changed; no thermal effect (the bound only limits what
can be set).

- **Entity**: the head's "upper setpoint bound" number, present for every isolated head while
  `enable_cloud_mqtt` is on. The integration refuses a bound that would exclude the comfort or
  setback setpoint.

### DP 27 — lower setpoint bound, with DP 120 ✅ proven (2026-11-19)

Written on the same head in two steps, each read back as the head's minimum setpoint through the
**local tunnel** (thermostat attribute `0x0015`), in the cloud and in the app:

1. `{"27": 55}` alone, with the pause setpoint already at 5.5 °C — the bound moved to 5.5 °C, the
   pause setpoint did not;
2. `{"27": 60, "120": 60}` in one frame — the bound moved to 6 °C and the pause setpoint followed
   to 6 °C (read in the cloud and in the app).

Restored with `{"27": 50}` then `{"120": 50}`.

- **What is sent**: `{"27": v}`; and `{"27": v, "120": v}` in one frame when the new bound is
  **above the head's pause setpoint**. That frame is applied by the head. Whether the app itself
  publishes DP 120 in that situation was **not** observed: the rule remains this project's reading
  of the capture (contract §4.2).
- **The head does not re-clamp its current setpoint**: with the bound at 5.5 °C then 6 °C, the
  head's current setpoint stayed at 5 °C (tunnel read), and its schedule kept 5 °C.
- **Lowering the bound does not lower the pause setpoint again**: it stayed at 6 °C after the bound
  went back to 5 °C, and was written back on its own with DP 120.

### DP 120 — pause setpoint of an isolated head ✅ proven (2026-11-19), weaker proof

Written on the same head (5 → 5.5 °C, later 6 °C with DP 27, then back to 5 °C), the head **not**
in pause mode — no thermal effect.

- **Read-back**: no tunnel attribute is known for the pause setpoint, so the **app's settings
  screen** was the independent source, with the cloud (per-device route) agreeing each time. This
  is weaker than a tunnel read: both the app and the cloud can show a value the head does not hold
  (seen on the same head for its comfort setpoint). The pause setpoint following the lower bound
  in the `{"27", "120"}` frame is consistent with the head handling DP 120, but is read from the
  same two sources.
- **What is sent**: `{"120": v}`. No settings block (DP 120 is not part of it).
- **Entity**: the head's "pause setpoint" number, present for every isolated head while
  `enable_cloud_mqtt` is on.

### DP 118 + 16 — comfort setpoint of an isolated head ✅ proven (2026-11-19/20)

Written on an isolated head **following its weekly schedule** (comfort slots 08:30–17:30 on four
days), 21 → 20.5 °C in the evening, outside a comfort slot, then 20.5 → 21 °C the next morning,
one minute into a comfort slot. Each step read back through the **local tunnel**, in the cloud
(per-device route), in Home Assistant and in the app.

- **Entity**: the head's "comfort setpoint" number, present for every isolated head while
  `enable_cloud_mqtt` is on.
- **What is sent**, as the app does (contract §4.2): one MQTT frame `{"118": v, "16": v}`; once
  DP 118 is confirmed, the whole settings block `{"1", "118", "119", "121"}` through
  `settings.change` (`gwId` = the head's devId), with the head's current values and the new one.
  Only DP 118's confirmation is required. Each write returned in under a second.
- **The head's schedule takes the value by itself — no schedule rewrite.** About a minute after
  the write, every comfort transition of the head's weekly schedule carried the new value (tunnel
  read; still the old value 15 s after the write). The next morning, at the start of the comfort
  slot, the head applied the value written the evening before, on its own, with the setpoint
  source "schedule". Unlike a room (R3), nothing has to be rewritten.
- **DP 16 sets the current setpoint at once, then the head goes back to its schedule.** 15 s after
  the write the head's current setpoint (attribute `0x0012`) was the new comfort value, with the
  setpoint source "external". Within five minutes the source was "schedule" again:
  - outside a comfort slot, the current setpoint fell back to the setback value. In between, the
    head was in heat demand towards the comfort value: **a comfort write outside a comfort slot
    costs a few minutes of heating**;
  - inside a comfort slot, the current setpoint stayed at the new comfort value.
- **Neighbouring settings unchanged**: the real preheat (attribute `0x0025`) and the head's
  schedule mode, although the settings block carries DP 1; the setback transitions; the bounds.
- **Not covered**: a head in **manual** mode, or with no schedule. DP 16 is the head's effective
  setpoint, and nothing was observed that would bring such a head back to its previous setpoint.
  The integration therefore refuses the comfort write unless the cloud reports the head in a
  schedule mode (`at_home` or `leaving_home`). The cloud's mode can itself be wrong (seen on
  2026-11-19 on another head): the guard is a best effort, not a proof.

What must not be used to prepare such a trial, observed on 2026-11-19 on an isolated head left in
manual mode: a schedule write (`set_schedule`) and `restore_schedule` over HTTP were both accepted
and had **no effect on the head within five minutes** (five tunnel reads). An effect appeared more
than ten minutes later: the head ended in manual mode at the cloud's comfort value, with no
schedule, and had to be set back by hand in the app.

### DP 119 — setback setpoint of an isolated head ✅ proven (2026-11-19)

Written on the same head, 14 → 13.5 → 14 °C, at night, **during a setback period** (the setback
value was the one in force). Each step read back through the **local tunnel**, in the cloud, in
Home Assistant and in the app.

- **Entity**: the head's "setback setpoint" number, present for every isolated head while
  `enable_cloud_mqtt` is on.
- **What is sent**: `{"119": v}` alone (no DP 109: the app does not send it for an isolated head),
  then the settings block as above. Each write returned in under a second.
- **The head's schedule takes the value by itself — no schedule rewrite.** Between 15 s and
  75 s after the write, every setback transition of the weekly schedule, on all seven days,
  carried the new value (tunnel read). The comfort transitions did not move.
- **DP 119 alone does not set the current setpoint at once** (unchanged 75 s after the write,
  unlike DP 109 for a room, contract §4.2). During a setback period the head then aligns its
  current setpoint by itself, with the setpoint source "schedule": seen between one and five
  minutes after the first write, and within 90 s after the restore.
- **Neighbouring settings unchanged**: the real preheat and the schedule mode.
- **Not covered**: the same write during a comfort slot (the value is then not in force; the
  schedule read above is what establishes it), and a head in manual mode.

### DP 101 — viewing direction, DP 133 — orientation (candidates)

Sheet of their own, below (DP 133 confirmed by the tunnel flag `0x4014`, DP 101 by the per-device
route and the head's display). DP 133 passed its trial on 2026-11-20; DP 101 is still to run.

### DP 1 — preheat (candidate; stage A positive, stage B failed, 2026-11-20)

The known trap: over HTTP, DP 1 only changed the gateway cache while the head's real preheat (bit 1
of Zigbee attribute `0x0025`) did not move. The gateway's echo and the cloud read therefore confirm
nothing here; **only `0x0025` read through the local tunnel does**. Background and assessment:
`docs/preheat.md`. Two stages; stage B is run only if stage A is positive.

Result on 2026-11-20 (tables in `docs/preheat.md`): stage A positive — the app's toggle reached the head
within a minute; stage B **not passed** — the integration's `{"1": true}` changed the cloud's DP 1
and not the head, 15 minutes later still. DP 1 stays a closed candidate. A listen the same day
showed that the app's toggle is followed by a reprogramming of the head through the Zigbee tunnel,
which the bare publish does not trigger. The write was changed accordingly (below) and passed
once with it, OFF to ON on one head (`docs/validation/2026-11-preheat-dp1-pair.md`); the restore
and the overnight hold are still to be read.

Preconditions for both, on top of the generic ones: the local tunnel answers **this head** right
before starting (its preheat switch has a value, not "unavailable"), and a raw read of `0x0025`
is available to the supervisor (both bits: 0 = schedule, 1 = preheat) — the switch only shows
bit 1.

**Stage A — observation, no code, no option.** The app is the reference publisher.

1. Baseline: raw `0x0025` through the tunnel (`V0`, both bits); cloud DP 1 and DP 172 (the cloud's
   mirror of `0x0025`) through the per-device route; the app's preheat toggle. Record all four.
2. In the Danfoss app, toggle preheat on that head, once. Note the time.
3. Read raw `0x0025`, cloud DP 1 and cloud DP 172 at about 20 s, 1 min, 5 min and 15 min.
4. Toggle back in the app; same reads; `0x0025` must be back to `V0`. If it is not, restore
   through the tunnel (the preheat switch, proven) and read again.

| Instant | `0x0025` raw (tunnel) | bit 1 | bit 0 | cloud DP 1 | cloud DP 172 |
|---|---|---|---|---|---|
| baseline | | | | | |
| +20 s | | | | | |
| +1 min | | | | | |
| +5 min | | | | | |
| +15 min | | | | | |
| after toggle back | | | | | |

Reading the result:

- bit 1 follows the toggle within about a minute, bit 0 unchanged → positive, go to stage B;
- bit 1 does not move while cloud DP 1 does → cloud MQTT is as blind as HTTP for preheat. Record
  it, **remove DP 1 from `MQTT_CANDIDATE_DPS`** and close the question: the tunnel stays the only
  route;
- bit 1 moves only after minutes → not usable as it stands (the integration waits 60 s); record
  the delay and do not run stage B;
- bit 0 changes → stop, restore, do not run stage B.

**Stage B — supervised write from the integration** (generic procedure, with these specifics).

- **What is sent**: one MQTT frame `{"1": bool}`, then `settings.change` over HTTP with the whole
  settings block `{"1", "118", "119", "121"}` (the cloud's current values, DP 1 changed), as the
  app does for the settings of that block. Whether that pair is what makes the cloud reprogram the
  head is the question of this trial. If a value of the block is unknown, nothing is sent.
- **Arm**: `enable_local` and `enable_cloud_mqtt` on, the test head designated, DP 1 ticked.
  Without `enable_local` there is no preheat switch at all, so ticking DP 1 does nothing. The
  head's preheat switch must show `write_path: cloud_mqtt` and `write_trial: true`; the preheat
  switch of another head must show `write_path: local`. While armed, the tunnel never writes this
  head's preheat: with the MQTT link down the write fails instead of falling back.
- **Trial value**: the opposite of `V0`'s bit 1.
- **What the call does**: reads the head through the tunnel first (no answer → nothing sent;
  already at the value → nothing sent), publishes, posts the block, then reads the head every 10 s
  for 120 s at most (the app's toggle took 20 to 60 s to show on the head). It returns only when
  bit 1 shows the value; otherwise it raises "not confirmed". The echo and the cloud are not
  consulted. A caller that times out before that (60 s for some clients) has not failed the write:
  read the task's result, do not resend.
- **Also check**, since the cloud may rewrite the schedule: the head's weekly schedule and
  current setpoint through the tunnel, before and after — they must be unchanged.
- **Independent read-back** by the supervisor: raw `0x0025` through the tunnel (bit 1 at the new
  value, **bit 0 unchanged** — the code does not check bit 0), then the app, then cloud DP 1 and
  DP 172 for the record.
- **Restore after a confirmed write**: toggle the switch back while still armed (second proof).
  Read `0x0025` back: it must equal `V0`.
- **After a "not confirmed"**: the frame **was sent**. Do not write anything yet.
  1. Read raw `0x0025` and cloud DP 1 (per-device route) again at about 5 min and 15 min: the
     head may apply the frame late (stage A's "only after minutes" case). Record the delay if it
     does; the trial is not passed either way.
  2. If the head ended up at the trial value: disarm, restore it through the tunnel (the preheat
     switch, proven), read `0x0025` back (= `V0`). Then read cloud DP 1 through the per-device
     route: a tunnel write does not update that cache, so if it still shows the trial value,
     resynchronise it from the app as in step 3.
  3. If the head stayed at `V0` while **cloud DP 1 shows the trial value**, the gateway cache is
     out of step with the head — the HTTP failure, reproduced. Toggling the switch back does
     **not** fix it: the integration reads the head, finds it already at `V0` and publishes
     nothing (a publish the head does not react to could not be confirmed by the tunnel, so the
     integration never sends one). A tunnel write does not touch that cache either. Resynchronise
     from the **Danfoss app**, the reference publisher. Its preheat toggle does **not** display
     that cloud DP 1 (2026-11-20: it showed the head's value while cloud DP 1 said the opposite),
     so setting it "to the head's value" may be a no-op: do a round trip instead — toggle to the
     trial value, wait a minute, toggle back to the head's value (`V0`'s bit 1). Then read cloud
     DP 1 through the per-device route — it must show `V0`'s value — and raw `0x0025` — it must
     equal `V0`. Record both reads. These are two real writes to the head: the owner's to do.
- **Passed** means only: this publish reaches the head. Promotion is a change of its own, which
  must say when cloud MQTT would be preferred to the tunnel that confirms it.

## Sheet — viewing direction (DP 101) and orientation (DP 133)

Batch C of `docs/zigbee2mqtt-alignment.md`: the first new head-setting writes of the Zigbee2MQTT
alignment. Both are written over Tuya cloud MQTT exactly as the Danfoss app does for an isolated
head (`docs/interface-contract.md` §4.2: `{"101": bool}`, `{"133": "Vertical" | "Horizontal"}`).
Both are **closed candidates** (`api.writes.MQTT_CANDIDATE_DPS`): nothing exists and nothing can
be sent until the trial is armed for one head. This sheet completes the generic procedure above;
its preconditions and stop rules apply unchanged. **Rémi present, on site, for every write.**

Status after the trial of 2026-11-20 (one isolated head):

- **DP 133 passed, both ways** (horizontal → vertical → horizontal, `confirmed_by_tunnel` in 22 s
  and 17 s; the cloud's DP 133 followed). The mapping is settled: flag `0x4014` false =
  horizontal, as Zigbee2MQTT reads it. Still a candidate in the code: promotion is a change of
  its own.
- **DP 101 was refused before anything was sent**: the per-device route gave no DP 101 (it
  carries the DPs under `dataPointInfo.dps`, fixed since). To be run again with the owner at the
  head's display.

### What the code does

| | Viewing direction (DP 101) | Orientation (DP 133) |
|---|---|---|
| Entity (trial head only) | `switch` "Viewing direction", config category | `select` "Mounting orientation" (`horizontal` / `vertical`), config category |
| Exists when | `enable_cloud_mqtt` on, DP 101 ticked, head designated, head isolated, verified model | same with DP 133, **and** `enable_local` on with the head addressable by the tunnel |
| State shown | the cloud's DP 101 (bulk list, then the per-device route after a write); unavailable when absent | the head's flag `0x4014` read through the tunnel (daily pass or read-back); the cloud's DP 133 only as attribute `cloud_value` |
| Checked before sending | value is a boolean; the per-device route gives DP 101; equal to the value → `unchanged`, nothing sent | value is exactly `"Vertical"` or `"Horizontal"`; the tunnel gives the flag; flag and cloud's DP 133 agree under false = horizontal; equal to the value → `unchanged`, nothing sent |
| Confirmation | per-device cloud route shows the value, read every 15 s for 60 s | tunnel flag shows the value, read every 15 s for 120 s |
| Never accepted | the gateway's echo | the gateway's echo, the cloud's DP 133 |
| After "not confirmed" | error raised | error raised, and the select is **unavailable** until the head is read again |

Every attempt is recorded on the entity: `trial_result` (`confirmed_by_cloud`,
`confirmed_by_tunnel`, `unchanged`, `refused`, `not_confirmed`), `trial_at`, `trial_error`. The
entities also show `write_path: cloud_mqtt`, `write_scope: head`, `write_trial: true`.

Two limits, by construction:

- **DP 101 has no source independent of the gateway.** The tunnel reads the thermostat cluster
  only; viewing direction lives in the user-interface cluster. The per-device route is the
  gateway's view, as the echo is. The proof that the head applied it is **its display**, looked
  at by Rémi. A cloud confirmation without the display turning is the "accepted but not applied"
  failure.
- **The meaning of the flag `0x4014`** (false horizontal, true vertical) was Zigbee2MQTT's reading
  and was confirmed on one head on 2026-11-20. The write still refuses to send when the flag and
  the cloud disagree under that reading, and step 1 below stays as a check on any new head.

### Arming (options of the integration)

1. `enable_cloud_mqtt` on; `enable_local` on (for DP 133).
2. `cloud_mqtt_supervised_head`: the test head, **isolated**, verified model, online, nobody
   relying on it. Rémi chooses it on site.
3. `cloud_mqtt_supervised_dps`: tick `101` **or** `133`, one per session (one DP at a time).
4. Optional, for DP 101: `post_command_refresh` on, so the switch follows the per-device route
   right after the write instead of waiting for the bulk list (it lags for minutes).
5. The entry reloads. Check: "Cloud MQTT link" sensor on; the new entity exists on the test head
   only, with `write_trial: true`; no such entity on any other head.

### DP 133 — orientation

1. **Settle the mapping first (read only).** On the test head, look at the head itself (how it is
   mounted), the select's `raw` (the flag) and its `cloud_value`, and the app's mounting screen.
   Record the three. If the select is unavailable, wait for the daily pass or restart the
   integration (a pass runs after each start). Expected under Zigbee2MQTT's reading: `raw: false`
   with a horizontal head and `cloud_value: Horizontal`. Anything else: **stop**, record it in the
   alignment doc (open question), write nothing.
2. **Write** the other orientation from the select, once. The call takes up to two minutes (tunnel
   reads). Outcomes:
   - returns, `trial_result: confirmed_by_tunnel`: the flag moved;
   - `refused`: nothing was sent (the error says why);
   - `not_confirmed`: the frame went out and the flag did not move; the select goes unavailable.
     Read the head (local survey service) before anything else.
3. **Read back** the app's mounting screen and the cloud's DP 133 (`cloud_value`, after the next
   poll). Watch the head for a minute: does it react (display, motor, adaptation run)? Note it.
4. **Restore** the original orientation the same way and read it back the same way.

### DP 101 — viewing direction

1. **Baseline.** Look at the head's display and note which way it reads; note the switch's state
   and the app's viewing-direction toggle. They must agree; if the switch is unavailable, the
   cloud does not carry DP 101 for this head: stop.
2. **Write** the other value from the switch, once (up to a minute). `confirmed_by_cloud` means the
   per-device route shows it; it does not mean the head applied it.
3. **Look at the display.** It must have turned. If the cloud and the app changed and the display
   did not: the "accepted but not applied" failure, stop and restore from the app.
4. **Restore** the original value from the switch, look at the display again.

### Rolling back

- Untick the DP in `cloud_mqtt_supervised_dps` and set `cloud_mqtt_supervised_head` back to none
  (and `enable_cloud_mqtt` off unless a proven DP needs it). The entry reloads, the entity and its
  registry entry are removed; nothing else changes.
- A head left in the wrong orientation or viewing direction: set it back from the Danfoss app on
  that head's page (the reference publisher), then read it again (tunnel for 133, display for 101).

### After the trial

Record in the local validation notes (never real identifiers in the repository): model, firmware,
what step 1 showed, confirmation delays, what the head did. Then:

- the answer to the mapping question goes into `docs/zigbee2mqtt-alignment.md` §6 and the comment
  of `mqtt_write.ORIENTATION_FLAG` (and the read-only "orientation" sensor if inverted);
- a DP that passed moves from `MQTT_CANDIDATE_DPS` to `MQTT_WRITE_DPS` in a change of its own,
  which also decides how its entity exists outside a trial.

## Sheet — head settings through the local tunnel

Batch C2 of `docs/zigbee2mqtt-alignment.md`: four head settings that Zigbee2MQTT writes as
Danfoss manufacturer attributes of the thermostat cluster (`0x0201`, manufacturer code `0x1246`),
written here the same way through the local Zigbee tunnel of the Ally gateway. Batch C3 added the
**external measured room sensor** (`0x4015`, int16, hundredths of °C), the **external window
open** flag (`0x4003`, boolean) and **load balancing** (`0x4032`, boolean); batch C4 the
**automatic adaptation run** on/off (`0x404E` `adaptation_run_settings`, boolean) — the
enable/disable of the nightly run, **not** the launch/cancel command `0x404C`
`adaptation_run_control`, which is not implemented. All are closed by default: nothing exists and
nothing can be sent until the trial is armed for one head. This sheet completes the generic
procedure above; its preconditions and stop rules apply unchanged. **Rémi present, on site, for
every write.**

Status after the trials of 2026-11-20 and 21 (one isolated head):

- **Radiator covered, setpoint offset, regulation speed, valve exercise day and time**: each
  written and restored, `confirmed_by_tunnel`, nothing else changed on the head. No independent
  source showed them (the app has no screen for the offset; the public API's "radiator covered"
  did not follow).
- **Setpoint offset**: the raw value is in tenths (±25 written and read back) and a positive
  offset **raises the regulation target** without shifting the measured temperature. That raw 25
  means 2.5 °C is not proven: no plateau was reached in two attempts. To redo on a weekday, in a
  comfort slot.
- **Hold over time**: a valve exercise day written through the tunnel alone held one night. One
  setting, one head; nothing is established for the others (a tunnel-only preheat write does not
  hold, `docs/preheat.md`).
- **Not tried**: external room sensor, external window open, load balancing, automatic
  adaptation run.
- All stay closed in the code: a setting becomes proven in a change of its own.

### What the code does

| Trial key | Entity (trial head only) | Attribute, ZCL type | Values accepted |
|---|---|---|---|
| `radiator_covered` | `switch` "Radiator covered setting" | `0x4016`, boolean | on / off |
| `setpoint_offset` | `number` "Setpoint offset setting", °C | `0x404B`, int8 | −2.5 to 2.5 by 0.1, sent in tenths (raw −25 to 25) |
| `regulation_speed` | `number` "Regulation speed setting" | `0x4020`, uint8 | integer 1 to 10 |
| `valve_exercise` | `select` "Valve exercise day setting" and `time` "Valve exercise time setting" | `0x4010` enum8 / `0x4011` uint16 (minutes) | a weekday; a time HH:MM |
| `external_room_sensor` | `number` "External room sensor setting", °C | `0x4015`, int16 | −80 to 35 °C by 0.1, sent in hundredths (raw −8000 to 3500); **−80 °C (raw −8000) disables it** |
| `window_open_external` | `switch` "External window open setting" | `0x4003`, boolean | on / off |
| `load_balancing` | `switch` "Load balancing setting" | `0x4032`, boolean | on / off |
| `adaptation_run_settings` | `switch` "Automatic adaptation run" | `0x404E`, bitmap8 | on / off |

- **Exists when**: `enable_local` on, the key ticked in `local_supervised_settings`, the head chosen
  in `local_supervised_head`, a verified model, and the tunnel can address the head (node id,
  gateway key fetched). Grouped or isolated heads alike: the tunnel writes one head. Every other
  head has no such entity; disarming removes the entities and their registry entries.
- **Before sending**: the value is checked (type, range, step). A refused value sends nothing.
- **Write**: one manufacturer-specific Write Attributes frame. The valve exercise day and time
  are written together, as the existing `set_descaling` service does: the half not being changed
  is first read from the head itself, on the same link, never taken from a stored value (a head
  whose day is undefined must get a day before a time).
- **After the write**: the head's settings are read back through the tunnel (the same single-head
  read as the orientation trial, `async_refresh_settings`). The entity shows what the head said,
  never the value written. Errors raised:
  - `refused`: nothing was sent (invalid value, gateway unknown or unreachable);
  - `rejected`: the head answered the write with an error status, or the read-back holds another
    value — the entity shows the read-back;
  - `not_confirmed`: the head did not answer the read-back. The entity goes **unavailable** until
    the head is read again (the value shown before can no longer be trusted).
- Every attempt is recorded on the entity: `trial_result` (`confirmed_by_tunnel`, `refused`,
  `rejected`, `not_confirmed`), `trial_at`, `trial_error`, with `write_path: local`,
  `write_scope: head`, `write_trial: true`, and `raw` / `read_at` of the read shown.

Two limits, by construction:

- **The read-back uses the channel written.** The tunnel read is the head's own answer, which is
  better than a gateway cache, but it is not an independent source in the sense of
  `docs/architecture.md`. The Danfoss app (where it shows the setting) and the head itself are
  the independent sources of this trial.
- **The scale of the setpoint offset is not confirmed** (tenths of °C is Zigbee2MQTT's reading).
  The read-back proves the raw value only. Step 2 below bounds the risk.

### Before arming

1. Enable the read-only diagnostic sensors of the test head that are disabled by default:
   "Regulation speed", "Setpoint offset", "Valve exercise day", "Valve exercise time" (the
   "Radiator covered" binary sensor is on by default). They show the daily read, with `read_at`.
2. Restart the integration so that a settings pass runs (one runs after each start); wait until
   the sensors are available with a fresh `read_at`.
3. **Record `V0` for every setting**: the sensors' values and `raw` attributes, and the app's
   screen for the same settings when it has one. These are the restore values.

### Arming (options of the integration)

1. `enable_local` on.
2. `local_supervised_head`: the test head — online, nobody relying on it. The isolated head used
   for the earlier trials is the natural choice.
3. `local_supervised_settings`: tick **one** setting per session (one write at a time).
4. The entry reloads. Check: one log warning naming the setting under trial; the new entity exists
   on the test head only, with `write_trial: true`, and shows `V0`.

### Per setting

Each time: write once, read the outcome (`trial_result`), check the app and the head, then
restore `V0` from the same entity and read it back the same way.

1. **Radiator covered.** Flip it. Expected: `confirmed_by_tunnel`, the switch shows the new value.
   Check the app's setting if it shows one. No immediate thermal effect is expected (it changes
   how the head estimates the room temperature). Restore `V0`.
2. **Setpoint offset.** The tenths-of-°C scale is **not confirmed**, so the first write is
   `V0 + 0.1` (raw +1), never a large value: if the head read the raw value in whole degrees
   instead of tenths, the error stays at 1 °C. **Check it at once in the app**: if the app shows
   anything other than `V0 + 0.1 °C`, restore `V0` immediately and stop the offset trial. The
   offset shifts the temperature the head regulates to, not the one it measures, so the valve is
   no check: the scale is settled only by a source that shows the offset in °C. Without one (the
   app has no such setting), the scale stays unconfirmed after the trial: say so in the notes.
   Restore `V0`.
3. **Regulation speed.** Write `V0 ± 1`. No visible effect is expected in the short term. Check
   the app if it shows it. Restore `V0`.
4. **Valve exercise.** Change the day first (another weekday), check it reads back with the time
   unchanged; then change the time the same way. Optional independent check: put the exercise a
   few minutes ahead on today's weekday and watch or listen to the head at that time (the valve
   should run its exercise stroke) — not observed here so far. Restore day and time `V0`.
5. **External window open.** Flip it on, then off. Expected: `confirmed_by_tunnel`, the switch
   showing the new value. The head should treat the room as window-open while on (the internal
   window state and heat demand change); check the app/head if it shows one. Restore `V0` (off).
6. **Load balancing.** Only if you mean to: on an Ally gateway the room drives this, so a lone
   write may be ignored or re-driven by the gateway. If you try it, flip it, read the outcome,
   check nothing changed on another head of the room, and restore `V0` at once.
7. **External room sensor.** Write a plausible room temperature (e.g. `V0`'s room temp, or 20.0),
   and **check the app/head at once**: the head should regulate on the external value (its reading
   follows it; with `radiator_covered` false it applies an auto-offset). Then write **−80.0 °C**
   and confirm it reads back as −80.0 (disabled): the head returns to its own internal sensor.
   Note that a real live feed must be refreshed periodically — the head resets the value to −8000
   by itself after 30 min to 3 h (see below). Restore `V0` (−80.0 disables it if there was none).
8. **Automatic adaptation run.** Flip the "Automatic adaptation run" switch and read the outcome:
   `confirmed_by_tunnel`, the switch showing the new value. This only enables or disables the
   nightly adaptation (`0x404E`); it does **not** launch a run now — that is a separate command
   (`0x404C`, not implemented). No immediate visible effect is expected; the "adaptation run"
   status sensor (`0x404D`) will only change when a run actually occurs. Restore `V0`.

#### Feeding the external sensor live (user-side automation)

The integration exposes the setting only; it does not push a sensor's value on a timer. On a real
head the value must be refreshed every few minutes or the head disables it (Zigbee2MQTT docs: reset
to −8000 after 30 min in room-sensor mode, 3 h in auto-offset mode). Feed it from a Home Assistant
temperature sensor with a small automation, writing the `number` entity periodically, for example:

```yaml
alias: Room X — feed the external room sensor to the head
mode: single
triggers:
  - trigger: time_pattern
    minutes: "/5"
  - trigger: state
    entity_id: sensor.room_x_temperature
conditions:
  - condition: template
    value_template: "{{ states('sensor.room_x_temperature') | float(default=none) is not none }}"
  - condition: template  # do not feed a stale reading
    value_template: "{{ (now() - states.sensor.room_x_temperature.last_reported).total_seconds() < 1200 }}"
actions:
  - action: number.set_value
    target:
      entity_id: number.room_x_external_room_sensor_setting  # the trial head's entity
    data:
      value: "{{ states('sensor.room_x_temperature') | float }}"  # °C; the integration sends hundredths
```

To stop feeding it, set the `number` to −80 (disabled) or disarm the trial.

A packaged blueprint ships the same automation with a UI:
`blueprints/automation/danfoss_ally_cloud/external_room_sensor_feed.yaml`. Import it in Home
Assistant (Settings → Automations → Blueprints → Import, or **My Home Assistant** import of the raw
file URL), then create an automation from it, choosing the source temperature sensor and the trial
head's "External room sensor setting" number. It resends on a timer (default every 5 min, below the
head's reset window) and on each new reading, skips stale or implausible values, and never writes
the −80 °C disable value by accident. It remains closed-by-default in spirit: it does nothing until
the trial number exists (the trial is armed) and you create an automation from it.

Stop and restore at once if: a write raises `rejected` with a value nobody wrote; the app shows a
change on another head or another setting; the head reports a fault; or anything changes on
another head.

### Rolling back

- **A setting to its previous value**: write `V0` back from the same entity; it is confirmed by
  the same read-back. If the entity is unavailable after `not_confirmed`, restart the integration
  (the settings pass after start reads the head again), then write `V0`. The valve exercise can
  also be restored with the existing `set_descaling` service (day and time in one call).
- **Disarm**: untick every setting in `local_supervised_settings` and set `local_supervised_head`
  back to none. The entry reloads; the entities and their registry entries are removed; nothing
  else changes (the read-only sensors stay).

### After the trial

Record in the local validation notes (never real identifiers in the repository): model, firmware,
`V0`, each value written, `trial_result`, what the app and the head showed, delays. Then:

- the offset scale answer goes into `docs/zigbee2mqtt-alignment.md` §6 and the comment of
  `tunnel.TUNNEL_SETTINGS` (and the read-only "Setpoint offset" sensor if it is not tenths);
- a setting that passed becomes proven in a change of its own, which also decides how its entity
  exists outside a trial (today: trial head only).

## Returning to the released build

Turn the options off (the link closes on reload), then redeploy the released build and restart.
Nothing persists except the option values in the entry, inert without the code that reads them.
