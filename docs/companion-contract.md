# v2.x Architecture & Companion MQTT Contract

> **Baseline policy (2026-11-22):** `1.4.x` is the **frozen 1.x release line** (direct cloud HTTP +
> cloud MQTT + local Zigbee tunnel inside the Home Assistant integration). All architectural work for
> **v2.x** follows the **Bridge + Companion** split defined in this document, modeled on the
> `ebusd` ↔ Mosquitto ↔ `ha-weishaupt` architecture and unified with **Zigbee2MQTT**.

---

## 1. Architectural Vision

In v2.x, Home Assistant no longer speaks Tuya HTTP, Tuya cloud MQTT, or `tinytuya` LAN sockets
directly. Instead, two bridges publish to and listen on the local **Home Assistant Mosquitto MQTT
broker** using the **same Zigbee2MQTT device dialect**, and a single **Danfoss Companion**
integration (`ha-danfoss-ally` v2) connects solely to Mosquitto:

```
  [Heads & sensors on Sonoff PoE]           [Heads, sensors & relays on Danfoss Gateways]
               │                                                   │
               ▼                                                   ▼
        ┌──────────────┐                                   ┌───────────────┐
        │ zigbee2mqtt  │                                   │ danfoss2mqtt  │
        └──────┬───────┘                                   └───────┬───────┘
               │  zigbee2mqtt/bridge/devices                       │  danfoss2mqtt/bridge/devices
               │  zigbee2mqtt/<name> (+ /set)                      │  danfoss2mqtt/<name> (+ /set)
               │                                                   │  danfoss2mqtt/bridge/rooms
               └───────────────────────┐   ┌───────────────────────┘
                                       ▼   ▼
                           ╔═══════════════════════════╗
                           ║   Mosquitto Broker (HA)   ║
                           ╚═════════════╦═════════════╝
                                         ║
                                         ▼
                     ┌───────────────────────────────────────┐
                     │     Danfoss Companion (HA v2.x)       │
                     │  • Subscribes to configured prefixes  │
                     │    (default: zigbee2mqtt, danfoss2mqtt│
                     │  • Unified DanfossDevice model        │
                     │  • Rooms (native Danfoss or virtual)  │
                     │  • Weekly schedules & holidays        │
                     │  • Room sensor 014G2480 -> heads sync │
                     │  • Boiler demand -> relay / Weishaupt │
                     └───────────────────────────────────────┘
```

### Design Invariants Carried Over from v1.x

1. **Zero optimistic state:** `<prefix>/<friendly_name>` state topics are only updated after the
   underlying channel confirms the write (gateway echo, tunnel read-back, or verified HTTP route).
2. **Hardware-proven routing (R1–R7):** `danfoss2mqtt` enforces the exact same routing and safety
   gates (`docs/interface-contract.md`, `docs/mqtt-routing-target.md`) as `1.4.x`.
3. **Seamless migration between bridges:** moving a radiator head (`014G2461`) or room sensor
   (`014G2480`) from a Danfoss Ally gateway (`danfoss2mqtt`) to a Zigbee2MQTT coordinator
   (`zigbee2mqtt`) requires zero UI or automation rework in the Companion.

---

## 2. Per-Device MQTT Contract (Zigbee2MQTT Dialect)

Every bridge prefix `<prefix>` (e.g. `zigbee2mqtt` or `danfoss2mqtt`) exposes:

| Topic | Retain | Direction | Payload |
|---|---|---|---|
| `<prefix>/bridge/state` | yes | Bridge → Companion | `"online"` or `"offline"` (or `{"state": "online"}`) |
| `<prefix>/bridge/devices` | yes | Bridge → Companion | JSON array of device descriptors (§2.1) |
| `<prefix>/<friendly_name>/availability` | yes | Bridge → Companion | `"online"` or `"offline"` (or `{"state": "online"}`) |
| `<prefix>/<friendly_name>` | yes | Bridge → Companion | JSON state object with Z2M property names (§2.2) |
| `<prefix>/<friendly_name>/set` | no | Companion → Bridge | JSON command object with Z2M property names (§2.3) |

### 2.1 Device Descriptor (`<prefix>/bridge/devices`)

The Companion recognises a device entry from `<prefix>/bridge/devices` as a Danfoss device when
`definition.vendor` is `"Danfoss"` (case-insensitive) or `definition.model` / `model_id` is in the
known model table:

| Category | Zigbee2MQTT `model` / `model_id` | Tuya `product_id` (`danfoss2mqtt`) | Normalized `category` |
|---|---|---|---|
| Radiator thermostat | `014G2461` | `03wvrwpv` | `"head"` |
| Room temperature & humidity sensor | `014G2480` | `mxzo5rhf` | `"sensor"` |
| Boiler relay | `014G2400` / `Ally Boiler Relay` | `ypieax1h` | `"relay"` |

When `danfoss2mqtt` publishes `bridge/devices`, it includes a `"danfoss"` metadata block on each
entry (`{"dev_id": dev.id, "product_id": dev.product_id, "mesh_id": dev.mesh_id, "category": dev.category}`)
so the Companion keeps the cloud `devId` when available, while falling back to `ieee_address` for
pure `zigbee2mqtt` devices.

### 2.2 Per-Device State Properties (`<prefix>/<friendly_name>`)

Both bridges use the canonical Zigbee2MQTT property names established in
`docs/zigbee2mqtt-alignment.md`:

#### Radiator Thermostat (`category == "head"`)

| Z2M Property | Type / Values | `DanfossDevice` field |
|---|---|---|
| `local_temperature` | `float` (°C) | `temperature` |
| `occupied_heating_setpoint` | `float` (°C, 5.0–35.0) | `setpoint` |
| `pi_heating_demand` | `float` (0–100 %) | `valve_opening` |
| `running_state` | `"heat"` \| `"idle"` | `heating` (`True` → `"heat"`, `False` → `"idle"`) |
| `system_mode` | `"heat"` | always `"heat"` |
| `battery` | `float` (0–100 %) | `battery` |
| `window_open_internal` / `window_open` | `bool` or Z2M 5-state enum | `window_open` |
| `window_open_feature` | `bool` | `window_detection` |
| `keypad_lockout` | `"lock"` \| `"unlock"` (or `bool`) | `child_lock` |
| `max_heat_setpoint_limit` | `float` (°C) | `max_setpoint` |
| `min_heat_setpoint_limit` | `float` (°C) | `min_setpoint` |
| `heat_required` | `bool` | `heat_request` |
| `mounted_mode_active` | `bool` | `mounting` |
| `programming_operation_mode` | `"setpoint"` \| `"schedule"` \| `"schedule_with_preheat"` \| `"eco"` | `schedule_active` + `preheat` |
| `viewing_direction` | `bool` | `viewing_direction` |
| `thermostat_orientation` | `bool` (`True` = vertical, `False` = horizontal) | `orientation` |

`danfoss2mqtt` also includes an optional `"danfoss"` extension object in the state JSON for
cloud-only fields that have no native Z2M equivalent (`setpoints` dict `{comfort, setback, pause}`,
`mode`, `faults`, `inconsistent`).

#### Room Sensor (`category == "sensor"`, `014G2480`)

| Z2M Property | Type | `DanfossDevice` field |
|---|---|---|
| `temperature` | `float` (°C) | `temperature` |
| `humidity` | `float` (% RH) | `humidity` |
| `battery` | `float` (0–100 %) | `battery` |

#### Boiler Relay (`category == "relay"`)

| Z2M Property | Type | `DanfossDevice` field |
|---|---|---|
| `state` / `relay_on` | `"ON"` \| `"OFF"` (or `bool`) | `relay_on` |

### 2.3 Per-Device Command Topic (`<prefix>/<friendly_name>/set`)

The Companion issues device-level writes by publishing a JSON object to `<prefix>/<friendly_name>/set`:

| High-level Companion Action | `<prefix>/<friendly_name>/set` JSON |
|---|---|
| Target setpoint (`setpoint`) | `{"occupied_heating_setpoint": 21.0}` |
| Upper bound (`max_setpoint`) | `{"max_heat_setpoint_limit": 28.0}` |
| Lower bound (`min_setpoint`) | `{"min_heat_setpoint_limit": 16.0}` |
| Child lock (`child_lock`) | `{"keypad_lockout": "lock"}` or `{"keypad_lockout": "unlock"}` |
| Open-window detection (`window_detection`) | `{"window_open_feature": true}` |
| Preheat (`preheat`, when schedule active) | `{"programming_operation_mode": "schedule_with_preheat"}` or `"schedule"` |
| External room sensor temperature (`external_sensor_temp`) | `{"external_measured_room_sensor": 2050}` (hundredths of °C; `-8000` disables) |
| External window state (`window_open_external`) | `{"window_open_external": true}` |
| Room load mean (`load_room_mean`) | `{"load_room_mean": 35}` |
| Weekly schedule day (`weekly_schedule`) | `{"weekly_schedule": {"dayofweek": 1, "num_of_transitions": 3, "transitions": [...]}}` |

---

## 3. Fleet & Room Extension Topics

While `zigbee2mqtt` manages individual Zigbee devices, a Danfoss heating system is operated by
**Room**. In v2.x, rooms come from two sources that the Companion merges seamlessly:

1. **Native Danfoss rooms** published by `danfoss2mqtt` on:
   - `danfoss2mqtt/bridge/rooms` (`retain`): list of room objects (`group_id`, `name`, `home_id`,
     `members`, `temperature`, `humidity`, `setpoint`, `setpoints`, `mode`, `heating`, `schedule`).
   - `danfoss2mqtt/bridge/holidays`, `danfoss2mqtt/bridge/relays`, `danfoss2mqtt/bridge/alerts` (`retain`).
   - `danfoss2mqtt/bridge/request/<action>` → `danfoss2mqtt/bridge/response/<action>` and
     `danfoss2mqtt/bridge/jobs/<job_id>` for room/schedule/vacation operations.
2. **Companion-managed rooms (for `zigbee2mqtt` heads + `014G2480` sensors)**:
   - Stored in Home Assistant storage (`danfoss_ally_companion_rooms`).
   - For a room grouping $N$ `zigbee2mqtt` heads and an optional `014G2480` sensor, the Companion:
     - aggregates room temperature (from the `014G2480` sensor if linked, else mean of head temperatures);
     - pushes the `014G2480` temperature to each member head's `external_measured_room_sensor` every
       30 minutes (and on ≥ 0.2 °C change);
     - computes and pushes `load_room_mean` from the member heads' `pi_heating_demand`;
     - fans out room setpoint and weekly schedule changes to `<prefix>/<head_name>/set`.

---

## 4. Staged Implementation Plan (v2.0 Roadmap)

Each batch is a self-contained PR with ≥ 95 % test coverage and zero regression on existing suites.

| Batch | Scope | Deliverable | Status |
|---|---|---|---|
| **Batch 2.1 (Foundation)** | Freeze 1.4.x; publish `docs/companion-contract.md`; shared bidirectional Z2M ↔ `DanfossDevice` codec (`api/z2m_contract.py`) | `docs/companion-contract.md`, `api/z2m_contract.py`, `tests/test_v2_contract.py` | **Done (99 % cov)** |
| **Batch 2.2 (`danfoss2mqtt` Bridge)** | Bidirectional MQTT bridge (`bridge_mqtt.py`): publishes heads, `014G2480` sensors, relays, `bridge/rooms`, `bridge/holidays` and handles `<base>/<name>/set` + `<base>/bridge/request/+` | `custom_components/danfoss_ally_cloud/bridge_mqtt.py` | **Done (90 % cov)** |
| **Batch 2.3 (Unified MQTT Companion Discovery)** | `MqttCompanionCoordinator` (`mqtt_companion.py`): subscribes to `("zigbee2mqtt", "danfoss2mqtt")`, decodes `bridge/devices` + `<prefix>/<name>` via `z2m_contract`, exposes unified `dict[str, DanfossDevice]` | `custom_components/danfoss_ally_cloud/mqtt_companion.py` | **Done (99 % cov)** |
| **Batch 2.4 (Companion Room & Sensor Orchestrator)** | `CompanionRoomManager` (`companion_rooms.py`): virtual rooms for `zigbee2mqtt` heads + automatic `014G2480` → `external_measured_room_sensor` & `load_room_mean` loop + weekly schedule fan-out + boiler demand aggregation | `custom_components/danfoss_ally_cloud/companion_rooms.py` | **Done (99 % cov)** |
| **Batch 2.5 (Lovelace & View Adapter)** | `CompanionCoordinatorView` & `build_companion_store` (`companion_adapter.py`): drop-in adapter feeding `ops_views.py` (`rooms_payload`, `overview_payload`) directly from the unified MQTT Companion | `custom_components/danfoss_ally_cloud/companion_adapter.py` | **Done (95 % cov)** |
| **Batch 2.6 (Standalone `danfoss2mqtt` Daemon)** | Pure-Python, zero-HA-dependency `StandaloneDanfoss2MqttDaemon` & CLI entry point `danfoss2mqtt` (`api/bridge_daemon.py` + `pyproject.toml`) | `custom_components/danfoss_ally_cloud/api/bridge_daemon.py`, `tests/test_v2_end_to_end.py` | **Done (100 % cov)** |
