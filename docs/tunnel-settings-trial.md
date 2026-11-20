# Head settings through the local tunnel — supervised trial

Batch C2 of `docs/zigbee2mqtt-alignment.md`: four head settings that Zigbee2MQTT writes as
Danfoss manufacturer attributes of the thermostat cluster (`0x0201`, manufacturer code `0x1246`),
written here the same way through the local Zigbee tunnel of the Ally gateway. **None has been
written on real hardware by the integration.** All are closed by default: nothing exists and
nothing can be sent until the trial is armed for one head. This sheet completes the generic
procedure of `docs/first-write-procedure.md`; its preconditions and stop rules apply unchanged.
**Rémi present, on site, for every write.**

## What the code does

| Trial key | Entity (trial head only) | Attribute, ZCL type | Values accepted |
|---|---|---|---|
| `radiator_covered` | `switch` "Radiator covered setting" | `0x4016`, boolean | on / off |
| `setpoint_offset` | `number` "Setpoint offset setting", °C | `0x404B`, int8 | −2.5 to 2.5 by 0.1, sent in tenths (raw −25 to 25) |
| `regulation_speed` | `number` "Regulation speed setting" | `0x4020`, uint8 | integer 1 to 10 |
| `valve_exercise` | `select` "Valve exercise day setting" and `time` "Valve exercise time setting" | `0x4010` enum8 / `0x4011` uint16 (minutes) | a weekday; a time HH:MM |

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

## Before arming

1. Enable the read-only diagnostic sensors of the test head that are disabled by default:
   "Regulation speed", "Setpoint offset", "Valve exercise day", "Valve exercise time" (the
   "Radiator covered" binary sensor is on by default). They show the daily read, with `read_at`.
2. Restart the integration so that a settings pass runs (one runs after each start); wait until
   the sensors are available with a fresh `read_at`.
3. **Record `V0` for every setting**: the sensors' values and `raw` attributes, and the app's
   screen for the same settings when it has one. These are the restore values.

## Arming (options of the integration)

1. `enable_local` on.
2. `local_supervised_head`: the test head — online, nobody relying on it. The isolated head used
   for the earlier trials is the natural choice.
3. `local_supervised_settings`: tick **one** setting per session (one write at a time).
4. The entry reloads. Check: one log warning naming the setting under trial; the new entity exists
   on the test head only, with `write_trial: true`, and shows `V0`.

## Per setting

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

Stop and restore at once if: a write raises `rejected` with a value nobody wrote; the app shows a
change on another head or another setting; the head reports a fault; or anything changes on
another head.

## Rolling back

- **A setting to its previous value**: write `V0` back from the same entity; it is confirmed by
  the same read-back. If the entity is unavailable after `not_confirmed`, restart the integration
  (the settings pass after start reads the head again), then write `V0`. The valve exercise can
  also be restored with the existing `set_descaling` service (day and time in one call).
- **Disarm**: untick every setting in `local_supervised_settings` and set `local_supervised_head`
  back to none. The entry reloads; the entities and their registry entries are removed; nothing
  else changes (the read-only sensors stay).

## After the trial

Record in the local validation notes (never real identifiers in the repository): model, firmware,
`V0`, each value written, `trial_result`, what the app and the head showed, delays. Then:

- the offset scale answer goes into `docs/zigbee2mqtt-alignment.md` §6 and the comment of
  `tunnel.TUNNEL_SETTINGS` (and the read-only "Setpoint offset" sensor if it is not tenths);
- a setting that passed becomes proven in a change of its own, which also decides how its entity
  exists outside a trial (today: trial head only).
