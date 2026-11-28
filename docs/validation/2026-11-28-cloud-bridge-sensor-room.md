# Cloud-bridge sensor room — supervised trial plan (NOT RUN)

**Status: plan only, not run.** Nothing in this file has touched real hardware through the bridge. Every live
write below needs Rémi's explicit go-ahead, **one go-ahead per write**, given at the keyboard.

What it covers: putting a cloud room sensor (`014G2480`, served by `danfoss2mqtt`) that is in no Danfoss room
into the Tuya room of the heads it should serve, from the sensor's page in the integration's side panel
(`sensor_room`, contract [`../companion-contract.md`](../companion-contract.md) §3, design
[`../sensor-room-assign.md`](../sensor-room-assign.md)). Then taking it out and putting it back, to prove both
routes. The general rules are in [`../first-write-procedure.md`](../first-write-procedure.md).

⚠ **This changes what the room's heads regulate on.** A sensor in a room is meant to become the reference
measurement of its heads (`ext_measured_rs` stops being -8000).

## What is written, and how it is checked

| Step | Who | What |
|---|---|---|
| Ask | Panel (admin) → WebSocket `sensor/set_room` | Checks: sensor known, `sensor_room` advertised, room of its home on `bridge/sensor_rooms`, not in another room, no other sensor in the room. Publishes `{"sensor_room": {"room_id"}}` on the sensor's `/set`. Shows "Awaiting the bridge…" |
| Validate | Bridge | Gate open for this sensor; fresh reads of the home's rooms (`m.life.group.room.map.get`) and device → room map (`m.life.my.group.device.sort.list` v2.1); same checks |
| Write | Bridge | One `smartlife.m.custom.wkf.device.relation.save` (put in) or `.delete` (take out) `{bizId, bizType: 6, parentId, parentType: 4}` |
| Read back | Bridge | Re-reads the device → room map (up to 3 reads, 5 s apart), republishes `bridge/sensor_rooms` at once with what it read; logs "confirmed" or "NOT confirmed" |
| Show | Panel | Re-reads the overview every 3 s (2 min at most) and clears "Awaiting" only when `bridge/sensor_rooms` shows the asked room |
| Independent read-back (link) | The Danfoss app | The sensor's page shows its room (the app reads the same map, but through its own session) |
| Independent read-back (effect) | MCP connector `danfoss-ally` | `danfoss_appareil` on each head of the room: `ext_measured_rs`. Does not go through the bridge, the broker or Home Assistant |

The route was captured from the app on 2026-11-28 (app name `thing.m.custom.wkf.device.relation.save` /
`.delete`, keys above). **Through this bridge it is not proven yet**, and neither is the `smartlife.m.*` wire
name the client sends (the SDK's usual rewrite of `thing.m.*`): this trial is its first write.

## Builds needed (not released yet)

- `pydanfoss-cloud` with `sensor_rooms` (branch `claude/sensor-room-assign`), in a release;
- add-on `danfoss2mqtt` with the options `sensor_rooms_writes` / `sensor_rooms_trial_sensor` and a pin on that
  release;
- the integration with the sensor page section and `sensor/set_room` (branch `claude/sensor-room-assign`).

Check what actually runs on the Pi before the trial (a HACS update can replace a hand-deployed build).

## Preconditions

- **One driver of the live install**: no other session restarts Home Assistant or the add-on, changes options
  or deploys while the gate is open.
- **Trial sensor `Sensor S`**: online, in **no** Danfoss room now (`bridge/sensor_rooms` shows `room_id: null`,
  the app agrees). If the chosen sensor is already in its room (the 2026-11-28 capture left one so), start at
  step 5 (take out), then step 3 (put back).
- **Trial room `Room R`**: the Tuya room of the heads `Sensor S` should serve, chosen by Rémi, holding **no
  other sensor**, with at least one head that the MCP connector reads (`danfoss_appareil`). `Sensor S` sits in
  `Room R` physically, away from radiators, windows and doors.
- Time of day: a slot where `Room R` is **not** in comfort heating, so a change of reference does not swing
  the room while it is occupied. Note its heads' setpoints and `pi_heating_demand`.
- The Danfoss app open on `Sensor S`'s page (to observe; check it is not logged out).
- A way back that does not depend on this code: the sensor's room setting in the app.

## Steps

1. **Baseline (read only).**
   - `bridge/sensor_rooms` (Developer tools → MQTT, or the add-on log): `Sensor S` → `room_id: null`, `Room R`
     listed in its `rooms`. Record the whole entry as `E0` (anonymised: no ids here).
   - Panel, `Sensor S`'s page: **Danfoss room** = "In no room", read-only note (the gate is still closed).
   - App: `Sensor S` in no room.
   - MCP `danfoss_appareil` on every head of `Room R`: record `ext_measured_rs` (expected -8000) and the
     measured temperature, as `H0`. Also `danfoss_appareil` on `Sensor S`: its temperature.
   All three must agree on "no room". Stop if not.
2. **Arm** (add-on options, needs the go-ahead "arm"): `sensor_rooms_writes: true`,
   `sensor_rooms_trial_sensor: <Sensor S device id>`. Restart the add-on. Check:
   - the add-on log has one warning "sensor room writes OPEN (trial sensor … only)";
   - `bridge/devices`: `Sensor S` carries `danfoss.set_keys: ["sensor_room"]`, **every other sensor `[]`**;
   - panel: `Sensor S`'s page shows the warning, the room picker without rooms holding another sensor, and
     **Put in this room**; another sensor's page stays read-only.
3. **Write 1 — put `Sensor S` in `Room R`** (go-ahead "write 1"). Pick `Room R`, click **Put in this room**,
   accept the confirmation.
   - Panel: "Awaiting the bridge…", then **Danfoss room** = `Room R` within about 20 s.
   - Add-on log: "sensor … put in room … (confirmed by a read of the device rooms)". Record the delay.
   - App: `Sensor S` shows `Room R`.
   - `bridge/rooms`: the schedule group of `Room R` (if any) names `Sensor S` as its `sensor` on the next
     cycle (the write wakes it at once).
   - **Effect**, MCP `danfoss_appareil` on each head of `Room R`, at +2, +5 and +15 min: `ext_measured_rs`
     leaves -8000 and follows `Sensor S`'s temperature (×100). Record the delay.
   Pass: panel, bridge and app agree on `Room R`, nothing else moved on `bridge/sensor_rooms`, and the heads
   take the sensor. Room moved but heads still -8000 after 15 min: **"applied, no effect"**, not a pass:
   record it, take the sensor out (step 5) only if Rémi asks, and stop the widening there.
   A panel or bridge `Room R` that the app does not show is the "accepted but not applied" failure:
   **stop and restore from the app**.
   "NOT confirmed" in the log: read the app and the MCP **before** anything else; never retry blindly.
4. **Watch** (read only), as long as Rémi wants, at least one heating period: `Room R`'s temperature and its
   heads' valve openings stay sensible (no runaway heating or cooling compared with the days before).
5. **Write 2 — take it out** (go-ahead "write 2"; only to prove the `delete` route, and only if Rémi wants the
   proof now). Click **Take out of this room**, accept.
   - Panel / log / app: "In no room". MCP: the heads' `ext_measured_rs` back to -8000 within about 15 min.
6. **Write 3 — put it back** (go-ahead "write 3"), as step 3. Ends in the state Rémi wants to keep.
7. **Refusals (no cloud write, no go-ahead needed, one at a time).**
   - Panel: the picker never lists a room that holds another sensor; with `Sensor S` in a room, only
     **Take out** is offered.
   - From Developer tools → MQTT, publish on **another** sensor's `/set`:
     `{"sensor_room": {"room_id": "<one of its home's rooms>"}}`. Expected: add-on log "sensor room writes are
     closed", **no** change in the app or on `bridge/sensor_rooms`. Skip it if Rémi prefers not to publish by
     hand.
8. **Disarm** (go-ahead "disarm"): `sensor_rooms_writes: false`, `sensor_rooms_trial_sensor: ""`, restart the
   add-on. Check every sensor advertises `[]` and every sensor page is read-only again.
9. **Final read-back**: app and `bridge/sensor_rooms` show `Sensor S` in the room Rémi chose to keep; every
   other sensor as in `E0`; the heads of `Room R` as expected (`H0` if it was taken out, the sensor's
   temperature if it was kept in).
10. **Record** the result here (versions, delays per step, what each source showed), anonymised: no real
    device ids or room names in this repository.

## Stop and restore at once if

- the app does not show the change within about a minute while the panel or the bridge does;
- any other sensor's room, or any head outside `Room R`, changes;
- the bridge logs "NOT confirmed" or a write failure (record the error; it may be the `smartlife.m.*` wire name);
- `Room R`'s heads behave oddly once on the sensor (setpoint jumps, valves fully open with the room warm);
- the app is logged out, or there is any doubt about restoring.

Restore through the sensor's room setting in the app, back to the state Rémi chose, then disarm.

## After a pass

- Open the gate to every sensor only by a separate decision (`sensor_rooms_trial_sensor: ""`), recorded here.
- Update `CloudClient.async_sensor_room_save` / `_delete`'s docstrings and the contract to say the bridge route
  is proven, in a pull request of its own.
