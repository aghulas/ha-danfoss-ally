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
   gates (`docs/interface-contract.md`, `docs/cloud-mqtt-channel.md`) as `1.4.x`.
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

### 2.4 Direct-cloud-only write paths are not part of the Companion (by design)

A Companion entry is **channel-free** (Design Invariant §1): it speaks only to the bridges over
Mosquitto and writes exclusively through the `<prefix>/<name>/set` and `<prefix>/bridge/request/*`
topics. It deliberately does **not** own the direct-cloud / local-tunnel / Tuya-cloud-MQTT
machinery of the frozen `1.4.x` line. In `__init__.py async_setup_entry`, an MQTT-companion entry
`return`s from `_async_setup_companion_entry` **before** the direct-cloud branch that installs the
local-tunnel coordinator (`_async_setup_local_and_keys`), the dedicated cloud-MQTT link
(`_async_setup_mqtt_link`) and the supervised trials (`_supervised_trial` / `_local_trial`). So a
Companion store holds **no `DATA_LOCAL`, no `DATA_MQTT_LINK`, no `DATA_CLOUD_MQTT`, and no
supervised-trial keys**.

Consequently these entities exist on **no** companion head — each platform already self-gates on the
absent store keys, so they are **absent rather than lying**:

| Not exposed on a Companion | Gate (direct-cloud only) | Why it belongs to the direct-cloud entry |
|---|---|---|
| Preheat switch (`DanfossPreheat`, Zigbee `0x0025`) | `switch.py`: `if local is not None` | Proven lever is the local tunnel; the cloud DP 1 route is a closed candidate (`docs/preheat.md`) |
| Local-tunnel setting switches (radiator covered, external window, load balancing, adaptation run) | `switch.py`: `DATA_LOCAL` | Tunnel-only supervised writes |
| Valve-exercise-day select, orientation select (DP 133) | `select.py`: `DATA_LOCAL` / `DATA_MQTT_LINK` | Local-tunnel / cloud-MQTT candidates |
| Viewing-direction switch (DP 101) | `switch.py`: `trial_dp_armed` + `DATA_MQTT_LINK` | Cloud-MQTT candidate |
| Cloud-MQTT head bounds / setpoints numbers, cloud-MQTT child-lock/window writes | `number.py` / `switch.py`: `DATA_CLOUD_MQTT` + `DATA_MQTT_LINK` | Dedicated Tuya cloud-MQTT link |
| Local setpoint-offset / regulation-speed numbers | `number.py`: `DATA_LOCAL` | Tunnel-only |
| `cloud_mqtt_link` connectivity sensor, cloud-MQTT coverage/probe | `binary_sensor.py` / diagnostics: `DATA_MQTT_LINK` | Dedicated cloud-MQTT link |
| MQTT re-publishing (`mqtt_publisher`: discovery / zigbee2mqtt) | not wired in companion setup | The Companion consumes the Z2M dialect; re-publishing is the bridges' job |

The companion-routed writes **are** present (setpoint, max/min bounds, `child_lock`,
`window_detection` via `mqtt_companion`, plus rooms / schedules / holidays via
`bridge/request`). Where a head's preheat is reachable over a bridge at all it is driven by the
`programming_operation_mode` command (§2.3), handled by the bridge that owns the head; the
autonomous `danfoss2mqtt` cloud bridge declines it for an isolated head today
(`docs/z2m-cloud-parity.md`). `danfoss2mqtt` heads also carry no `mesh_id`, which independently
rules out every tunnel/cloud-MQTT path.

**A supervised DP 1 / DP 101 / DP 133 trial, a local-tunnel setting trial, preheat, head-unbind or
the cloud-MQTT link can therefore only be armed from a direct-cloud (`1.4.x`-style) entry** on a
head that entry reaches through its own tunnel / dedicated cloud-MQTT link — never through the
Companion. The config-entry diagnostics carry a `preheat` block (`companion_mode`, `switch_exposed`,
`reason`) so at least the preheat absence is explicit at runtime.

Because none of the direct-cloud options (`enable_local`, `enable_cloud_mqtt`,
`cloud_mqtt_supervised_dps` / `_head`, `local_supervised_settings` / `_head`, `cloud_mqtt_probe`,
`enable_vacation_write`, `enable_head_unbind`, the `mqtt_publisher` settings) do anything on a
Companion entry, the **options flow is mode-aware**: a Companion entry's options show only its
subscribed bridge prefixes (`CONF_MQTT_PREFIXES`), not the inert direct-cloud toggles. Editing them
reloads the entry. This keeps the UI honest — an option that does nothing is not shown.

---

## 3. Fleet & Room Extension Topics

While `zigbee2mqtt` manages individual Zigbee devices, a Danfoss heating system is operated by
**Room**. In v2.x, rooms come from two sources that the Companion merges seamlessly:

1. **Native Danfoss rooms** published by `danfoss2mqtt` on:
   - `danfoss2mqtt/bridge/rooms` (`retain`): list of room objects (`group_id`, `name`, `home_id`,
     `members`, `temperature`, `humidity`, `setpoint`, `setpoints`, `mode`, `heating`, `schedule`).
   - `danfoss2mqtt/bridge/holidays`, `danfoss2mqtt/bridge/relays`, `danfoss2mqtt/bridge/alerts` (`retain`).
     `bridge/relays` is a dict keyed by the boiler relay's device id, each value the rooms eligible
     to drive it: `{"<relay id>": [{"room_id": "<id>", "name": "Room 1", "linked": true}]}`
     (`room_id` is a Tuya *room* id, not a schedule-group id; the relay's own on/off stays on its
     device topic). Read only: the Companion feeds it to `overview` (`linked_rooms`), `get_relays`
     and the relay's linked-rooms sensor. Until a bridge has published a relay, its linkage is
     empty, never assumed; a malformed payload leaves the previous one in place. The bridge
     re-reads the linkage from the cloud at most once an hour (one request per relay).
   - `danfoss2mqtt/bridge/request/<action>` → `danfoss2mqtt/bridge/response/<action>` and
     `danfoss2mqtt/bridge/jobs/<job_id>` for room/schedule/vacation operations.
2. **Companion-managed rooms (for `zigbee2mqtt` heads + `014G2480` sensors)**:
   - Stored in Home Assistant storage (`danfoss_ally_companion_rooms`).
   - For a room grouping $N$ `zigbee2mqtt` heads and an optional `014G2480` sensor, the Companion:
     - aggregates room temperature (from the `014G2480` sensor if linked, else mean of head temperatures);
     - when the option `companion_feed_external_sensor` is on, pushes the `014G2480` temperature
       to each member head's `external_measured_room_sensor` on a ≥ 0.2 °C change or when that
       head's last write is 20 minutes old, at most once every 5 minutes per head;
     - when the option `companion_feed_load_mean` is on (off by default, not validated on real
       hardware), computes and pushes `load_room_mean` from the member heads' `load_estimate`,
       only if every member reports `load_balancing_enable` on;
     - fans out room setpoint and weekly schedule changes to `<prefix>/<head_name>/set`.

---

## 4. Implementation batches (all shipped in 2.0.0)

Each batch is a self-contained PR with ≥ 95 % test coverage and zero regression on existing suites.

| Batch | Scope | Deliverable | Status |
|---|---|---|---|
| **Batch 2.1 (Foundation)** | Freeze 1.4.x; publish `docs/companion-contract.md`; shared bidirectional Z2M ↔ `DanfossDevice` codec (`api/z2m_contract.py`) | `docs/companion-contract.md`, `api/z2m_contract.py`, `tests/test_v2_contract.py` | **Done (99 % cov)** |
| **Batch 2.2 (`danfoss2mqtt` Bridge)** | Initial in-HA bidirectional bridge prototype, superseded by Batch 2.6 standalone daemon (`api/bridge_daemon.py`) and removed | *(superseded by `api/bridge_daemon.py`)* | **Superseded** |
| **Batch 2.3 (Unified MQTT Companion Discovery)** | `MqttCompanionCoordinator` (`mqtt_companion.py`): subscribes to `("zigbee2mqtt", "danfoss2mqtt")`, decodes `bridge/devices` + `<prefix>/<name>` via `z2m_contract`, exposes unified `dict[str, DanfossDevice]` | `custom_components/danfoss_ally_cloud/mqtt_companion.py` | **Done (99 % cov)** |
| **Batch 2.4 (Companion Room & Sensor Orchestrator)** | `CompanionRoomManager` (`companion_rooms.py`): virtual rooms for `zigbee2mqtt` heads + automatic `014G2480` → `external_measured_room_sensor` & `load_room_mean` loop + weekly schedule fan-out + boiler demand aggregation | `custom_components/danfoss_ally_cloud/companion_rooms.py` | **Done (99 % cov)** |
| **Batch 2.5 (Lovelace & View Adapter)** | `CompanionCoordinatorView` & `build_companion_store` (`companion_adapter.py`): drop-in adapter feeding `ops_views.py` (`rooms_payload`, `overview_payload`) directly from the unified MQTT Companion | `custom_components/danfoss_ally_cloud/companion_adapter.py` | **Done (95 % cov)** |
| **Batch 2.6 (Standalone `danfoss2mqtt` Daemon)** | Pure-Python, zero-HA-dependency `StandaloneDanfoss2MqttDaemon` & CLI entry point `danfoss2mqtt` (`api/bridge_daemon.py` + `pyproject.toml`) | `custom_components/danfoss_ally_cloud/api/bridge_daemon.py`, `tests/test_v2_end_to_end.py` | **Done (100 % cov)** |
