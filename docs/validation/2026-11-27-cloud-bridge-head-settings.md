# Cloud-bridge head settings — supervised trial (VALIDATED — 2026-11-27)

**Status: validated on 2026-11-27** on real heads behind Danfoss gateways (anonymised):

- add-on `danfoss2mqtt` `0.1.7`, with `pydanfoss-cloud` `0.7.6`;
- Companion `2.0.16`;
- then `0.1.8` / `0.7.7` / `2.0.17` for the follow-up fixes, and for the room-route writes completed on
  2026-11-28.

This trial covers the settings the `danfoss2mqtt` bridge writes for a cloud head: child lock, open-window
detection, and the upper and lower setpoint bounds. It does not cover the setpoint, which was proven
earlier.

The general rules are in [`../first-write-procedure.md`](../first-write-procedure.md). The proven channels are in
[`../interface-contract.md`](../interface-contract.md) §4.2 and the bridge contract in
[`../companion-contract.md`](../companion-contract.md) §3 (`danfoss.set_keys`).

## What is written, and through which channel

| Setting | Z2M `/set` key | DP | Grouped head (room group publish) | Isolated head (cloud-MQTT `publishDps`) |
|---|---|---|---|---|
| Child lock | `keypad_lockout` / `child_lock` | 30 | yes — **the whole room** | yes |
| Window detection | `window_open_feature` | 116 | yes — **the whole room** | yes |
| Upper bound | `max_heat_setpoint_limit` | 18 | yes — **the whole room** | yes |
| Lower bound | `min_heat_setpoint_limit` | 27 (+120 when above the pause setpoint) | no group route: refused | yes |

The bridge advertises the keys each head accepts right now in `bridge/devices` (`danfoss.set_keys`). The
integration opens an entity only for an advertised key; any other key stays unavailable.

On a grouped head the entities carry `write_scope: room` and `room_head_count`, so the UI says that the
write reaches every head of the room.

## Gate

Two add-on options control the writes:

- `head_settings_writes`: `false` by default. While it is off, no setting key is advertised and every setting
  `/set` is refused.
- `head_settings_trial_head`: one device id. While it is set, only that head is open.

The trial ran with the gate confined to one head at a time. Each write had its own go-ahead from the owner.
Each was read back independently:

- through the per-device cloud route (MCP connector `danfoss-ally`), which does not depend on the channel used;
- then on the bridge's state topic and in Home Assistant, typically after 20–50 s.

## Results

### Isolated head (`Head I`, service room, manual mode 5 °C) — cloud-MQTT channel

| # | Write | Independent read-back | Verdict |
|---|---|---|---|
| 1 | Child lock on → off (DP 30) | Cloud read showed it locked, then unlocked; HA followed | **Pass** |
| 2 | Window detection on → off (DP 116) | Cloud read followed both values; HA followed | **Pass** |
| 3 | Upper bound 35 → 30 → 35 °C (DP 18) | Cloud read followed each step; HA followed | **Pass** |
| 4 | Lower bound 5 → 6 → 5 °C (DP 27) | Cloud read followed. Going up, the pause setpoint (DP 120) followed to 6 °C in the same frame. Going down, the pause stayed at 6 °C (see findings) | **Pass**, with one limit |

The head was put back in its exact original state. The pause setpoint went back to 5 °C through the MCP
connector (DP 120, gateway echo).

### Two-head room (`Room R`, corridor, both heads normally locked) — room group publish

| # | Write | Independent read-back | Verdict |
|---|---|---|---|
| 5 | Unlock asked on head 1 only | **Both** heads unlocked in the cloud in under 30 s. HA showed `write_scope: room`, `room_head_count: 2` | **Pass** (room scope confirmed) |
| 6 | Relock | Both heads locked again; about 50 s unlocked in all | **Pass** |

HA and the bridge did not show the unlocked state in between: their 180 s poll is longer than the 50 s it
lasted. Only the cloud read saw it, which is expected because nothing on those paths sets state in advance.

### Same room, 2026-11-28 — window detection and upper bound through the room route

This ran with the gate open to every head (see Rollout), Companion `2.0.17`, add-on `0.1.8`. Each write was asked on
head 1 only, from Home Assistant, and each had its own go-ahead. Both heads were read back through the per-device
cloud route right after each write.

| # | Write | Independent read-back | Verdict |
|---|---|---|---|
| 7 | Window detection on → off (DP 116) | **Both** heads showed it off | **Pass** |
| 8 | Window detection back on | Both heads showed it on | **Pass** |
| 9 | Upper bound 21 → 21.5 °C (DP 18) | Both heads at 21.5 °C | **Pass** |
| 10 | Upper bound back to 21 °C | Both heads at 21 °C | **Pass** |

The bound was raised and not lowered. Comfort was at 21 °C, so a bound under 21 °C could have pulled that
setpoint down, and putting the bound back would not have raised it again.

No other setting or setpoint moved, and the room ended in its exact original state. One cloud field,
`heat_available`, went from true to false on both heads during the trial. None of these writes touches it. It most
likely reflects the boiler idling at night.

### Rollout

After the trial, the trial head was cleared and the gate was opened to every head:

- 66 grouped heads advertise the group keys;
- 33 isolated heads advertise the MQTT keys.

After `2.0.17` was installed, the 66 grouped upper-bound numbers carry `write_scope: room`. The isolated heads
carry `write_scope: head`.

## Findings & after the trial

- **The pause setpoint does not come back down.** When the lower bound goes down, the pause setpoint stays
  where the earlier raise put it. The app does not lower it either, and the bridge has no Z2M key for the pause
  setpoint. We deliberately did not add an automatic rewrite: it would be a write the app does not make. A
  "pause setpoint" setting would be its own trial.
- **A manual setpoint can sit below the lower bound.** In the trial, a manual 5 °C stayed under a 6 °C bound, and
  the head did not realign it.
- **The bridge's success line is INFO**, so it does not show in the add-on log at the default level. Always read
  back through the cloud.
- **Fixed after the trial:**
  - `window_open_internal` was published as the raw integer from the cloud push (`1` = closed). It is now the
    Z2M text (`quarantine` / `closed` / `hold` / `open` / `external_open`), in `pydanfoss-cloud` `0.7.7`.
  - The bound numbers of a grouped head now state their room scope (`2.0.17`).
  - The text form of `window_open_internal` is not yet seen on site: the key only appears with a cloud push
    that carries the window state.
- **All three room-route settings are now proven through the bridge:** the child lock on 2026-11-27, and window
  detection and the upper bound on 2026-11-28 (writes 7–10). The lower bound has no group route.
