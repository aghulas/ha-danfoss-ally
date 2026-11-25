# Stages 3–7 — coordinator write stages: supervised trial (PARTIAL — 2026-11-25)

**Status: partially run on 2026-11-25** on 4-head Zigbee2MQTT test room `Area X` + `014G2480` room
sensor (`danfoss-room-coordinator 0.2.0` / `pydanfoss-cloud 0.7.0`, Companion `2.0.5`, Zigbee2MQTT
`2.14.3-1`, anonymised). One stage flag was armed at a time; all flags were returned to `false` and
`Area X` restored to `14.0 °C` afterwards. Remaining items require physical presence or >35 min windows.

See [`../first-write-procedure.md`](../first-write-procedure.md) and
[`2026-11-23-setpoint-fanout-stage2.md`](2026-11-23-setpoint-fanout-stage2.md) for general rules.
Arm **only one test room** (`--armed-room <room_id>`) and enable **one stage flag at a time**.

## Live results (2026-11-25)

| Stage | Tested | Observed on hardware / Z2M | Remaining |
|---|---|---|---|
| **3** (`feed_external_sensor`) | Armed `feed_external_sensor: true` (`radiator_covered: false`) | **Z2M non-retained sensor finding**: after daemon restart (`12:57`), `zigbee2mqtt/<sensor>` is not retained, so `coordinator` lacked the `12:50` report (`humidity: null`, temperature fell back to head mean `16.3 °C`) until the next periodic report (`13:19` -> `13.77 °C / 62.1 %`, ~30 min cadence). | Observe initial `external_measured_room_sensor` `/set` across a `:20`/`:50` report + 35-min (`radiator_covered: true`) / 3-h (`false`) stop reset to `-8000`. |
| **4** (Schedules & modes) | R1 validation (`7` slots), `set_schedule`, `restore_schedule`, `bridge/devices` inspection | **R1 refusal**: rejected in `0.0 s` (`400 too many slots: 14 transitions`). **`set_schedule`**: Z2M `2.14.3-1` processed all 28 `weekly_schedule` ZCL frames + `programming_operation_mode: "schedule"` (`schedule_with_preheat -> schedule`) with zero errors; **`zhc:tz` warning** on `"mode": 1` (`ignoring provided mode value (1), this is now calculated automatically` — fixed by omitting `mode`). **`restore_schedule`**: succeeded in `12.4 s`. **`bridge/devices`**: Z2M `2.14.3-1` exposes **no `schedule_<day>`** properties. Note: Z2M `day_of_week`/`trigger_time` are the valve descaling day/time (not wall clock); head clock is `genTime` (verified via `preheat_time` in Nov 2026). | Direct MQTT `room/set-comfort-setback`, `room/set-mode` (`pause -> schedule`), and morning transition read-back (`[H]`). |
| **5** (`reconcile_drift`) | Armed `reconcile_drift: true`; pushed one individual head (`Area X-1`) to `15.0 °C` vs `desired.setpoint = 14.0 °C` (twice) | **Pass**: next coordinator tick (~9–11 s) wrote `{"occupied_heating_setpoint_scheduled": 14.0}` to `Area X-1/set` only; heads 2–4 untouched; `Area X-1` and `bridge/rooms` returned to `14.0 °C` (`drift: []`). | Manual dial test, 1-hour cooldown under sustained drift, `reconcile_blocked` after 3 failed attempts, `room/set-settings`, overnight preheat. |
| **6** (`feed_load_mean`) | Armed `feed_load_mean: true`, then `false` | **Pass**: all 4 heads (with `load_balancing_enable: true`) received `{"load_room_mean": 782}` and updated `-8000 -> 782`. On clean stop (`feed_load_mean: false`), all 4 heads reset back to `-8000.0`. | Compare valve openings over time with/without mean; stale mean behavior. |
| **7** (Holidays & window) | — | Not run remotely (`set_vacation` intentionally refuses Companion rooms in HA; `window_open_internal` requires physical draft). | `holiday/set` + restart end-edge reconciliation; physical open-window propagation across multi-head room. |

## Stage 3 — Room sensor feed (`--feed-external-sensor`)

- Confirm `014G2480` sensor is linked via `room/set-sensor` and no other producer is writing
  `external_measured_room_sensor` on the test heads (`2026-11-21-external-sensor-producer.md`).
- Test both `radiator_covered=true` (5 min floor / 20 min keep-alive) and `radiator_covered=false`
  (30 min floor / 2 h keep-alive).
- **Stop test**: stop the coordinator and confirm the head resets `external_measured_room_sensor`
  back to `-8000` after ~35 min (`radiator_covered=true`).

## Stage 4 — Weekly schedule, comfort / setback, modes

- Run `bridge/request/room/set-schedule` (with `comfort`, `setback`, `days`) and read back via
  `room/get-schedule` (check if `schedule_<day>` is populated by the installed Zigbee2MQTT).
- Test `room/set-comfort-setback` (verify R3 schedule rewrite) and `room/set-mode` (`pause` ->
  `schedule` / `restore_schedule`).
- **Settle `[H]`**: switch to `setpoint` and back to `schedule` with a head monitored directly;
  record whether `programming_operation_mode = setpoint` preserves the ZCL schedule on our firmware.
  Only set `mode_change_keeps_schedule: true` if proven.

## Stage 5 — Room-wide settings, preheat, reconciliation (`--reconcile-drift`)

- Run `room/set-settings` (`child_lock`, `window_detection`, `min_setpoint`, `max_setpoint`,
  `preheat`); confirm heads already matching receive no `/set`.
- Turn one head dial by hand and confirm:
  - `bridge/rooms` `drift` lists that head immediately;
  - reconciliation rewrites it with `occupied_heating_setpoint_scheduled` at most once per hour;
  - after 3 consecutive failed attempts, reconciliation stops and lists the head in
    `reconcile_blocked`.
- Overnight test: confirm `preheat` (`schedule_with_preheat`) holds over one night with no cloud.

## Stage 6 — Load balancing (`--feed-load-mean`)

- Test on a two-head room where both heads report `load_balancing_enable: true`.
- Verify `load_room_mean` shares one `/set` with `external_measured_room_sensor` when both are due.
- Compare valve openings with and without `load_room_mean`; observe clean stop (`-8000`) and what a
  stale mean does.

## Stage 7 — Holidays (`--enable-holidays`) & open window (`--propagate-window-open`)

- **Holidays**: schedule a short `holiday/set` window, confirm start edge writes
  `occupied_heating_setpoint_scheduled` + `setpoint` mode, stop the coordinator across the end
  edge, restart, and confirm `start()` restores `schedule` mode cleanly.
- **Open window**: open one window in a multi-head room, confirm the other heads receive
  `window_open_external: true` with no feedback loop, then close and check `window_open_external:
  false` (and max-duration expiry).
