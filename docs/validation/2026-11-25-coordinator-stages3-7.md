# Stages 3–7 — coordinator write stages: supervised trial (PARTIAL — 2026-11-25)

**Status: live on `Area X` (2026-11-25 – 2026-11-27)** on 4-head Zigbee2MQTT test room `Area X` + `014G2480` room
sensor (`danfoss-room-coordinator 0.2.2` / `pydanfoss-cloud 0.7.2`, Companion `2.0.9`, Zigbee2MQTT
`2.14.3` / `zhc 26.125.0`, anonymised). `Area X` is running live with `feed_external_sensor: true`,
`reconcile_drift: true`, `enable_holidays: true` (`feed_load_mean: false`, `propagate_window_open: false`).
Remaining items require physical presence or multi-day / >35 min windows.

See [`../first-write-procedure.md`](../first-write-procedure.md) and
[`2026-11-23-setpoint-fanout-stage2.md`](2026-11-23-setpoint-fanout-stage2.md) for general rules.
Arm **only one test room** (`--armed-room <room_id>`) and enable **one stage flag at a time**.

## Live results (2026-11-25)

| Stage | Tested | Observed on hardware / Z2M | Remaining |
|---|---|---|---|
| **3** (`feed_external_sensor`) | Armed `feed_external_sensor: true` (`radiator_covered: false`) across a `:20` `014G2480` report | **Pass on event-driven feed**: at `16:19:55`, `zigbee2mqtt/<sensor>` emitted `13.8 °C / 63.94 %`; coordinator published `{"external_measured_room_sensor": 1380}` to all 4 `/set` topics in the same tick and all 4 heads updated `-8000 -> 1380`. Note: non-retained Z2M sensors leave coordinator without cached temperature after a restart until the next `:20`/`:50` report. Earlier pre-2.0.5 feed stopped at `12:20` and heads self-reset to `-8000` at `15:11–15:12` (~2h51m, `radiator_covered: false`). | 35-min stop test with `radiator_covered: true`. |
| **4** (Schedules & modes) | R1 validation (`7` slots), `set_schedule`, `restore_schedule`, `room/set-comfort-setback`, `room/set-mode`, plus **`dayofweek` list fix (`0.7.2`/`0.2.2`/`2.0.9`)** on `2026-11-27` | **Pass**: R1 rejected; `0.2.1` hit a hidden bug at Friday `08:30` (heads switched to legacy `19.0 °C` instead of `21.0 °C` because `zhc 26.125.0` evaluates integer `dayofweek` bitmasks to `0`). Fixed to pass English day-name lists (`["friday"]`), rewrote via `0.2.2` `companion_set_room_comfort_setback(21, 14)` (`51.1 s`), and all 4 heads immediately switched `19 -> 21 °C` with `0` Z2M warnings (`drift: []`). | Verify `18:00` setback, weekend `14.0 °C`, and Monday `08:30` comfort transitions; settle `[H]` (`mode_change_keeps_schedule`). |
| **5** (`reconcile_drift` & settings) | `reconcile_drift: true` (`Area X-1` pushed to `15.0 °C` vs `desired: 14.0 °C`); `room/set-settings`, HA `2.0.8` switches; **overnight preheat observation (2026-11-26 & 2026-11-27)** | **Pass on settings & overnight preheat**: `set-settings` (`preheat: true`) and `child_lock` HA switch synced all 4 heads (`drift: []`). On both mornings (`Thu` `06:00` and `Fri` `06:05`), heads autonomously ramped early without cloud (`preheat_time` for `08:30`, `sensor` rose `13.2 -> 15.6 °C` and `13.8 -> 15.8 °C`). (`pydanfoss-cloud 0.7.3` pending release adds `schedule`-mode `scheduled_setpoint` drift detection + fresh-state schedule confirm.) | Physical manual dial test, 1-hour cooldown under sustained drift, `reconcile_blocked` after 3 failed attempts; deploy `0.7.3` -> `0.2.3`. |
| **6** (`feed_load_mean`) | Armed `feed_load_mean: true`, then `false` | **Pass**: all 4 heads (with `load_balancing_enable: true`) received `{"load_room_mean": 782}` and updated `-8000 -> 782`. On clean stop (`feed_load_mean: false`), all 4 heads reset back to `-8000.0`. | Compare valve openings over time with/without mean; stale mean behavior. |
| **7** (Holidays & window) | Armed `enable_holidays: true`, published short `holiday/set` (`16:20–16:23`, `14.0 °C`), observed end edge, then `holiday/cancel`; **restart-across-end test** (`19:40–19:43`, coordinator stopped `19:41`, restarted `19:44`) via HA `2.0.8` `companion_set_holiday` / `companion_cancel_holiday` | **Pass on holidays (live edge & stopped-across-end restart)**: active holiday forced `mode: "holiday"` / `setpoint` (`14.0 °C`); both the live `16:23` edge and startup reconciliation after the `19:44` restart automatically restored `mode: "schedule"` (`schedule_with_preheat`, `drift: []`); `companion_cancel_holiday` cleared `bridge/holidays`. | Physical open-window propagation (`propagate_window_open`). |

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

## Remaining / Next steps (as of 2026-11-27)

- **Deploy `pydanfoss-cloud 0.7.3` -> `danfoss-room-coordinator 0.2.3`**: adds `scheduled_setpoint`
  drift detection/reconciliation in `schedule` mode (3-min transition grace) and fresh post-write
  confirmation in `_run_schedule_job`.
- **Observe scheduled cycles**: confirm `18:00` setback (`14.0 °C`), weekend `14.0 °C`, and Monday
  `08:30` comfort (`21.0 °C`) transitions hold across all days, and settle `[H]`
  (`mode_change_keeps_schedule`).
- **Stage 6 (`feed_load_mean: true`)**: enable load balancing on `Area X`, compare valve openings,
  and track battery impact over ~2 weeks before enabling additional rooms.
- **On-site physical tests**: Stage 2 Case 4 (head powered off), Stage 3 35-min stop test with
  `radiator_covered: true`, Stage 5 manual dial + 1h cooldown + `reconcile_blocked`, and Stage 7
  physical open-window propagation (`propagate_window_open`).
- **Cutover & cloud tracks**: Stage 8 (generalise Z2M rooms, remove legacy `_2` duplicates per
  `docs/v2-cutover.md`, HACS inclusion PR) plus Cloud MQTT 24 h probe (`cloud_mqtt_probe`) and
  cloud `real-validation-plan.md` remaining items (`W-6`, `§2b`, DP 133/101).
