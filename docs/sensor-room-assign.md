# Putting a cloud room sensor in a room from the Companion (design)

**Status:** built in three repositories (`pydanfoss-cloud`, the `danfoss2mqtt` add-on, this integration),
gate closed by default, **not written on real hardware through the bridge yet**. The supervised trial plan is
[`validation/2026-11-28-cloud-bridge-sensor-room.md`](validation/2026-11-28-cloud-bridge-sensor-room.md).

Goal: from the integration's side panel, do what the Danfoss Ally app does when you set a room sensor's room
(`014G2480`, served by the `danfoss2mqtt` cloud bridge). The first target is a sensor that is in **no room**
(cloud `roomId` -1), to be put in the Tuya room of the heads it should serve.

⚠ **This is a write that changes heating.** In Danfoss Ally a sensor in a room is meant to become the reference
measurement of that room's heads: their external room temperature (`ext_measured_rs`) stops being -8000 and
they regulate on the sensor. That is the effect we want, and the reason the write is gated like the other
heating writes ([`first-write-procedure.md`](first-write-procedure.md)).

## 1. The route (captured, 2026-11-28)

Capture of the Danfoss Ally app on the Android emulator (AVD `danfoss34`, Frida in spawn mode, request hook
with the `thing.m.api.batch.invoke` sub-calls expanded, filtered output, raw capture deleted after
extraction). Rémi did the gestures in the app on one live sensor that was in no room: first an assignment
that the capture missed (the emulator rebooted under the hook), then, recorded, **take it out of its room**
and **put it back in the same room**.

| Gesture | Route (app name) | Version | Parameters |
|---|---|---|---|
| Put in a room | `thing.m.custom.wkf.device.relation.save` | 1.0 | `bizId` (sensor device id), `bizType` = 6, `parentId` (Tuya room id, type 4), `parentType` = 4 |
| Take out of its room | `thing.m.custom.wkf.device.relation.delete` | 1.0 | same keys; `parentId` = the room it is in |

- No `gid` among the parameters (the app sets the home on the request context). The same `parentId` was sent
  both times.
- The SDK signs `thing.m.*` routes as `smartlife.m.*` (seen for `device.reset`, and every room write the MCP
  connector uses is a `smartlife.m.*` name). The client therefore sends
  `smartlife.m.custom.wkf.device.relation.save` / `.delete`. **Unproven until the first supervised write**: if
  the cloud refuses that name, the write fails visibly (no read-back change), nothing is retried.
- One device, one room. It is **not** `smartlife.m.custom.wkf.device.relations.selected.save` (the MCP's
  `danfoss_tuya_piece_attacher_preparer`), which replaces a room's whole member list and is proven for heads
  only. The capture shows the app does not use it for a sensor.
- Right after each gesture the app re-reads `m.life.my.group.device.sort.list` v2.1: the device → room map the
  bridge already reads (`CloudClient.async_device_rooms`, validated read-only on 2026-11-28). A sensor's
  `roomId` there is its room in the app; `-1` = in no room.

## 2. Read-back

Two independent sources, as the first-write procedure asks:

1. **The device → room map** (`sort.list` v2.1, one request per home). The bridge reads it before the write
   (fresh state) and after (up to 3 reads, 5 s apart). It is the same source the app reads after its own
   gesture.
2. **The effect on the heads**, through the MCP connector `danfoss-ally` (it does not go through the bridge,
   the broker or Home Assistant): the per-device read of each head of the room (`danfoss_appareil`) shows
   `ext_measured_rs`. Before: -8000 (no external sensor). After: the sensor's temperature in hundredths of °C,
   within a few minutes. This is evidence of the effect, never the link itself. If the room moves but the
   heads never take the sensor, the write is recorded as "applied, no effect", not as a pass.

## 3. Bridge contract (`danfoss2mqtt`, `pydanfoss-cloud` `sensor_rooms`)

### New retained topic `<prefix>/bridge/sensor_rooms`

```json
{"<sensor id>": {"home_id": "<gid>", "room_id": "<Tuya room id>" | null,
                 "rooms": [{"room_id": "<id>", "name": "<room name>"}]}}
```

- `room_id`: the sensor's room in the device → room map (`null` = in no room). Same TTL and same read as the
  `sensor` field of `bridge/rooms` (one `sort.list` per home, at most hourly).
- `rooms`: the Tuya rooms of the sensor's home (`m.life.group.room.map.get`, one request per home that holds
  a sensor, at most hourly). A sensor whose home or rooms were never read is left out; nothing is assumed.
- Built like `bridge/relays` and kept apart from `bridge/rooms`, whose groups are schedule groups (type 5),
  not Tuya rooms (type 4).

### `/set` key on the sensor: `sensor_room`

```json
{"sensor_room": {"room_id": "<id from bridge/sensor_rooms>"}}
{"sensor_room": {"room_id": null}}
```

- The first puts the sensor in that room, the second takes it out of the room it is in. Any other key on a
  sensor's `/set` is logged and ignored.
- **Advertised** in the sensor's descriptor on `bridge/devices` as `danfoss.set_keys: ["sensor_room"]` only
  while the gate is open for that sensor **and** its entry is on `bridge/sensor_rooms`; else `[]`.
- **Gate** (add-on options, off by default): `sensor_rooms_writes` (bool) and `sensor_rooms_trial_sensor`
  (a Danfoss device id; when set, only that sensor is written). Closed, or another sensor: refused and logged,
  no cloud request.
- **Validation** (bridge, pure checks in `sensor_rooms.py`): `room_id` must be a non-empty id or `null`
  (a boolean, `-1`, an empty string or a missing key is refused). The bridge then makes **fresh reads** of the
  sensor's home: its rooms and its device → room map. It refuses a room that is not one of the home's rooms,
  a sensor that already sits in **another** room (take it out first, as the app does: moving is two writes),
  and a room that already holds **another room sensor** (the heads would get two references). A sensor
  already as asked sends nothing.
- **Write**: one `relation.save` (put in) or one `relation.delete` (take out, with the current room), one
  sensor write at a time.
- **Read-back**: the device → room map is re-read up to 3 times, 5 s apart, until the sensor shows the asked
  room. Then `bridge/sensor_rooms` is republished **at once** with what was read, and the poll loop is woken
  so `bridge/rooms`' `sensor` follows. An unconfirmed write is logged "NOT confirmed" and the topics carry the
  state read back, never the asked one. A refusal after the fresh reads also republishes, so a stale entry is
  corrected.

The design keeps the edits in `bridge_daemon.py` small (config, gate, set keys, one `_apply_set` branch, the
loop's publish); the logic and its I/O live in `sensor_rooms.py`.

## 4. Integration (Companion) and panel

- `mqtt_companion.py` subscribes to `bridge/sensor_rooms` (`sensor_cloud_rooms`); a malformed payload keeps
  the previous one.
- The `overview` WebSocket gives each sensor the bridge publishes: `cloud_room` (`{room_id, name}` or `null`),
  `cloud_rooms` (each room with the other sensor already in it, if any) and `room_writable` (the bridge
  advertises `sensor_room` for it).
- New admin-only WebSocket command `danfoss_ally_cloud/sensor/set_room` `{sensor, room_id | null}`. It checks
  the same rules as the bridge against the last `bridge/sensor_rooms` (sensor known, key advertised, room of
  its home, not in another room, no other sensor there) before publishing, so a refused click never reaches
  the broker. Result: `status: "sent"`.
- Side panel, the sensor's page: a **Danfoss room** section with the room the bridge read (or "In no room").
  While the sensor advertises `sensor_room` and the user is an administrator: a warning that the room's heads
  may then regulate on the sensor, and either a room picker (rooms with no other sensor) with **Put in this
  room**, or **Take out of this room**. Each gesture asks for a confirmation naming the sensor and the room.
  After the click the section shows "Awaiting the bridge…" and re-reads the overview every 3 s (2 min at most)
  until `bridge/sensor_rooms` shows the asked room; nothing is optimistic. Otherwise the section is read-only
  with a note on why.
- The section only exists for a sensor the bridge publishes on `bridge/sensor_rooms`; Zigbee2MQTT sensors and
  older bridges are unchanged.

## 5. What can go wrong

| Risk | Guard |
|---|---|
| The cloud refuses `smartlife.m.…relation.save` (signing-name rewrite not as assumed) | The write fails, the read-back shows no change, the bridge logs "NOT confirmed". The trial plan stops there; next step would be a capture of the wire name. |
| The cloud accepts the call but does not apply it (the "accepted, not applied" pattern seen elsewhere) | Never trusted: only the re-read map counts, and the MCP per-device read of the heads is the independent check. |
| The room moves but the heads do not take the sensor (`ext_measured_rs` stays -8000) | Recorded as "applied, no effect"; the gate is not widened on that result. The gateway may need time, or the link may need a schedule group with that room's name: investigate before any other write. |
| The heads take the sensor and regulate worse (sensor placed badly, near a radiator or a door) | Put the sensor in the room the owner chooses, on a sensor the owner can see; the way back is "Take out of this room" or the app. Watch the room's temperature for a day. |
| Two sensors in one room | Refused by the panel and by the bridge (fresh read). |
| A sensor in room A sent to room B in one message | Refused: take it out first. One gesture = one cloud call. |
| A stale `bridge/sensor_rooms` (app change since the last hourly read) | The bridge always re-reads before writing and republishes what it read, even on a refusal. |
| `sort.list` v2.1 lags after a change (as the bulk device list does) | Up to 3 reads over 10 s; then "NOT confirmed" with the state read. The trial plan reads again by MCP a minute later before deciding. |
| Moving a sensor out of a room that the bridge places it in on `bridge/rooms` | `bridge/rooms`' `sensor` follows the next map read (the write wakes the loop at once). |
| The trial sensor or room id typed wrong in the add-on options | Gate confined to one device id; any other sensor is refused and logged. |
| Writes left open after the trial | Off by default; the trial plan ends by closing the gate and checking every sensor advertises `[]`. |

## 6. Not in scope

- Moving a sensor between rooms in one message, or choosing which sensor heads use when a room has two.
- A room with no schedule group (the parallel work on `bridge/rooms` covers how such rooms are shown).
- Zigbee2MQTT sensors (`companion_rooms.py` keeps its own sensor link and `external_measured_room_sensor`).
- The 1.4.x direct-cloud entry (frozen).
