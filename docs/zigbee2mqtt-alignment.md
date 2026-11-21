# Zigbee2MQTT alignment — correspondence table

Goal: a head driven by this integration and a head paired directly to Zigbee2MQTT should look the
same in Home Assistant wherever they mean the same thing. This table is the reference for that
work. It changes nothing by itself.

## Sources

- **Zigbee2MQTT side**: `zigbee2mqtt/bridge/devices` read on the production broker on 2026-11-20.
  Two Danfoss models are paired there: `014G2461` (Ally thermostat, firmware `00.34.0008`, 5
  devices) and `014G2480` (temperature and humidity sensor, 1 device). The property names, access
  flags, ranges and categories below are copied from those definitions.
- **Integration side**: the code at `main` (`climate.py`, `sensor.py`, `binary_sensor.py`,
  `switch.py`, `number.py`, `api/decode.py`, `api/local/tunnel.py`) and
  `docs/interface-contract.md`.
- **Not verified**: the Home Assistant entity type Zigbee2MQTT creates for each property. The
  "HA entity (Z2M)" column applies Zigbee2MQTT's usual discovery rules (settable binary → `switch`,
  settable enum → `select`, settable numeric → `number`, read-only → `sensor` / `binary_sensor`);
  it was not checked against the entity registry.

Access: `R` = published and readable, `RW` = also settable.

## 1. Thermostat (`climate`)

| Concept | Z2M property | Z2M | Integration today | Gap |
|---|---|---|---|---|
| Unit of control | one `climate` per head | — | one `climate` per **room**; a head has its own only when isolated | Structural, stays (a grouped head is only written through its room) |
| Measured temperature | `local_temperature` | R | `current_temperature` of the climate, plus a `temperature` sensor per head | None in the climate; ours has an extra per-head sensor |
| Target temperature | `occupied_heating_setpoint` | RW, 5–35, step 0.5 | `temperature`, 5–35 (or the head's bounds), step `SETPOINT_STEP` | Same range. Ours is only writable in comfort / setback mode, and read-only on an isolated head without `enable_cloud_mqtt` |
| Mode | `system_mode` = `heat` only | RW | `hvac_modes` = `heat` only | None |
| Action | `running_state` (`idle` / `heat`) | R | `hvac_action` (`idle` / `heating`), from DP 3 with valve opening as fallback | None |
| Valve opening | `pi_heating_demand`, 0–100 % | R | `valve_opening` sensor (DP 170) | Name only |
| Scheduled setpoint | `occupied_heating_setpoint_scheduled` | RW | no single equivalent: comfort / setback / pause `number` entities and the weekly schedule | Different model, see §5 |

## 2. Settings

| Concept | Z2M property | Z2M | HA entity (Z2M) | Integration today | Channel on our side | Gap |
|---|---|---|---|---|---|---|
| Upper setpoint bound | `max_heat_setpoint_limit` | RW, 5–35, 0.5 | `number` | `number` `upper_bound`, config | DP 18 (room, or cloud MQTT on an isolated head) | Name; ours is `config` category, Z2M's has none |
| Lower setpoint bound | `min_heat_setpoint_limit` | RW, 5–35, 0.5 | `number` | `number` `lower_bound`, config | DP 27 | Same |
| Child lock | `keypad_lockout` (`unlock` / `lock`) | RW, config | `select` | `switch` `child_lock`, config | DP 30 | Entity type (`switch` is the better fit; nothing to change on our side) |
| Open-window detection | `window_open_feature` | RW, config | `switch` | `switch` `window_detection`, config | DP 116 / tunnel `0x4051` | Name only |
| Preheat | `programming_operation_mode` = `schedule_with_preheat` | RW | `select` | `switch` `preheat` | tunnel `0x0025` bit 1 (only proven lever) | Z2M folds preheat into a 4-value mode; ours is a dedicated switch |
| Programming mode | `programming_operation_mode` (`setpoint`, `schedule`, `schedule_with_preheat`, `eco`) | RW | `select` | `sensor` `programming_mode` (enum, diagnostic, read only), same four value names | tunnel `0x0025` | Read only on our side, on purpose: writing `setpoint` here is the manual switch that erases the schedule (R4) |
| Viewing direction | `viewing_direction` | RW, config | `switch` | `switch` `viewing_direction`, config, **trial head only** (batch C) | cloud MQTT DP 101, candidate, confirmed by the per-device route | Closed until its supervised trial passes |
| Orientation (vertical / horizontal) | `thermostat_orientation` | RW, config | `switch` | `select` `orientation_setting` (`horizontal` / `vertical`), config, **trial head only** (batch C); `sensor` `orientation` read only | cloud MQTT DP 133, candidate, confirmed by the tunnel flag `0x4014` | Closed until its supervised trial passes; ours is a `select`, the two values being names, not on/off |
| Radiator covered | `radiator_covered` | RW | `switch` | `binary_sensor` `radiator_covered` read only; `switch` `radiator_covered_setting`, config, **trial head only** (batch C2) | tunnel `0x4016` read; write implemented, not tried | Closed until its supervised trial passes |
| External room sensor | `external_measured_room_sensor` | RW, int16, −8000…3500 (0.01 °C) | `number` | `number` `external_room_sensor_setting` in °C (−80…35; −80 = disabled), config, **trial head only** (batch C3) | tunnel `0x4015` read + write, closed, not tried | Closed until its supervised trial passes; must be refreshed periodically on a real head (§6) |
| External window contact | `window_open_external` | RW, boolean | `switch` | `switch` `window_open_external_setting`, config, **trial head only** (batch C3) | tunnel `0x4003` read + write, closed, not tried | Closed until its supervised trial passes |
| Load balancing | `load_balancing_enable` | RW, boolean | `switch` | `switch` `load_balancing_setting`, config, **trial head only** (batch C3); read by the tunnel as `load_balancing` | tunnel `0x4032` read + write, closed, not tried | Closed until its supervised trial passes. On the Ally gateway this is driven by the room, so it stays closed |
| Room load mean / estimate | `load_room_mean` RW, `load_estimate` R | — | `number` / `sensor` | not exposed, not read | none | Missing; gateway-managed, low value |
| Regulation speed | `algorithm_scale_factor`, 1–10 | RW | `number` | `sensor` `regulation_speed` read only; `number` `regulation_speed_setting` 1–10, config, **trial head only** (batch C2) | tunnel `0x4020` read; write implemented, not tried | Closed until its supervised trial passes |
| Setpoint offset | `regulation_setpoint_offset`, −2.5…2.5, 0.1 | RW, config | `number` | `sensor` `setpoint_offset` read only; `number` `setpoint_offset_setting` −2.5…2.5 by 0.1, config, **trial head only** (batch C2) | tunnel `0x404B` read; write implemented, not tried | Closed until its supervised trial passes; tenths-of-°C scale not confirmed |
| Valve exercise day / time | `day_of_week`, `trigger_time` | RW, config | `select` / `text` | `sensor` `descale_day` / `descale_time` read only; `select` `valve_exercise_day` and `time` `valve_exercise_time`, config, **trial head only** (batch C2) | tunnel `0x4010` / `0x4011` read; write = the `set_descaling` service's frame, not tried through these entities | Closed until its supervised trial passes; ours is a `time`, Z2M's a `text` |
| Adaptation run | `adaptation_run_control`, `adaptation_run_settings` | RW | `select` / `switch` | not exposed; `adaptation_setting` read by the tunnel | tunnel `0x404E` read | Missing |
| Heat available | `heat_available` | RW, config | `switch` | not exposed; read by the tunnel | tunnel `0x4030` read | Missing; gateway-managed (boiler relay link) |
| Heating system mode | `heating_system_mode` | RW, config | `select` | not exposed, not read | none | Missing |
| Mounting mode control | `mounted_mode_control` | RW, config | `switch` | not exposed | none proven | Missing |

## 3. State and diagnostics

| Concept | Z2M property | Z2M | HA entity (Z2M) | Integration today | Gap |
|---|---|---|---|---|---|
| Battery | `battery`, diagnostic | R | `sensor`, diagnostic | `sensor` `battery`, diagnostic | None (batch A) |
| Fault | `system_status_code`, diagnostic | R | `sensor` | `sensor` `fault`, diagnostic (decoded bit list) | Name only |
| Window | `window_open_internal` (`quarantine`, `closed`, `hold`, `open`, `external_open`), diagnostic | R | `sensor` (enum) | `binary_sensor` `window` (DP 25) | Ours is two-state and a primary entity. The five states are readable through the tunnel (`0x4000`) only |
| Heat request | `heat_required`, diagnostic | R | `binary_sensor` | `binary_sensor` `heat_required`, diagnostic (DP 162) | None (batch A) |
| Mounting mode | `mounted_mode_active`, diagnostic | R | `binary_sensor` | `binary_sensor` `mounting_mode`, diagnostic (DP 149) | Name only (batch A) |
| Preheat running | `preheat_status` | R | `binary_sensor` | decoded (`preheat`, DP 172 bit 1), carried by the `preheat` switch | Different meaning to check: Z2M's is "preheating now", ours is "preheat enabled" |
| Preheat time | `preheat_time` | R | `sensor` | not read | Missing |
| Setpoint change source | `setpoint_change_source` (`manual`, `schedule`, `externally`), diagnostic | R | `sensor` (enum) | `sensor` `setpoint_source` (enum, diagnostic), same three value names | None (batch B) |
| Adaptation status | `adaptation_run_status` | R | `sensor` (enum) | tunnel `adaptation_state` → `adaptation_done` | Missing entity |
| Absolute setpoint limits | `abs_min_heat_setpoint_limit`, `abs_max_heat_setpoint_limit`, diagnostic | R | `sensor` | constants `_MIN_TEMP` / `_MAX_TEMP` (5 / 35) | None worth closing |
| Link | `linkquality`, 0–255 lqi, diagnostic | R | `sensor` | `binary_sensor` `online`, diagnostic | No LQI on our side: the gateway does not report it. `online` is the equivalent |

## 4. Temperature and humidity sensor (`014G2480`)

| Concept | Z2M property | Integration today |
|---|---|---|
| Temperature | `temperature` | `sensor` `temperature` (DP 1, tenths of °C), from the cloud device list |
| Humidity | `humidity` | `sensor` `humidity` (DP 2, tenths of %) |
| Battery | `battery`, `voltage` (diagnostic) | `sensor` `battery` (DP 4, %), diagnostic. No `voltage` DP on the cloud side |
| Link | `linkquality` (diagnostic) | No LQI on the cloud side (as for heads) |

**Settled (batch A2).** The cloud device list returns the Danfoss Ally™ Room Sensor (014G2480,
Tuya category `wsdcg`, product `mxzo5rhf`) with DP 1 `temp_current` (tenths of °C), DP 2
`humidity_value` (tenths of %) and DP 4 `battery_percentage` (%). `api/decode.py` now gives it the
`sensor` category and `sensor.py` three read-only sensors (temperature, humidity, battery). Seen on
the real install's device list (2026-11-21); no write.

## 5. What exists on one side only

| Integration only | Closest thing in Z2M |
|---|---|
| Room device, room `climate`, head count, inconsistent-heads sensor | Z2M groups (not used for these heads today) |
| Comfort / setback / pause setpoint `number` entities | `occupied_heating_setpoint_scheduled` (one value) |
| Weekly schedule (services, WebSocket, schedule card) | none exposed; `programming_operation_mode` selects whether the head follows its own schedule |
| `schedule_active` binary sensor (DP 172 bit 0) | `programming_operation_mode` ≠ `setpoint` |
| Holiday binary sensor and setpoint | `day_of_week` = `away_or_vacation` is unrelated; none |
| Boiler relay and "rooms calling for heat" | none |
| Cloud MQTT connectivity sensor | bridge state |

## 6. Proposed batches

**A — no new write, no new channel** (data already decoded from the cloud). Items 1 to 3 are
done (entities `heat_required` and `mounting_mode`); item 4 was settled by keeping our names:

1. `battery` sensor → `EntityCategory.DIAGNOSTIC`.
2. New diagnostic `binary_sensor` "heat required" (DP 162).
3. New diagnostic `binary_sensor` "mounted mode active" (DP 149).
4. Naming glossary: one canonical term per concept in `strings.json` / `translations/`, with the
   Z2M property quoted in the documentation. Decision needed: adopt Z2M's English labels
   ("PI heating demand", "Keypad lockout") or keep ours ("Valve opening", "Child lock") and treat
   the table above as the bridge. Recommendation: keep ours, they read better.

**B — read-only entities fed by the local tunnel** (attributes already decoded in
`api/local/tunnel.py`), in two parts:

- **B1, done, no extra traffic.** The periodic local survey reads the standard attributes in one
  frame for the preheat switch; that frame already carries the programming mode (`0x0025`) and
  the setpoint change source (`0x0030`). Two diagnostic enum sensors expose them, for the heads
  the tunnel can address, refreshed at the survey's pace and right after a preheat write.
  Value names are Zigbee2MQTT's. Raw values `1` and `3` of `0x0025` are established on real
  hardware here; `0` (`setpoint`) and `4` (`eco`), and the three values of `0x0030`, come from
  Zigbee2MQTT and the Zigbee specification and were **not** observed on real hardware through
  this integration. An unlisted raw value reads unknown, with the raw value as an attribute.
- **B2, done, once a day.** The manufacturer attributes cost two more frames per head (one for
  a head that does not answer), on battery heads, where a survey already takes minutes for a
  site. They are read by a separate pass, at most once every 24 hours
  (`LOCAL_SETTINGS_INTERVAL`), right after a preheat survey so the two never overlap. The pass
  also runs once after each start of the integration. A head that misses a pass keeps its last
  value, dated by the `read_at` attribute. Entities, all read only and diagnostic:
  - enabled by default: `sensor` "window state" (`0x4000`, five states), `sensor` "adaptation
    run" (`0x404D`: `none`, `in_progress`, `found`, `lost`), `binary_sensor` "radiator covered"
    (`0x4016`);
  - disabled by default (static settings): `sensor` "orientation" (`0x4014`), "regulation
    speed" (`0x4020`), "setpoint offset" (`0x404B`, tenths of °C), "valve exercise day" and
    "valve exercise time" (`0x4010` / `0x4011`).

  Not observed on real hardware through this integration, taken from Zigbee2MQTT's reading of
  the same attributes: the five window states, the adaptation values other than "found" (bit 1),
  the meaning of the orientation flag (`false` horizontal, `true` vertical) and the tenth-of-°C
  scale of the setpoint offset. Zigbee2MQTT's `lost_in_progress` adaptation value is not mapped
  (its raw value is not known here): it reads unknown, with the raw value as an attribute.

**C — new writes**, one at a time, each with a supervised write read back from an independent
source (`docs/architecture.md`, rules for adding a route).

- **C1, implemented, not tried on real hardware.** Viewing direction (DP 101) and orientation
  (DP 133) over cloud MQTT, as the app's captured frames: closed candidates, selectable for a
  supervised trial like DP 1, with entities on the designated isolated head only (a config
  `switch` and a config `select`). Orientation is confirmed by the tunnel flag `0x4014` and shown
  from it; viewing direction is confirmed by the per-device cloud route (the tunnel does not read
  the user-interface cluster, so the head's display is the trial's proof). The cloud does carry
  both DPs in its device list (`"101": false`, `"133": "Horizontal"` on every head of a capture of
  the app's fleet), so DP 101 has a state to show. Procedure: `docs/viewing-orientation-trial.md`.
- **Open question: does `false` of attribute `0x4014` mean horizontal?** It is Zigbee2MQTT's
  reading, not observed here. Until it is settled the orientation write refuses to send when the
  tunnel's flag and the cloud's DP 133 disagree under that reading, and the trial starts by
  comparing the head, the flag and the cloud (read only). The answer also fixes the read-only
  "orientation" sensor of B2.

- **C2, implemented, not tried on real hardware.** Radiator covered (`0x4016`), setpoint offset
  (`0x404B`), regulation speed (`0x4020`) and valve exercise day / time (`0x4010` / `0x4011`)
  through the local tunnel, as Zigbee2MQTT writes the same manufacturer attributes (types:
  boolean, int8, uint8; enum8 / uint16). Closed by default; options `local_supervised_settings`
  and `local_supervised_head` open them on one head (grouped or isolated), with config entities
  on that head only. Each write is validated, then read back through the tunnel and shown from
  the read-back. Procedure: `docs/tunnel-settings-trial.md`.
- **Open question: the scale of the setpoint offset.** Tenths of °C (raw −25…25) is Zigbee2MQTT's
  reading; the read-only sensor of B2 and the C2 write both assume it. The trial writes the
  smallest step first and needs a source that shows the offset in °C to settle it.
- **C3, implemented, not tried on real hardware.** External measured room sensor (`0x4015`,
  int16, hundredths of °C), external window open (`0x4003`, boolean) and load balancing (`0x4032`,
  boolean) through the local tunnel, as Zigbee2MQTT writes the same Danfoss manufacturer attributes
  (`zigbee-herdsman-converters`, `src/devices/danfoss.ts`: `danfossExternalMeasuredRoomSensor`
  0x4015, `danfossWindowOpenExternal` 0x4003, `danfossLoadBalancingEnable` 0x4032). Closed by
  default; the same options (`local_supervised_settings` / `local_supervised_head`) open them on
  one head, with config entities on that head only, read back through the tunnel after each write.
  Entities: a `number` "External room sensor setting" (°C, −80 to 35; **−80 °C disables it**, raw
  −8000), a `switch` "External window open setting", a `switch` "Load balancing setting".
  Procedure: `docs/tunnel-settings-trial.md`.
  - **External room sensor must be refreshed periodically.** Zigbee2MQTT's own documentation: the
    head resets the value to −8000 (disabled) after 30 min (room-sensor mode, `radiator_covered`
    true) to 3 h (auto-offset mode, `radiator_covered` false) without an update, and the value
    should be sent at most every 5–30 min or every 0.1 °C change. The integration exposes the
    setting only; feeding it live from a Home Assistant sensor is an automation on the user's side
    (a ready-made example is in `docs/tunnel-settings-trial.md`). A HA blueprint is left as future
    work, kept out of scope for a closed-by-default trial.
  - **Load balancing is gateway/room business on an Ally gateway.** It stays closed by default and
    is exposed for completeness; its real effect needs `load_room_mean` updates the gateway owns.

- **A2, done.** Danfoss Ally™ Room Sensor (014G2480, `wsdcg`) decoded from the cloud device list:
  temperature / humidity / battery read-only sensors (§4). No write.

**Not proposed**: any write to `programming_operation_mode` (R4), `load_room_mean` /
`load_estimate` and heat available (managed by the gateway and the relay link), LQI (not
available).
