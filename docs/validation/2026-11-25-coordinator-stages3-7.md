# Stages 3–7 — coordinator write stages: supervised trial plan (PENDING)

**Status: not yet run.** Code for Stages 3–7 is implemented closed by default in `pydanfoss-cloud`
(`room_control.py`, `room_coordinator.py`, `room_store.py`, `room_view.py`, `write_job.py`) and
covered by synthetic tests only (`tests/test_room_coordinator_stages.py`). **Nothing was written to
a head to produce this file.**

See [`../first-write-procedure.md`](../first-write-procedure.md) and
[`2026-11-23-setpoint-fanout-stage2.md`](2026-11-23-setpoint-fanout-stage2.md) for general rules.
Arm **only one test room** (`--armed-room <room_id>`) and enable **one stage flag at a time**.

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
