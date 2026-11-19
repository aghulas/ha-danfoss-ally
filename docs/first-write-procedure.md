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

- **Entity**: the head's "upper setpoint bound" number. It exists only while DP 18 is open (tick
  `18` in `cloud_mqtt_supervised_dps`).
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

## Returning to the released build

Turn the options off (the link closes on reload), then redeploy the released build and restart.
Nothing persists except the option values in the entry, inert without the code that reads them.
