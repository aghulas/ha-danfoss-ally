# First real cloud-MQTT write of a DP — supervised procedure

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
confirmed by a read of the head through the local tunnel only (its sheet below).

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

### DP 1 — preheat (candidate; stage A positive, stage B failed, 2026-11-20)

The known trap: over HTTP, DP 1 only changed the gateway cache while the head's real preheat (bit 1
of Zigbee attribute `0x0025`) did not move. The gateway's echo and the cloud read therefore confirm
nothing here; **only `0x0025` read through the local tunnel does**. Background and assessment:
`docs/cloud-mqtt-preheat-proposal.md`. Two stages; stage B is run only if stage A is positive.

Result on 2026-11-20 (tables in the proposal): stage A positive — the app's toggle reached the head
within a minute; stage B **not passed** — the integration's `{"1": true}` changed the cloud's DP 1
and not the head, 15 minutes later still. DP 1 stays a closed candidate. Do not repeat stage B
with the same frame: change what is sent first (see the proposal's open question).

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

- **What is sent**: one MQTT frame `{"1": bool}`.
- **Arm**: `enable_local` and `enable_cloud_mqtt` on, the test head designated, DP 1 ticked.
  Without `enable_local` there is no preheat switch at all, so ticking DP 1 does nothing. The
  head's preheat switch must show `write_path: cloud_mqtt` and `write_trial: true`; the preheat
  switch of another head must show `write_path: local`. While armed, the tunnel never writes this
  head's preheat: with the MQTT link down the write fails instead of falling back.
- **Trial value**: the opposite of `V0`'s bit 1.
- **What the call does**: reads the head through the tunnel first (no answer → nothing sent;
  already at the value → nothing sent), publishes, then reads the head every 10 s for 60 s at most.
  It returns only when bit 1 shows the value; otherwise it raises "not confirmed". The echo and the
  cloud are not consulted.
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

## Returning to the released build

Turn the options off (the link closes on reload), then redeploy the released build and restart.
Nothing persists except the option values in the entry, inert without the code that reads them.
