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
| Radiator covered | `radiator_covered` | RW | `switch` | not exposed; read by the tunnel | tunnel `0x4016` read | Missing |
| External room sensor | `external_measured_room_sensor` | RW | `number` | not exposed, not read | none | Missing, no channel known |
| External window contact | `window_open_external` | RW | `switch` | not exposed, not read | none | Missing, no channel known |
| Load balancing | `load_balancing_enable` | RW | `switch` | not exposed; read by the tunnel as `load_balancing` | tunnel `0x4032` read | Missing. On the Ally gateway this is driven by the room; exposing a write needs care |
| Room load mean / estimate | `load_room_mean` RW, `load_estimate` R | — | `number` / `sensor` | not exposed, not read | none | Missing; gateway-managed, low value |
| Regulation speed | `algorithm_scale_factor`, 1–10 | RW | `number` | not exposed; read by the tunnel as `control_speed` | tunnel `0x4020` read | Missing |
| Setpoint offset | `regulation_setpoint_offset`, −2.5…2.5, 0.1 | RW, config | `number` | not exposed; read by the tunnel as `setpoint_offset` | tunnel `0x404B` read | Missing |
| Valve exercise day / time | `day_of_week`, `trigger_time` | RW, config | `select` / `text` | not exposed; read by the tunnel as `descale_day` / `descale_time` | tunnel `0x4010` / `0x4011` read | Missing |
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
| Temperature | `temperature` | No handling found in the code (device categories are `head` and `relay`) |
| Humidity | `humidity` | Same |
| Battery | `battery`, `voltage` (diagnostic) | Same |
| Link | `linkquality` (diagnostic) | Same |

To check first: whether the cloud device list returns a room sensor paired to an Ally gateway, and
with which DPs.

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
source (`docs/architecture.md`, rules for adding a route). Radiator covered, setpoint offset and
regulation speed would be tunnel writes, unproven, not started.

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

**Not proposed**: any write to `programming_operation_mode` (R4), load balancing and heat
available (managed by the gateway and the relay link), LQI (not available).
