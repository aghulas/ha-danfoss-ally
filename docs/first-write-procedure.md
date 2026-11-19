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
else: every other head keeps its normal routing (for window detection, the local tunnel), so an
automation or a click on another head can never go out through the channel under trial. With no
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

- an **isolated** test head (in no room) on a verified model, `online`, with nobody relying on it;
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

### DP 116 — open-window detection (candidate)

- **Entity**: the head's "window detection" switch.
- **Routing**: outside a trial, an isolated head's window detection is written through the **local
  tunnel** when it is enabled and the head answers locally (proven, immediate), and cloud MQTT will
  only be the fallback when the tunnel is not available. **During the trial**, DP 116 takes cloud
  MQTT even with the tunnel up, so the tunnel stays free as the read-back source.
- **Trial value**: the opposite of `V0` (a boolean). No thermal effect: the setting only changes
  what the head does if it detects an open window, so do it with the room's window closed.
- **Independent read-back**: the head's window-detection setting read through the **local tunnel**
  (the same local read that validated the tunnel write, W-4), which does not go through the cloud.
- **Restore**: toggle back to `V0`.
- **What it decides**: if proven, DP 116 moves to `MQTT_WRITE_DPS` and an isolated head without a
  usable tunnel gets a window-detection write. The tunnel stays the first choice when available.
- **To observe in passing — the confirmation fallback.** When the gateway's echo does not come
  within 15 s, the write is now confirmed by one read of the head through the **per-device** cloud
  route; it used the bulk list before. This also changed for DP 30, a path already proven, and the
  2026-11-19 validation did not exercise it (that write was confirmed by the echo, in under a
  second). During this trial, note for each write which source confirmed it (debug log line
  "confirmed by echo" / "confirmed by cloud"). If a write is ever confirmed "by cloud", check that
  the head really holds the value; if one fails as "not confirmed" while the head did apply it,
  record how long the per-device route took to show the value.

### DP 18 — upper setpoint bound (candidate)

- **Entity**: the test head's "upper setpoint bound" number. It exists only while DP 18 is open on
  that head (the head chosen in `cloud_mqtt_supervised_head`, `18` ticked in
  `cloud_mqtt_supervised_dps`), and is removed again when the trial is disarmed.
- **Trial value**: `V0 − 0.5 °C` (or `V0 + 0.5 °C` if that stays within 20–35 °C), keeping it above
  the head's comfort setpoint. The integration refuses a bound that would exclude the comfort or
  setback setpoint. No thermal effect: the bound only limits what can be set.
- **Independent read-back**: the head's maximum setpoint through the **local tunnel** (thermostat
  attribute `0x0016`, part of the local head read), then the app's settings screen.
- **Restore**: write `V0` back.

### DP 27 — lower setpoint bound, with DP 120 (candidate)

- **Entity**: the head's "lower setpoint bound" number (tick `27`, and `120` too — see below).
- **What is sent**: `{"27": v}`; and `{"27": v, "120": v}` in one frame when the new bound is
  **above the head's pause setpoint**. The app publishes DP 120 with DP 27 "when the pause setpoint
  must follow" (contract §4.2); the rule retained here — raise the pause setpoint to the new bound
  when it would fall under it — is this project's reading of that capture, **to confirm during the
  trial** by watching what the app itself sends in the same situation. If DP 120 is needed and not
  ticked, the write is refused with a message saying so.
- **Trial value**, in two steps:
  1. a value that does **not** move the pause setpoint, if the head allows one (lower bound raised
     while still at or under the pause setpoint) — proves DP 27 alone;
  2. `V0 + 0.5 °C` above the pause setpoint — proves the DP 27 + DP 120 frame. No thermal effect
     unless the head is in pause mode: check its mode first.
- **Independent read-back**: the head's minimum setpoint through the **local tunnel** (thermostat
  attribute `0x0015`); the pause setpoint in the app.
- **Restore**: write `V0` back. ⚠ Lowering the bound does **not** lower the pause setpoint again:
  restore the pause setpoint in the Danfoss app (or with the pause-setpoint entity once that DP is
  available), and read it back.

### DP 118 + 16 — comfort setpoint of an isolated head (candidate)

- **Entity**: the head's "comfort setpoint" number (tick `118` **and** `16`).
- **What is sent**, as the app does (contract §4.2): one MQTT frame `{"118": v, "16": v}`; once
  DP 118 is confirmed, the whole settings block `{"1", "118", "119", "121"}` through
  `settings.change` (`gwId` = the head's devId), with the head's current values and the new one.
  Only DP 118's confirmation is required: DP 16 (`temp_set`) may be overruled by the schedule.
- **Trial value**: `V0 − 0.5 °C`, **while the head is in a comfort slot**. DP 16 is the head's
  effective setpoint: sent during a setback slot it may make the head heat to the comfort value
  until the next transition. In a comfort slot the effect is at most half a degree down.
- **Independent read-back**, through the **local tunnel**:
  1. the head's weekly schedule — do the comfort slots carry the new value? **This is the open
     question of this DP.** For a room, a setpoint publish must be followed by a schedule rewrite
     (R3), otherwise the heads keep the old value in their transitions. Whether an isolated head
     needs the same is not established. If the schedule still carries the old value, the trial is
     **not** passed: a schedule rewrite (HTTP, proven for an isolated head, §4.1) has to be added
     to the write before the DP is promoted;
  2. the head's current setpoint (attribute `0x0012`) before and after — what did DP 16 do?
  3. the real preheat (attribute `0x0025`) — unchanged after the block, which carries DP 1.
- **Restore**: write `V0` back, then read the schedule again.

### DP 119 — setback setpoint of an isolated head (candidate)

- **Entity**: the head's "setback setpoint" number (tick `119`).
- **What is sent**: `{"119": v}` alone (no DP 109: the app does not send it for an isolated head),
  then the settings block as above.
- **Trial value**: `V0 − 0.5 °C`, **while the head is in a comfort slot**, so the setback value is
  not the one in force. For a room, the setback publish also applies the value at once as the
  current setpoint (contract §4.2, DP 109): check with the head's current setpoint (attribute
  `0x0012`) that DP 119 alone does not.
- **Independent read-back**: the head's weekly schedule through the local tunnel (setback periods),
  same open question as for DP 118.
- **Restore**: write `V0` back.

### DP 120 — pause setpoint of an isolated head (candidate)

- **Entity**: the head's "pause setpoint" number (tick `120`).
- **What is sent**: `{"120": v}`. No settings block (DP 120 is not part of it).
- **Trial value**: `V0 + 0.5 °C`, the head **not** in pause mode — no thermal effect.
- **Independent read-back**: no tunnel attribute is known for the pause setpoint; the app's
  settings screen is the independent source. Weaker than a tunnel read: say so in the record.
- **Restore**: write `V0` back.

### DP 1 — preheat (candidate; observation from the app first)

The known trap: over HTTP, DP 1 only changed the gateway cache while the head's real preheat (bit 1
of Zigbee attribute `0x0025`) did not move. The gateway's echo and the cloud read therefore confirm
nothing here; **only `0x0025` read through the local tunnel does**. Background and assessment:
`docs/cloud-mqtt-preheat-proposal.md`. Two stages; stage B is run only if stage A is positive.

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
     switch, proven), read `0x0025` back (= `V0`).
  3. If the head stayed at `V0` while **cloud DP 1 shows the trial value**, the gateway cache is
     out of step with the head — the HTTP failure, reproduced. Toggling the switch back does
     **not** fix it: the integration reads the head, finds it already at `V0` and publishes
     nothing (a publish the head does not react to could not be confirmed by the tunnel, so the
     integration never sends one). A tunnel write does not touch that cache either. Resynchronise
     from the **Danfoss app**, the reference publisher: set its preheat toggle to the head's value
     (`V0`'s bit 1), then read cloud DP 1 through the per-device route — it must show that value —
     and raw `0x0025` — it must still equal `V0`. Record both reads.
- **Passed** means only: this publish reaches the head. Promotion is a change of its own, which
  must say when cloud MQTT would be preferred to the tunnel that confirms it.

## Returning to the released build

Turn the options off (the link closes on reload), then redeploy the released build and restart.
Nothing persists except the option values in the entry, inert without the code that reads them.
