# Viewing direction (DP 101) and orientation (DP 133) — supervised trial

Batch C of `docs/zigbee2mqtt-alignment.md`: the first new head-setting writes of the Zigbee2MQTT
alignment. Both are written over Tuya cloud MQTT exactly as the Danfoss app does for an isolated
head (`docs/interface-contract.md` §4.2: `{"101": bool}`, `{"133": "Vertical" | "Horizontal"}`).
Neither has been written on real hardware by the integration. Both are **closed candidates**
(`api.writes.MQTT_CANDIDATE_DPS`): nothing exists and nothing can be sent until the trial is armed
for one head. This sheet completes the generic procedure of `docs/first-write-procedure.md`; its
preconditions and stop rules apply unchanged. **Rémi present, on site, for every write.**

## What the code does

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
- **The meaning of the flag `0x4014` is not established** (false horizontal, true vertical is
  Zigbee2MQTT's reading). The write refuses to send when the flag and the cloud disagree under that
  reading. Step 1 below answers the question before anything is written.

## Arming (options of the integration)

1. `enable_cloud_mqtt` on; `enable_local` on (for DP 133).
2. `cloud_mqtt_supervised_head`: the test head, **isolated**, verified model, online, nobody
   relying on it. Rémi chooses it on site.
3. `cloud_mqtt_supervised_dps`: tick `101` **or** `133`, one per session (one DP at a time).
4. Optional, for DP 101: `post_command_refresh` on, so the switch follows the per-device route
   right after the write instead of waiting for the bulk list (it lags for minutes).
5. The entry reloads. Check: "Cloud MQTT link" sensor on; the new entity exists on the test head
   only, with `write_trial: true`; no such entity on any other head.

## DP 133 — orientation

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

## DP 101 — viewing direction

1. **Baseline.** Look at the head's display and note which way it reads; note the switch's state
   and the app's viewing-direction toggle. They must agree; if the switch is unavailable, the
   cloud does not carry DP 101 for this head: stop.
2. **Write** the other value from the switch, once (up to a minute). `confirmed_by_cloud` means the
   per-device route shows it; it does not mean the head applied it.
3. **Look at the display.** It must have turned. If the cloud and the app changed and the display
   did not: the "accepted but not applied" failure, stop and restore from the app.
4. **Restore** the original value from the switch, look at the display again.

## Rolling back

- Untick the DP in `cloud_mqtt_supervised_dps` and set `cloud_mqtt_supervised_head` back to none
  (and `enable_cloud_mqtt` off unless a proven DP needs it). The entry reloads, the entity and its
  registry entry are removed; nothing else changes.
- A head left in the wrong orientation or viewing direction: set it back from the Danfoss app on
  that head's page (the reference publisher), then read it again (tunnel for 133, display for 101).

## After the trial

Record in the local validation notes (never real identifiers in the repository): model, firmware,
what step 1 showed, confirmation delays, what the head did. Then:

- the answer to the mapping question goes into `docs/zigbee2mqtt-alignment.md` §6 and the comment
  of `mqtt_write.ORIENTATION_FLAG` (and the read-only "orientation" sensor if inverted);
- a DP that passed moves from `MQTT_CANDIDATE_DPS` to `MQTT_WRITE_DPS` in a change of its own,
  which also decides how its entity exists outside a trial.
