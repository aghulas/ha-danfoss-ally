# Stage 2 — room setpoint fan-out: supervised trial (PENDING)

**Status: not yet run.** The Stage 2 code is merged closed (`pydanfoss-cloud` room coordinator,
`write_job.py` + `bridge/request/room/set-setpoint`, `aghulas/pydanfoss-cloud` PR #8). This note is
the plan for the supervised real-hardware trial of [`../z2m-cloud-parity.md`](../z2m-cloud-parity.md)
§7 Stage 2, to run in a later session with the owner present. **Nothing was written to a head to
produce this file** — it records the procedure and leaves the results blank.

See [`../first-write-procedure.md`](../first-write-procedure.md) for the general supervised-write
rules; this note only adds what is specific to the setpoint fan-out.

## Preconditions

- One Zigbee2MQTT **test room** on the coordinator, two or more heads, no Danfoss gateway involved.
- The coordinator running, **read-only** (no `armed_rooms`) and already publishing `bridge/rooms`
  for the room — its members confirmed online and reporting `occupied_heating_setpoint`.
- The room's `room_id` noted from `bridge/rooms`.
- A way to read each head back independently (the Zigbee2MQTT state topic is the confirmation the
  coordinator uses; cross-check in the Zigbee2MQTT UI / a second subscriber).

## Arming (one room only)

Arm **only** the test room, then restart the coordinator:

```bash
danfoss-room-coordinator --armed-room <room_id>
```

Confirm the start log shows `setpoint fan-out ARMED for room(s) <room_id>`. Every other room must
still refuse `set-setpoint` with `status: "closed"` — check one.

## Writes to try (one explicit go-ahead each)

For each, publish to `<base>/bridge/request/room/set-setpoint` and read the per-head report on
`<base>/bridge/response/room/set-setpoint`, then read each head back independently.

1. **User setpoint** — `{"room_id": "<room_id>", "setpoint": <value>, "source": "user"}`.
   Expect: one `/set` per head carrying `occupied_heating_setpoint`, every head `applied`, the heads
   reporting the new value, `bridge/rooms` `desired.setpoint` = value and `drift` empty.
2. **Scheduled setpoint** — `{..., "source": "coordinator"}`.
   Expect: `/set` carrying `occupied_heating_setpoint_scheduled`; same confirmation; note whether the
   valve response differs from the user write (the "aggressive vs scheduled" distinction, §3).
3. **Out-of-bounds / off-step value** — expect `status: "error"`, `job_status: "failed"`, **no
   `/set` at all** (value validation before send).
4. **One head powered down** — expect that head `unreachable` after the bounded retries, the others
   `applied`, `job_status: "partial"`.

## Results (to fill in during the trial)

| # | Input | Per-head report | Independent read-back | Valve behaviour | Verdict |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
| 4 | | | | | |

## After the trial

- Remove the room from `armed_rooms` again (back to read-only) until the next supervised step.
- Record anomalies (lag, a head that reports late, mismatch retries) and whether the 0.1 °C match
  tolerance and the default timeout/retries fit the hardware.
- If clean, Stage 2 can be marked validated in [`../z2m-cloud-parity.md`](../z2m-cloud-parity.md) §7.
