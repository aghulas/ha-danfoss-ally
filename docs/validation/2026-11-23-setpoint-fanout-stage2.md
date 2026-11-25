# Stage 2 — room setpoint fan-out: supervised trial (PARTIAL — 2026-11-25)

**Status: partially validated on 2026-11-25** (4-head Zigbee2MQTT test room `Area X`, add-on `0.2.0` /
`pydanfoss-cloud 0.7.0`, Companion `2.0.5`, anonymised). Cases 1 and 3 passed against the
coordinator and all 4 heads; Cases 2 (`source: "coordinator"` direct MQTT) and 4 (powered-down head)
remain pending on site.

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

## Results (2026-11-25 trial on 4-head `Area X`)

| # | Input | Per-head report | Independent read-back | Valve behaviour | Verdict |
|---|---|---|---|---|---|
| 1 | `climate.set_temperature` (`14.0 -> 14.5 -> 14.0 °C`, `source: "user"`) | HA service returned HTTP `500` after `15.0–15.5 s` (`BRIDGE_REQUEST_TIMEOUT = 15.0` too short for 4 sleeping heads) | `bridge/rooms` showed `desired.setpoint`, `setpoint`, and `drift: []`; all 4 head entities updated to `14.5 °C` then back to `14.0 °C` | Normal heating state | **Pass on hardware**; Companion timeout bumped `15s -> 60s` |
| 2 | Scheduled setpoint (`source: "coordinator"`) | — | — | — | **Pending** (covered indirectly via Stage 5 `reconcile_drift` writing `occupied_heating_setpoint_scheduled`) |
| 3 | Out-of-bounds (`22.0 °C` > `max_temp: 21.0`) | Refused at HA layer in `0.9 s` (`400 Provided temperature 22.0 is not valid. Accepted range is 5.0 to 21.0`) | All 4 heads untouched | No change | **Pass** |
| 4 | One head powered down | — | — | — | **Pending** (requires physical power-off on site) |

## Findings & after the trial

- **Companion RPC timeout**: Sequential Zigbee writes + confirmation on 4 sleeping TRVs regularly
  exceeded `15.0 s` (`BRIDGE_REQUEST_TIMEOUT`), triggering a false HA `500` even though all 4 heads
  applied cleanly (`drift: []`) and `setpoint_timeout_s` on the coordinator is `30.0 s`. Raised
  `BRIDGE_REQUEST_TIMEOUT` to `60.0 s` in `mqtt_companion.py`.
- Re-verification confirmed `Area X` restored to `14.0 °C` with `drift: []`.
