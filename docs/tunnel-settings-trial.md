# Head settings through the local tunnel — supervised trial

Batch C2 of `docs/zigbee2mqtt-alignment.md`: four head settings that Zigbee2MQTT writes as
Danfoss manufacturer attributes of the thermostat cluster (`0x0201`, manufacturer code `0x1246`),
written here the same way through the local Zigbee tunnel of the Ally gateway. **None has been
written on real hardware by the integration.** All are closed by default: nothing exists and
nothing can be sent until the trial is armed for one head. Three more settings were added in the same frame (batch C3): the **external measured room sensor**
(`0x4015`, int16, hundredths of °C), the **external window open** flag (`0x4003`, boolean) and
**load balancing** (`0x4032`, boolean). Same gate, same read-back; none written on real hardware.
One more setting was added in the same frame (batch C4): the **automatic adaptation run** on/off
(`0x404E` `adaptation_run_settings`, boolean). This is the enable/disable of the nightly adaptation
run, **not** the separate launch/cancel command `0x404C` `adaptation_run_control`, which is not
implemented. Same gate, same read-back; not written on real hardware.
This sheet completes the generic
procedure of `docs/first-write-procedure.md`; its preconditions and stop rules apply unchanged.
**Rémi present, on site, for every write.**

## What the code does

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

### Feeding the external sensor live (user-side automation)

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
