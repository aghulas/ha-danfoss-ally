# Changelog

## Unreleased — Side panel navigation, relays under their own home

**Fixed**

- Side panel / `overview`: a boiler relay is listed under its own home. Under the v2 Companion the
  relay-to-room linkage is empty, so with several homes every relay fell back to the first one. The
  relay's own home (published per device by `danfoss2mqtt`) now wins; the vote of the linked rooms
  is only the fallback when that home is unknown.
- Room card: while its first read is in flight, the card says "Loading…" instead of "Unknown room",
  "schedule unavailable" and "no thermostat". Visible for a few seconds on the panel's room page.

**Added**

- Side panel: navigation (contract §8.2). Every room tile is a link to a room page (`/room/<id>`
  under the panel URL) with a breadcrumb back to the building; the browser's back button and a
  copied link work. A grouped room's page embeds the room card unchanged (same reads, actions and
  rules); a single-head room's page is read-only. The panel adds no write path of its own.
- Side panel: element pages (contract §8.2). A room page lists its heads; heads, boiler relays and
  gateways each have a page with their known state and the entities of their Home Assistant
  device, grouped (controls and readings, settings, diagnostics). A row opens the entity in Home
  Assistant's own dialog, where a setting is changed under the entity's rules; an unavailable
  entity stays listed as unavailable. A grouped room's page also lists the room's entities.

## 2.0.10 — Direct-cloud onboarding with email, password and country only

**Changed**

- `config_flow.py`: the direct-cloud setup no longer asks for `sign_key` / `device_id` / `ch_key`.
  The integration derives them (`api/_tuya/install.py`: app-wide `sign_key` and `chKey`, plus a
  `deviceId` generated once per entry) and validates them with a real login. The three-field step
  remains as an advanced manual fallback (checkbox on the account step). Existing entries, reauth
  and reconfigure are unchanged. See `docs/install-material.md`.
- `danfoss2mqtt` (`bridge_daemon.py`): `sign_key` / `ch_key` default to the derived values when a
  username and password are configured; explicit values still override.
- `config_flow.py` onboarding UX: country is now a searchable **name** dropdown (a curated ~37-country
  table in `const.py`) instead of a raw calling code, and the datacenter is derived from the country
  automatically (`CONF_REGION` defaults to `auto`, resolved via `COUNTRY_TO_REGION`), with an explicit
  datacenter kept as an advanced override. `reconfigure` uses the same selectors; `strings.json` and
  the `en`/`fr` translations gained helper descriptions.

**Added**

- `pydanfoss-cloud`: `derive_ch_key`, `app_sign_key`, `generate_device_id`, `app_install_material`.

**Docs**

- Corrected the `CLAUDE.md` note: the repository is public, not private.

## 2.0.9 — Fix Zigbee2MQTT `weekly_schedule` `dayofweek` encoding

**Fixed**

- `companion_rooms.py` (`async_set_room_schedule`): encode `weekly_schedule.dayofweek` as a list
  of English day names (`["monday"]`..`["sunday"]`) instead of an integer bitmask (`0x01`..`0x40`)
  which `zigbee-herdsman-converters >= 26` (`tz.thermostat_weekly_schedule`) evaluated to `0`
  (dropping all scheduled days), and omit unused `num_of_transitions`. Matching `pydanfoss-cloud`
  `0.7.2`.

## 2.0.8 — Fix coordinator room switch fallback when `desired` omits settings

**Fixed**

- `switch.py` (`DanfossRoomCoordinatorSwitch.is_on`) & `companion_adapter.py`
  (`CompanionCoordinatorView.room_members`): read member head IDs via
  `coordinator.room_members(group_id)` instead of `RoomState.members` (which does not exist),
  fixing `AttributeError: 'RoomState' object has no attribute 'members'` when coordinator
  `desired` omits `child_lock` or `window_detection`.

## 2.0.7 — Coordinator room entities (`comfort`/`setback`, settings, mode) & holiday services

**Added**

- **Full Home Assistant controls for `danfoss-room-coordinator` rooms**:
  - `number` (`number.py`): `DanfossRoomSetpoint` (`comfort_setpoint`, `setback_setpoint`) exposed
    and routed via `<prefix>/bridge/request/room/set-comfort-setback` (R3).
  - `switch` (`switch.py`): `DanfossRoomCoordinatorSwitch` (`preheat`, `child_lock`,
    `window_detection`) exposed per coordinator room and routed via
    `<prefix>/bridge/request/room/set-settings`.
  - `select` (`select.py`): `DanfossRoomCoordinatorModeSelect` (`schedule` / `manual` / `pause`)
    exposed per coordinator room and routed via `<prefix>/bridge/request/room/set-mode`.
  - **Services** (`services.py`, `services.yaml`): `companion_set_room_comfort_setback`,
    `companion_set_room_settings`, `companion_set_room_mode`, `companion_set_holiday`, and
    `companion_cancel_holiday`.
- **`companion_rooms.py` & `ops_views.py`**: populate `setpoints`, `mode`, min/max bounds, and
  `writable: true` from coordinator `bridge/rooms` payloads (`desired` + `schedule`).

**Documentation**

- Recorded Stage 3 live sensor feed (`13.80 °C -> 1380`), Stage 4 `set-comfort-setback` /
  `set-mode`, Stage 5 `set-settings`, and Stage 7 `holiday/set` + end-edge recovery results in
  `docs/validation/2026-11-25-coordinator-stages3-7.md`.

## 2.0.6 — Coordinator RPC timeout fix, Z2M schedule cleanup & live trial records

**Fixed**

- **Companion bridge RPC timeout** (`mqtt_companion.py`): raised `BRIDGE_REQUEST_TIMEOUT` from
  `15.0 s` to `60.0 s` so sequential coordinator write fan-outs across sleeping multi-head Z2M
  rooms (`setpoint_timeout_s = 30.0` + retries) complete cleanly without spurious HA `500` errors.
- **Zigbee2MQTT `weekly_schedule` converter warning** (`companion_rooms.py`): omitted the
  deprecated `"mode": 1` field on Z2M virtual-room schedule payloads (`zhc:tz` calculates it
  automatically).

**Documentation**

- **Coordinator real-hardware trials** (`docs/validation/2026-11-23-setpoint-fanout-stage2.md`,
  `docs/validation/2026-11-25-coordinator-stages3-7.md`, `docs/z2m-cloud-parity.md`): recorded
  the live 4-head Zigbee2MQTT trial results for Stages 2, 3, 4, 5, and 6 and confirmed that
  Zigbee2MQTT `2.14.3-1` exposes no `schedule_<day>` read-back properties.

## 2.0.5 — Companion support for `danfoss-room-coordinator` & heat demand sensor

**Added**

- **Standalone `danfoss-room-coordinator` routing in v2 Companion** (#166):
  - `MqttCompanionCoordinator` subscribes to `<prefix>/bridge/heat_demand` and
    `<prefix>/bridge/response/#` (supporting two-segment RPC topics such as
    `bridge/response/room/set-setpoint`), exposes `is_coordinator_room()` and
    `heat_demand_by_prefix`, and preserves `"closed"` error codes on `CompanionBridgeError`.
  - `DanfossBridgeHeatDemandSensor` (`sensor.py`): dynamically created when
    `<prefix>/bridge/heat_demand` is published; exposes `max_valve` (%) and
    `calling` / `rooms_calling` / `ts` / `valid_for_s`, becoming unavailable when the bridge is
    offline or the validity window expires.
- **Documentation & real-hardware records** (#163, #164, #165):
  - Trial A1 overnight preheat hold & gateway upstream DP 1 sync recorded
    (`docs/validation/2026-11-preheat-trial-a1.md`).
  - 24h passive cloud-MQTT probe telemetry results & Stage 4 promotion recorded
    (`docs/cloud-mqtt-channel.md`).
  - Zigbee2MQTT coordinator Stages 3–7 arming flags and supervised trial plans documented
    (`docs/z2m-cloud-parity.md`, `docs/validation/2026-11-25-coordinator-stages3-7.md`).

**Changed**

- **Coordinator room setpoint & schedule routing** (`companion_rooms.py`, `operations.py`, #166):
  - `CompanionRoomManager.async_set_room_setpoint()` routes coordinator-owned rooms through
    `<prefix>/bridge/request/room/set-setpoint` (`source: "user"`), preserving coordinator sensor
    temperatures on native rooms in `build_rooms()`.
  - `operations.{get,set,restore}_schedule` route coordinator-owned rooms through
    `<prefix>/bridge/request/{get,set,restore}_schedule`.
  - `CompanionRoomManager.async_sync_telemetry()` skips heads owned by any bridge-published room
    (single owner per head, `docs/z2m-cloud-parity.md` §5.1).
- **Bridge availability & error surfacing on `DanfossRoomClimate`** (`climate.py`, #166): room
  climate entities become unavailable when their owning bridge is offline, and bridge refusals
  (such as `"closed"` on an unarmed room) surface as `HomeAssistantError`.

## 2.0.4 — Companion write-safety, `danfoss2mqtt` schedule RPC & virtual-room feeds

**Added**

- **`danfoss2mqtt` schedule RPC (`bridge/request/{get,set,restore}_schedule`)** (#161): on a v2
  MQTT Companion entry, `get_schedule`, `set_schedule`, and `restore_schedule` for native
  `danfoss2mqtt` rooms now route through `<prefix>/bridge/request/<action>` ↔
  `<prefix>/bridge/response/<action>` with `transaction` correlation (`mqtt_companion.py`,
  `operations.py`, `api/bridge_daemon.py`), giving real cloud read-back and confirmed HTTP writes
  instead of dropping `/set weekly_schedule`. *(Note: carry the `api/bridge_daemon.py` RPC
  handlers to `aghulas/pydanfoss-cloud` and bump `aghulas/danfoss2mqtt` for live add-on support.)*
- **`CoordinatorProtocol`** (#159): common structural protocol for `DanfossCoordinator` and
  `CompanionCoordinatorView` (omitting `.client`) so `mypy` catches unguarded cloud-client access.

**Changed**

- **The Companion's two periodic feeds to Zigbee2MQTT heads are now options, closed by default**
  (`config_flow.py`, `__init__.py`, `companion_rooms.py`, #152): a Companion entry has an options
  form with `companion_feed_external_sensor` (room sensor temperature →
  `external_measured_room_sensor`) and `companion_feed_load_mean` (`load_room_mean`). A change
  applies at the next tick, without a reload. Closing a feed sends nothing.
  - **Upgrade, room sensor**: an entry that already stores a virtual room with a sensor keeps its
    feed. The option is stored on at the first start, with a warning in the log. Every other
    entry gets it stored off, so a room created later starts closed.
  - **Upgrade, load mean**: off for everyone. An install with a virtual room of two heads or more
    was writing `load_room_mean` and stops; its heads keep the last value received. Tick the
    option to resume.
- **`load_room_mean` is only written when every member of the room reports
  `load_balancing_enable` on** (`api/z2m_contract.py`, `api/decode.py`: new
  `DanfossDevice.load_balancing_enable`, decoded from the Zigbee2MQTT state). A member that is
  unknown or has not reported the attribute counts as off.
- **`async_set_room_schedule` refuses a day of more than six transitions** instead of silently
  dropping the extra ones (rule R1), and validates the whole request before storing or sending
  anything.
- **Companion options & documentation** (#153, #160): Companion entries hide inert direct-cloud
  options; preheat absence on Companion heads is explicit; unused `bridge_mqtt.py` removed;
  `README.md` and `CLAUDE.md` updated for the v2 Bridge + Companion architecture.

**Fixed**

- **Schedule, vacation, and room-management services under Companion** (#158, #159):
  `set_schedule` / `get_schedule` / `restore_schedule` no longer crash with `AttributeError` (HTTP
  500) on `CompanionCoordinatorView`; vacation ops and `ops_rooms` (`create_room`, `rename_room`,
  `delete_room`, `attach_heads`, `detach_heads`, `set_relay_room`, `disconnect_head`) refuse
  cleanly with contract `OperationError` codes.
- **No silently dropped `/set` writes on `danfoss2mqtt`** (#159): `MqttCompanionCoordinator`
  tracks cloud-bridge capabilities (`is_cloud_bridge_device` / `supports_device_set`); switches
  (`child_lock`, `window_detection`), setpoint bounds (`min_setpoint`, `max_setpoint`), and
  isolated-head climates are marked unavailable / read-only on `danfoss2mqtt` while remaining
  writable on `zigbee2mqtt` in mixed fleets.
- **Rooms and holidays indexed per bridge prefix** (#156): a second bridge publishing
  `bridge/rooms` or `bridge/holidays` no longer overwrites another bridge's entries.
- **Room-sensor keep-alive past the head's deadline** (`companion_rooms.py`, `const.py`, #152): the
  refresh threshold was 30 min evaluated on a 15-min timer, so a keep-alive could land at 45 min,
  after the head's own 35-min reset in room-sensor mode (per Zigbee2MQTT's documentation). The
  threshold is now 20 min on a 6-min timer (lands at 24 to 26 min), tracked per head, and a head
  is never written twice within 5 min, service-triggered syncs included. On the 6-min timer the
  load mean's 15-min refresh lands at 15 to 18 min.

## 2.0.3 — Bridge connectivity diagnostic sensors (`danfoss2mqtt` & `zigbee2mqtt`)

**Added**

- **Bridge connectivity binary sensors** (`binary_sensor.py`): the v2.x Companion now exposes one
  diagnostic `connectivity` binary sensor per configured MQTT bridge prefix (e.g.
  `binary_sensor.danfoss2mqtt_bridge`, `binary_sensor.zigbee2mqtt_bridge`), tracking
  `<prefix>/bridge/state` (`online`/`offline`) and reporting the number of discovered devices.

## 2.0.2 — Fix virtual-room load balancing (`load_estimate` instead of valve opening)

**Fixed**

- **Multi-head virtual room load balancing** (`companion_rooms.py`, `api/z2m_contract.py`,
  `api/decode.py`): `async_sync_telemetry` now computes `load_room_mean` from each head's raw
  `load_estimate` (Zigbee attribute `0x404A`, excluding `-8000` invalid values, requiring at least
  2 valid heads, pushing on delta ≥ 25 or every 15 min) instead of `pi_heating_demand` (0–100 %).
  Sending a 0–100 percentage as `load_room_mean` caused Danfoss Ally TRVs to see themselves far
  above the room mean and close their valves.

## 2.0.0 — Bridge + Companion architecture (Zigbee2MQTT + danfoss2mqtt over Mosquitto)

Major release. Home Assistant no longer speaks Tuya HTTP, Tuya cloud MQTT or `tinytuya` LAN
sockets directly. Two bridges publish to the local Mosquitto broker in the **Zigbee2MQTT device
dialect** — `zigbee2mqtt` for heads on a local coordinator, and **`danfoss2mqtt`** (a standalone
add-on backed by the `pydanfoss-cloud` library) for heads on the Danfoss gateways — and a single
**Danfoss Ally Companion** integration reads both. Modelled on the `ebusd` ↔ Mosquitto ↔
`ha-weishaupt` split; see `docs/companion-contract.md`.

Validated on real hardware (2026-11-22): the Companion reads both bridges with fresh state; a
room-level setpoint round-trips over each channel (zigbee2mqtt local fan-out and danfoss2mqtt cloud
path 1a); the cloud path refuses an isolated head and declines fields it cannot prove, with no
optimistic state.

**Added**

- **Unified Companion** (`mqtt_companion.py`, `companion_rooms.py`, `companion_adapter.py`): one
  integration subscribing to the `zigbee2mqtt` and `danfoss2mqtt` prefixes, a unified
  `DanfossDevice` model, native and virtual rooms, the room card and side panel fed from the
  bridges.
- **`danfoss2mqtt` bridge** (Z2M dialect contract `api/z2m_contract.py`; standalone daemon in
  `pydanfoss-cloud`): publishes `bridge/devices`, `bridge/rooms`, `bridge/holidays` and per-device
  state; `/set` is routed only through proven cloud paths and declines the rest loudly.
- **Duplicate-provider Repairs warning** (`repairs.sync_provider_conflict`): fires when the
  Companion runs alongside a v1.x direct-cloud `danfoss_ally_cloud` entry, and clears once the old
  entry is gone. Cutover procedure: `docs/v2-cutover.md`.

**Migration**

- The 1.4.x direct-cloud line is frozen. After upgrading, make the Companion the sole provider of
  each head by following `docs/v2-cutover.md` (disable the v1.x cloud entry and the local-bridge
  MQTT discovery). The Repairs warning guides this; it is an operational step on the live install.

## 1.4.0 — Zigbee2MQTT convergence: room sensor, tunnel-write settings, heat-available and the app message center

**Not validated on real hardware.** Every new tunnel write in this release (external measured room
sensor, external window open, load balancing, and automatic-adaptation on/off) is closed by default
and opens only for a supervised trial, like the batch C2 settings
(`docs/first-write-procedure.md`). The new read-only entities and the message-center sensor only
read.

**Added**

- **App message center** (read only): the Danfoss Ally app's messages (low battery, device
  added/removed, firmware update, new login) are read from `smartlife.m.msg.list` v2.0 on a
  dedicated 30-minute poll. Device alerts only (logins and home messages are left out): one
  account sensor (`last_device_alert`: time of the latest alert, recent alerts as attributes, no
  identifier) and an HA event `danfoss_ally_cloud_message` per new alert, with the head's HA
  `device_id`. New alerts are detected from a high-water mark persisted in `.storage`, never from
  the cloud's read flag. Diagnostics carry
  counts and codes only. Route found in the app's dex and read on the real account (format in
  `docs/message-center.md`); never marks a message read or deletes one.
- **Danfoss Ally™ Room Sensor** (014G2480, Tuya category `wsdcg`, product `mxzo5rhf`): the cloud
  device list is now decoded into a device of its own with three read-only sensors — temperature
  (DP 1, tenths of °C), humidity (DP 2, tenths of %) and battery (DP 4, %). Observed on the real
  install's device list; no write. Closes §4 of `docs/zigbee2mqtt-alignment.md`.
- Three head settings written through the **local tunnel** as Zigbee2MQTT writes the same Danfoss
  manufacturer attributes (`src/devices/danfoss.ts`), each **closed by default** and opened only on
  the one designated trial head (`local_supervised_settings` / `local_supervised_head`), read back
  through the tunnel after every write:
  - **External measured room sensor** (`external_measured_room_sensor`, attribute `0x4015`, int16,
    hundredths of °C): a config `number` in °C (−80 to 35; **−80 °C disables it**, raw −8000). The
    head resets it to disabled after 30 min to 3 h without an update, so a live feed must be
    refreshed periodically — the integration exposes the setting only, with a ready-made Home
    Assistant **blueprint** to feed it from any temperature sensor on a timer
    (`blueprints/automation/danfoss_ally_cloud/external_room_sensor_feed.yaml`; import and configure
    it, see `docs/first-write-procedure.md`).
  - **External window open** (`window_open_external`, attribute `0x4003`, boolean): a config
    `switch`.
  - **Load balancing** (`load_balancing_enable`, attribute `0x4032`, boolean): a config `switch`.
    On an Ally gateway this is driven by the room, so it stays closed by default; exposed for
    completeness only. The attribute was already read as `load_balancing`.

Closes the remaining §2 / §6 gaps of `docs/zigbee2mqtt-alignment.md` (external room sensor,
external window contact, load balancing, and the room sensor).

- Read-only diagnostic `binary_sensor` **"heat available"** (Danfoss attribute `0x4030`), the same
  notion as Zigbee2MQTT's `heat_available`, fed by the local tunnel's daily settings pass (B3).
- A **supervised local-tunnel write** for the **automatic adaptation run** on/off
  (`adaptation_run_settings`, attribute `0x404E`): a config `switch`, **closed by default** and
  opened only on the one designated trial head like the batch C2 settings, read back through the
  tunnel. This is the enable/disable of the nightly adaptation run, **not** the one-shot
  `adaptation_run_control` command.
- The app's **message center** is read into Home Assistant (Tuya `smartlife.m.msg.list`, read
  only): an account-level `sensor` whose state is the timestamp of the latest **device alert**
  (recent messages as attributes, without ids, each head named by its Home Assistant device) and a
  **`danfoss_ally_cloud_message` event** fired once per new device alert (payload carries the
  `device_id` and the message type). Login and system messages are filtered out; new-message
  detection uses a high-water mark saved in Home Assistant storage; a dedicated, conservative
  30-minute poll. `docs/message-center.md` documents the interface, and
  `docs/cloud-mqtt-channel.md` maps the Tuya cloud MQTT channel from a real listen-only capture.

## 1.3.1 — Room sensor in the room card by area

Patch release: frontend only (room card by area), no change to the integration's entities,
services or writes.

**Added**

- Room card by area: the area's **room temperature** (and humidity) under the title, read from the
  area's `sensor` entities of device class `temperature` / `humidity` that are not on a climate's
  device (one sensor: its value; several: their average, with their number and range).
- Room card by area: a head that regulates on an **external room sensor**
  (`external_measured_room_sensor`, Zigbee2MQTT, hundredths of °C, −8000 = none) shows that
  temperature as its reading, a "regulates on an external room sensor" badge, and its own reading
  labelled as such underneath. Ally rooms of this integration are unchanged; no new write, no new
  WebSocket command.

**Validation on real hardware** (`1.3.1-rc1`, 2026-11-21): on a real install, the card on a Home
Assistant area holding four Danfoss heads paired to Zigbee2MQTT and a Danfoss room sensor showed
the room temperature and humidity under the title, and each head's external-sensor regulation with
its own reading underneath, matching the entities. The Lovelace resource was updated in place to
`?v=1.3.1-<hash>` (one entry). Read only: no control of the card was used.

**Also observed on the same install (1.3.0 features, 2026-11-20/21)**: the setpoint offset trial
setting raises the head's regulation target (direction confirmed, scale not proven); a valve
exercise day written through the local tunnel alone held overnight on one head.

## 1.3.0 — Isolated-head thermostat, runtime topology, embedded schedule editor, safer schedule writes

Minor release. It also carries what was prepared as 1.2.1, which was never released (a
`1.2.1-rc1` pre-release exists). Every write path added here is off by default or goes through an
existing, guarded service: an updated install behaves as 1.2.0 until an option is turned on,
except for the refusals listed under "Changed", which are deliberate.

**Validation on real hardware**

- Replayed on a real install (2026-11-20, `1.2.1-rc1`): the gateway homes of the building
  overview.
- Tried once on a real head (2026-11-20): the reworked preheat write of the cloud-MQTT candidate
  (publish, then settings block), OFF to ON, confirmed through the local tunnel. The return to OFF
  and the hold over a night are not established; DP 1 stays a closed candidate.
- Validated on a real install with `1.3.0-rc2` (2026-11-20): the isolated-head thermostat write
  over cloud MQTT (setpoint changed and restored, read back through the local tunnel, the cloud,
  Home Assistant and the app); the runtime creation and retirement of a room's entities (test room
  created then deleted, no reload, heads unchanged); the schedule-write guards (`set_schedule` and
  `restore_schedule` refused where they should be).
- Validated on a real install with `1.3.0-rc3` (2026-11-20, one isolated test head, every write
  restored):
  - the Zigbee2MQTT-aligned diagnostic entities, consistent with the app and with the official
    API;
  - the four head settings written through the local tunnel (radiator covered, setpoint offset,
    regulation speed, valve exercise day and time), each confirmed by a tunnel read-back;
  - the mounting orientation (DP 133) written over cloud MQTT both ways, confirmed by the tunnel
    and followed by the cloud: Zigbee2MQTT's reading of flag `0x4014` (false = horizontal) holds;
  - the room card by area and the panel's other areas, read only (thermostats of another
    integration stay read-only).
- **Not established on real hardware**:
  - the viewing direction (DP 101), refused on `1.3.0-rc3` for want of a confirmation read, which
    is the per-device route fixed below;
  - the post-command refresh overlay, fixed below and not yet observed;
  - the scale and effect of the setpoint offset: the head stores the raw value written, but no
    independent source shows it in °C;
  - whether the cloud keeps a setting written through the tunnel alone (it did not for preheat);
  - the bundle URL with its hash;
  - the embedded schedule editor and the editor fixes, the device actions, the polling backoff,
    the reconfigure step and the Repairs issues (unit tests only).

**Known issue, not fixed in this release.** A preheat change written by the preheat switch (local
tunnel only) does not survive the night: on 2026-11-19/20, heads whose preheat differed from the
cloud's value were back to the cloud's value by about 05:00, with no write from the integration
(docs/preheat.md). The switch is unchanged here.

### Added

- **Room card by Home Assistant area, for any climate.** `danfoss-ally-room-card` also accepts
  `area_id` (`room_id` is unchanged). It lists every `climate` entity of the area whatever its
  integration (for example Danfoss heads paired directly to Zigbee2MQTT): current and target
  temperature, `hvac_action`, availability, and, from the other entities of the same device when
  present, battery, valve opening (`pi_heating_demand`), window (`window_open_internal` /
  `window_open_external`), heat demand (`heat_required`) and link quality. A Danfoss Ally room
  whose room thermostat sits in the area keeps everything the card does for it (schedule strip,
  comfort / setback, back to schedule, write jobs). The only new write is
  `climate.set_temperature` on a climate of another integration, **off by default**: it needs
  `allow_foreign_writes: true` in the card (a checkbox in the editor), and is then offered to
  administrators, within the climate's `min_temp` / `max_temp` and at its `target_temp_step`. A
  Danfoss Ally head seen through another integration (`danfoss_ally`, the official Danfoss cloud
  API) is never written by the card, even then: it is the same head this integration drives. No
  new WebSocket command, no new cloud or tunnel write. The card editor picks a room or an area.
  The Ally section appears only when this integration's room thermostat is in the area: devices
  of this integration have to be given an area first.
- **Panel: other areas.** Below the integration's rooms, the side panel summarises the areas
  holding climate entities of other integrations (temperature, setpoint, heating, offline, low
  battery, window), read only, behind an "Other areas" toggle (**off by default**, remembered by
  the browser): where another integration also drives the Ally heads, the section would show
  them all a second time.

- **Thermostat of an isolated head: setpoint write over Tuya cloud MQTT.** With
  `enable_cloud_mqtt` on and the link connected, the climate of an isolated head writes the
  setpoint of its current mode (comfort: DP 118 + 16, setback: DP 119, then the settings block),
  the path proven for the setpoint numbers. The value is checked against the head's own bounds
  before anything is sent; other modes are refused. Off by default: the climate stays read-only.
  The mode is the one the cloud reports; outside a comfort slot a comfort write causes a few
  minutes of heat demand, as for the comfort number. The entity says what a change would do:
  attributes `write_path` (`cloud_mqtt` / `none`) and `write_setting` (`comfort` / `setback`).
- **Rooms and isolated heads follow the topology at runtime.** Climates and setpoint numbers are
  created when a room appears or a head becomes isolated, without reloading the integration. A
  room's entities are removed only on positive evidence that the room is gone: a complete device
  list, a complete topology read, and a topology that no longer lists it. A partial device list
  (one home not answering) or a degraded topology read never removes anything; the entities stay
  unavailable until the next complete read.
- **Room card: the schedule editor opens inside the card** (embedded mode of the schedule card),
  without a second card frame.
- **Device actions** in the automation editor: "set target temperature" on a room or an isolated
  head (through `climate.set_temperature`, which keeps its own checks) and "restore weekly
  schedule" on a room. The climate is referenced by its entity registry id, so an automation
  survives a rename.
- **`icons.json`**: icons of the entities, some by state (online, window, holiday, boiler relay,
  child lock, window detection, valve opening, fault), and of the services. It is the single
  source: the icons hard-coded in the entities are gone, so a few fixed icons change.
- **Building overview**: each gateway of `get_overview` says what it carries (`head_count`,
  `relay_count`).

- **Reconfigure step**: the region, country code, password or installation secrets of an entry
  can be changed from its page without deleting it (fields left empty keep their value). The
  account cannot be changed there, and the new values are checked by a real sign-in before the
  entry is updated and reloaded.
- **Repairs issues**: a warning for an offline gateway and for a head reporting a hardware fault,
  removed automatically when the device recovers or the entry is unloaded. No secret in them.
- **Two read-only diagnostic binary sensors per head**, from data the cloud already returned:
  "Heat required" (DP 162) and "Mounting mode" (DP 149). Unknown when the cloud does not carry
  the DP. They match Zigbee2MQTT's `heat_required` and `mounted_mode_active`
  (`docs/zigbee2mqtt-alignment.md`).
- **Two read-only diagnostic sensors per head read through the local tunnel** (only with the
  local tunnel on, for the heads it can address): "Programming mode" (manual setpoint, schedule,
  schedule with preheat, eco) and "Setpoint change source" (manual, schedule, external). They
  come from the frame the local survey already sends for the preheat switch: no extra traffic to
  the heads. They show what the head itself says, where the cloud's mode is only a label. Not
  yet seen on a real install; the `setpoint` and `eco` values and the three sources follow
  Zigbee2MQTT's reading of the same attributes.
- **Head settings read once a day through the local tunnel**, read only: window state (five
  states), adaptation run, radiator covered; and, disabled by default, orientation, regulation
  speed, setpoint offset, valve exercise day and time. These cost two more frames per head, so
  they are read by a separate pass at most once every 24 hours (and once after each start),
  after a preheat survey; on a large site that pass delays the next preheat survey once a day.
  Each value carries the time it was read. Not yet seen on a real install.

- **Supervised trial of two new head settings over Tuya cloud MQTT, closed by default**:
  viewing direction (DP 101) and orientation (DP 133, mounting vertical / horizontal), written as
  the Danfoss app does for an isolated head. They can be ticked in `cloud_mqtt_supervised_dps`
  like preheat; only then, on the designated isolated head, a config `switch` "Viewing direction"
  and a config `select` "Mounting orientation" appear (removed again when the trial is disarmed).
  The values are checked before sending (a boolean; exactly `"Vertical"` or `"Horizontal"`), the
  gateway's echo is never taken as confirmation: orientation is read back through the local
  tunnel (attribute `0x4014`, also the select's state), viewing direction through the per-device
  cloud route. Each attempt is reported in `trial_result`. **Not validated on real hardware**;
  procedure in `docs/first-write-procedure.md`.
- **Supervised trial of four head settings through the local tunnel, closed by default**: radiator
  covered (`0x4016`), setpoint offset (`0x404B`, −2.5 to 2.5 °C in tenths: Zigbee2MQTT's scale,
  not confirmed here), regulation speed (`0x4020`, 1 to 10) and valve exercise day / time
  (`0x4010` / `0x4011`, the `set_descaling` service's write), written as Zigbee attributes as
  Zigbee2MQTT does. New options `local_supervised_settings` and `local_supervised_head`: only for
  the ticked settings, on that one head, with `enable_local` on, config entities appear (a
  `switch`, two `number`, a `select` and a new `time` platform); they are removed when the trial
  is disarmed. Values are checked before sending; after each write the head is read back through
  the tunnel and the entity shows what it says, with a clear error on a rejection, a disagreeing
  read-back or no read-back (the entity then stays unavailable until the head is read again).
  **Not validated on real hardware**; procedure in `docs/first-write-procedure.md`.

### Changed

- The head's battery sensor is now in the diagnostic category, as in Zigbee2MQTT. Its entity id
  and unique id do not change; it moves to the "Diagnostic" block of the device page and no
  longer appears in automatically generated dashboards.

- **Schedule writes on an isolated head are guarded.** `set_schedule` and `copy_schedule` refuse
  an isolated head unless it is online and following a schedule (cloud mode `at_home` /
  `leaving_home`, schedule reported active, and, when the local tunnel answers, the schedule bit
  of attribute 0x0025): on an isolated head the cloud holds in manual, the write was accepted and
  left the head in manual at the cloud's comfort value, asking for heat (real install,
  2026-11-19). `copy_schedule` checks every target before writing the first. New error
  `head_not_following_schedule`. Rooms are unaffected.
- **`restore_schedule` refuses an isolated head** (`isolated_restore_unproven`): it did not bring
  the head back, and its closing step goes through a route that is accepted and never applied
  for such a head. Use the Danfoss app. Rooms are unaffected.
- **WebSocket commands on an install with several accounts**: without `entry_id`, a command is
  routed to the account that owns the targeted room, device or home; a command that **writes**
  is refused (`ambiguous_entry`) when no single account owns its target, instead of being applied
  to the first account. Read commands still fall back to the first account.
- **Building overview: a gateway's home is voted by everything it carries.** Since 1.2.0 a gateway
  is listed under the home of its heads; relays and sensors now vote too, so a gateway that
  carries only a boiler relay follows that relay's home instead of a fallback.
- **Preheat (DP 1) cloud-MQTT candidate: the trial write now also posts the settings block.**
  Still closed by default and confirmed by the local tunnel only. The supervised write of
  2026-11-20 showed that the bare `{"1": bool}` publish changes the cloud's DP 1 and not the
  head, and a listen showed that the app's own toggle is followed by a reprogramming of the head
  through the Zigbee tunnel. The candidate write therefore publishes DP 1 and then posts the whole
  settings block through `settings.change`, as the app does for the settings of that block; the
  tunnel confirmation window goes from 60 to 120 s. Nothing changes for an install that has not
  armed the trial (docs/preheat.md).
- **Polling backs off on repeated cloud errors**: the interval doubles on consecutive transient
  failures, up to 15 minutes, and returns to the configured value at the first success. A refused
  sign-in still triggers re-authentication at once.
- Start-up: the session opened by the first refresh is reused for the cloud-MQTT link, and the
  gateway keys are fetched once for the local tunnel and the cloud-MQTT link.
- Cloud-MQTT link: pending write confirmations are guarded across threads and resolved (as not
  confirmed) when the link stops.
- `operations.py` is split into `ops_common`, `ops_views`, `ops_rooms` and `ops_local`
  (re-exported from `operations`; no behaviour change).

- **Password and installation secrets are typed in masked fields** in the user, re-authentication
  and reconfigure steps, instead of plain text fields shown on screen.
- Manifest: `pycryptodome` is a version range instead of an exact pin, to coexist with other
  integrations; `tinytuya` stays on an exact version on purpose (the local tunnel rides it for a
  reverse-engineered protocol). `loggers` is declared.

### Fixed

- **The cards' bundle was cached across pre-releases.** Its URL only carried the manifest
  version (`?v=1.3.0`), the same for every `1.3.0-rcN`, so after an update the browser kept the
  previous cards and panel until a forced reload (seen on 1.3.0-rc3). The URL now also carries the
  first 8 characters of the bundle's SHA-256 (`?v=1.3.0-<hash>`); an existing Lovelace resource
  is updated in place on the next start.
- **Per-device cloud read returned nothing for every head.** `smartlife.m.device.get` v4.0 carries
  the DPs under `dataPointInfo.dps`, not at the top level, so the read always came back empty. Two
  consequences, both fixed: the post-command refresh (`post_command_refresh`) never overlaid
  fresh values (what looked like freshness was the settle-delay refresh of the bulk list), and the
  viewing-direction trial (DP 101) was refused on a real head for want of a confirmation source.
  Found during the 1.3.0-rc3 validation.
- Schedule editor: dragging a bar always moves that bar's own range (the wrong range could move
  after a keyboard time edit, next to a reversed range, or with two ranges of the same start).
- Schedule editor: an interrupted drag (`pointercancel`) restores the range instead of keeping
  the half-done move; a second finger no longer ends the drag.
- Schedule editor: the draft is frozen while saving, so the schedule shown after a save is
  exactly what was sent; late server-validation answers are ignored.
- Schedule and room cards: changing the card's room no longer leaves the previous room's schedule
  and write job on screen; late responses for the previous room are dropped. Write-job tracking
  resumes after Home Assistant detaches and re-attaches the card.
- Room card: the embedded schedule editor can always be closed, even when the schedule cannot be
  read, and cancelling it no longer replaces the card's own, fresher schedule read.

### Documentation

- `docs/isolated-head-schedule-writes.md`: what the schedule services send to an isolated head,
  what happened on 2026-11-19, and the trials still to run.
- `docs/preheat.md`: a tunnel-only preheat write does not survive the night.
- `docs/architecture.md`, `docs/interface-contract.md`: isolated-head thermostat write and its
  behaviour outside a comfort slot, runtime topology sync and `DanfossCoordinator.room_retired`,
  account resolution of the WebSocket commands, schedule-write guards.

## 1.2.0 — Cloud-MQTT channel for isolated heads (gated), non-blocking local start, stale cleanup, reauth

Minor release. It gathers the sections previously listed as unreleased: the gated cloud-MQTT write
path for isolated heads, the non-blocking start of the local tunnel and the Home Assistant 2026
deprecations, plus two fixes (window-detection switch after the first local read,
re-authentication step, single-head rooms in the building panel). Every new option is **off by default**: an updated install behaves as
1.1.0 until an option is turned on.

Adds the write path the Danfoss app uses for **isolated** heads (those not grouped into a room),
which `tuya.m.custom.wkf.settings.change` does not reach (W-3): a DP publish over Tuya cloud MQTT.
Reverse-engineered from the app and **validated on real hardware (2026-11-19)** — see
docs/cloud-mqtt-channel.md. **Off by default**; existing installs are unchanged.

### Added

- **`enable_cloud_mqtt` option (OFF by default).** When on, the integration opens one Tuya cloud
  MQTT connection from its **own** session (its distinct deviceId, so it coexists with the Danfoss
  app and the MCP connector — confirmed on hardware: an independent session is accepted, `rc=0`,
  while the phone app stays connected). It subscribes to `smart/mb/in/<gw>` and can publish a head
  DP on `smart/mb/out/<gw>` (protocol-2.3 AES-GCM frame with the gateway localKey).
- **Isolated-head child lock (DP 30) over MQTT.** With the option on and the link connected, an
  isolated head's child-lock switch routes through MQTT (previously unavailable); otherwise the
  local tunnel; otherwise unavailable — never an optimistic state. The write is **confirmed** by the
  gateway's inbound protocol-4 `{cid,dps}` echo (or a cloud re-read), with a 15 s timeout and a
  clear error if unconfirmed. **Validated 2026-11-19: DP 30 on an isolated test head, confirmed in the
  cloud, the app and physically on the head.** Other settings follow one per supervised validation
  (next entry).
- **Window detection, setpoint bounds and pause setpoint of an isolated head over MQTT (DP 116, 18,
  27, 120).** Each validated by its own supervised write on real hardware (2026-11-19, one isolated
  test head, written once and restored): DP 116, 18 and 27 read back through the local tunnel and
  in the app; DP 120 in the app and the cloud only (no tunnel read exists for it). With the option
  on, every isolated head gets "upper setpoint bound", "lower setpoint bound" and "pause setpoint"
  numbers, and its window-detection switch falls back to cloud MQTT when the local tunnel is not
  available (the tunnel stays the first route). Raising the lower bound above the pause setpoint
  sends DP 120 in the same frame. Values are checked before sending (schema range and step,
  ordering of the bounds, no bound that excludes the comfort or setback setpoint).
- **"Cloud MQTT link" connectivity binary sensor** (diagnostic, present only when the link exists),
  so the link never fails silently; reconnect uses exponential backoff and picks up a refreshed
  `sid`.

- **`cloud_mqtt_probe` option (OFF by default): listen-only measure of the cloud-MQTT push.** Counts
  the DP reports the broker pushes, per head and per DP (number, first and last instant, median and
  longest interval, heads never seen), and serves the aggregates in the diagnostics with no device
  identifier and no DP value. Without `enable_cloud_mqtt` the link has no send path and closes
  itself after 48 h. Tooling for roadmap stage 3; the 24 h run on a real install is still to do
  (docs/cloud-mqtt-channel.md).

- **Candidate DPs and the supervised-trial options.** A DP ships first as a candidate
  (`MQTT_CANDIDATE_DPS`) that only the option `cloud_mqtt_supervised_dps` (empty by default) opens,
  for its supervised first write; its entity then shows `write_trial: true`.
- **Comfort and setback setpoints of an isolated head over MQTT (DP 118 + 16, DP 119).** With the
  option on, every isolated head gets "comfort setpoint" and "setback setpoint" numbers. Written
  as the app does: MQTT publish, then the whole settings block over HTTP. Values are checked
  against the head's own bounds before sending. Each validated by its own supervised write on
  real hardware (2026-11-19 and 2026-11-20, one isolated head following its weekly schedule,
  written once and restored), read back through the local tunnel and in the app. The head carries
  the new value into its own schedule transitions about a minute after the write: no schedule
  rewrite is needed, unlike a room. The comfort write also sets the head's current setpoint at
  once (DP 16); the head returns to its schedule within five minutes, so outside a comfort period
  it heats towards the comfort value for a few minutes. Not observed on a head in manual, pause
  or holiday mode: the comfort write is refused there, with a clear error.
- The cloud-MQTT write confirmation falls back to one read of the head through the per-device
  route when the gateway's echo does not come (it used the bulk list, which lags for minutes).
- **Preheat (DP 1) as a closed cloud-MQTT candidate.** Nothing changes by default: preheat is
  still written and read through the local tunnel (attribute 0x0025). DP 1 can be listed in
  `cloud_mqtt_supervised_dps` for a supervised trial on the designated isolated head; the write
  then goes out over cloud MQTT and is confirmed **only** by the tunnel's read of the head (never
  by the gateway's echo or the cloud, which answered from the gateway cache over HTTP). While
  armed, the tunnel does not write that head's preheat, and the preheat switch shows
  `write_path` / `write_trial`. **Tried on real hardware (2026-11-20), not passed**: the app's
  own toggle reaches the head, the integration's publish only changed the cloud's DP 1, and the
  write was reported "not confirmed" as designed. DP 1 stays closed; the tunnel remains the only
  preheat route (docs/preheat.md).

### Changed (cloud-MQTT link hardening)

- Reconnection backoff widened to 5 s – 5 min (was 2 s – 60 s).
- A link the broker refuses as not authorised asks for one cloud refresh (which renews an
  invalidated session), then **stops for good after five refusals in a row** instead of retrying
  forever with refused credentials. Reload the integration to try again.
- Closing sends `DISCONNECT` before joining the client thread, and no longer refreshes credentials
  while closing.
- The link's state (`connecting`, `connected`, `refused`, `stopped`) is an attribute of the "Cloud
  MQTT link" sensor; the diagnostics gain a `cloud_mqtt_link` block (state and counters, no
  credential, no identifier).
- No secret or identifier in the `repr` of the link objects, and the "unknown gateway" error no
  longer names the gateway. Connection log lines moved from warning to info.
- `enable_cloud_mqtt` now has a label in the options form (en/fr). README: the channel is
  unofficial and optional, with its risks for the account.

### Changed

- Shared library **`pydanfoss-cloud` 0.3.0** (packaging only, no behaviour change for the
  integration): the `api/` layer as of this release — `gw_id` on `async_write_setting`, distinct
  `deviceId`, the holiday / room / relay / unbind calls, and the cloud-MQTT modules `mqtt_publish`
  (codec) and `mqtt_client` (live link). `paho-mqtt` sits behind the new **`[mqtt]` extra**
  (`>=1.6.1,<3`, the same range as `manifest.json`); the codec alone needs no extra. CI now builds
  the wheel and imports the MQTT modules from it. To be published to PyPI for the MCP connector.

### Fixed

- **`get_local_survey` failed on every call** with "'method' object is not iterable" (service
  and WebSocket command): the heads were passed to the tunnel manager as the coordinator's
  method instead of its result. Present since the service was added (0.4.0); found on real
  hardware with 1.2.0-rc3 (2026-11-19). The test double now has the real coordinator's shape.
- **Building panel: single-head rooms were missing.** A room of the app with one head has no
  schedule-group, so the fleet overview (contract §3.6) only listed the grouped rooms and every total
  ignored the other heads (a 99-head fleet showed 66, and a fault or low battery on a lone head was
  invisible). Each such head is now a room of its own, `kind: "single_head"`, in its exact home
  (per-home device list), with the same health fields; totals cover the whole fleet. Its name is the
  app room's when one of its home has the same name (the cloud exposes no room membership), else
  the head's own name, flagged (`name_source`). Rooms also carry `online`, `temperature` and
  `setpoint`, shown on the tiles. Read only: one extra room-map read per home on the hourly topology
  cadence; no write path is added (a single head keeps the isolated-head writes).
- **`get_local_survey` silently left heads out.** The survey waited a flat 60 s per gateway,
  whatever its head count, and the heads not read by then were absent from the response: on a real
  install (2026-11-19) it returned 91 heads for a 99-head fleet, with nothing saying eight were
  missing. The time limit now grows with the busiest gateway (60 s + 60 s per head), and the
  response accounts for every head: `heads_total`, `attempted` (addressable through the tunnel,
  all present in `heads`), `reachable`, `not_read` (not reached before the limit, flagged
  `not_read` instead of being dropped) and `not_addressable` (heads with no Zigbee node id or
  whose gateway key is missing, with the reason). A survey that runs out of time also stops its
  gateway threads after the head they are on, instead of leaving them reading in the background.
  Documented in docs/interface-contract.md §4.4. Not replayed on real hardware yet.
- **Building panel: every gateway was listed under the first home.** On an account with several
  homes the overview (contract §3.6) put all the gateways under the first home and none under the
  others. A gateway is now listed under the home of the heads it carries (majority, a tie going
  to the earlier home); one that carries no head of a known home falls back to its own home in the
  per-home device lists, then to the first home as before. `totals.gateways` is unchanged. No
  frontend change: the panel already reads `gateways` per home.
- **An offline boiler relay showed `off` instead of unavailable.** The relay binary sensor stayed
  available while the relay was offline and served the last DP 1 the cloud kept (seen on a real
  install, 2026-11-19, while the relay's MQTT availability said offline). It is now unavailable
  while the relay is offline, like the head entities. The "rooms calling for heat" sensor is
  unchanged on purpose: it counts the rooms linked to the relay, an account configuration that is
  still true while the relay is offline.

- **Re-authentication step in the config flow.** When the account refuses the sign-in at
  runtime (password changed, installation secrets no longer valid), the coordinator raised
  `ConfigEntryAuthFailed` but the flow had no `reauth` step: the entry had to be deleted and
  recreated. Home Assistant now offers *Re-authenticate*: the same account (another login is
  refused), the new password, and the sign key / device id / channel key only if they changed
  (left empty, kept). The values are checked by a real sign-in before the entry is updated and
  reloaded; nothing typed there is logged.
- **The window-detection switch of an isolated head follows the local survey.** Its write path
  (`local`) depends on the head answering the local tunnel, but the switch only listened to the
  cloud coordinator: after the non-blocking start it stayed unavailable after its head had been
  read locally, until the next cloud poll (up to the scan interval). It now also listens to the
  local coordinator and comes up as soon as its head is read. Routing is unchanged; the state is
  only rewritten when the switch's availability or write path changes (a survey publishes every
  head one by one), and the listener goes with the entity on unload.
- **Stale devices and entities are removed at start-up** instead of lingering as restored orphans
  that had to be deleted by hand (real-hardware finding, 2026-11-19): the device of a head, relay
  or sensor gone from the account, with its entities; the preheat switches when `enable_local` is
  off; the "Cloud MQTT link" sensor when the cloud-MQTT option is off. Room and home devices are
  never removed automatically; a device that is no longer provided can be deleted from its device
  page. A device is removed only on a device list that is **complete and identical, home by
  home, to the previous start's** (never on a first start, a home that did not answer, or a list
  that got shorter: the removal then happens one restart later, if the picture holds), and **at
  most 3 devices per start, or 5 % of the entry's devices**; above that nothing is
  removed and a warning says so.
- `CloudClient.device_list_complete` / `device_list_homes` (library, additive): whether the last
  `async_list_devices` had an answer from every home. The list itself is unchanged and still
  tolerant; for a later `pydanfoss-cloud` 0.3.1.

### Added (MQTT publishing to your own broker)

- **Boiler relays are published in `discovery` mode**: one read-only binary sensor (on/off) per
  relay, with its availability. Real-hardware finding (2026-11-19): relays and room sensors had no
  topic at all. Relays were a gap (the integration has the entity); **room sensors stay out of
  scope on purpose**, since the integration does not decode that category yet. The scope is now
  written down in the README. `zigbee2mqtt` mode is unchanged (heads only).

### Changed (supervised trial)

- **A supervised cloud-MQTT trial is confined to one designated head** (new option
  `cloud_mqtt_supervised_head`, none by default). Ticking a candidate DP used to open it on every
  isolated head: for window detection (DP 116) that moved all of them from the local tunnel to the
  channel under trial for the duration of the trial. Now the DP opens on the designated head only;
  with no head designated nothing is open. The option holds a device id: it is redacted in the
  diagnostics and never logged.

### Library

- **`pydanfoss-cloud` 0.3.1 prepared (not published).** Additive only: the candidate-DP gate of
  the cloud-MQTT write path (`MQTT_CANDIDATE_DPS`, `mqtt_dp_open`, `supervised` argument of
  `mqtt_write_value`) and the completeness indicators of the device list
  (`CloudClient.device_list_complete` / `device_list_homes`).

### Notes

- Experimental / unofficial path; it rides the app's Tuya auth. Enable only deliberately. The first
  write per setting/model is done supervised (docs/first-write-procedure.md).
- No secret or real device identifier in logs or diagnostics (the MQTT client id is kept out of the
  log thread names; diagnostics redact ids).

### Fixed (local tunnel: non-blocking start)

- **The entry no longer waits for the first local survey (`enable_local`).** Setup awaited the
  first preheat survey, which reads the heads one by one through the gateways; every start or reload
  of the integration was held for up to 40 s per gateway, and the heads not read by then were
  written into the result afterwards without the entities being told. The first survey now runs as
  a background task tied to the entry (cancelled on unload and on Home Assistant stop).
- **Preheat switches come up head by head.** Until a head has been read locally its preheat switch
  is unavailable (never a default on/off); it becomes available as soon as *that* head is read,
  without waiting for the rest of the site and without a restart. The same holds for each periodic
  survey: a head that stops answering goes unavailable when it is read, not at the end.
- **A survey is bounded and never doubled.** Only one survey runs at a time (a survey longer than
  the scan interval no longer overlaps the next one), it is stopped after 40 s + 30 s per head of
  the busiest gateway, and an unload/reload/stop aborts it after the head being read (a tunnel
  request cannot be interrupted, 24 s at most) instead of leaving threads on the gateways.
- **A preheat write made during a survey is not overwritten** by the value the survey had read
  before the write: the head's own read-back wins until the next survey.

Not validated on real hardware yet (unit tests on synthetic data only): load time before/after and
the switches coming up progressively are to be measured on a real site.

### Changed (Home Assistant 2026 deprecations)

No functional change. Removes the deprecation warnings HA 2026.x logs for this integration, ahead of
the removals in 2027.8 and 2027.11, while staying compatible with older HA versions.

- **Climate temperature API (HA 2026.11, removal 2027.11).** Room and head climates now implement
  `native_temperature_unit` / `native_current_temperature` / `native_target_temperature`. On an HA
  without the native API, the legacy names are served from them. Checked against a real HA 2026.11.2:
  no deprecation warning at load (the previous code logged one per class), values unchanged.
- **Head → room device link (HA 2026, removal 2027.8).** `DeviceInfo.via_device` is gone. A grouped
  head is now linked to its room device on the device registry (`via_device_id`), once the devices
  exist and on each update, so attaching / detaching a head follows. Only links to our own room
  devices are ever cleared. Registry lookups use `async_get_device_by_identifier` when available
  (HA 2026 deprecates `async_get_device(identifiers=...)`).

## 1.1.0 — Real-hardware validation fixes (R-1, R-3, W-3), relays per building, gated unbind

Minor release built from the real-hardware validation of 2026-11-18/19 on a large real install (about
99 heads, two homes): the integration was checked for coherence against the official Danfoss app and
the MQTT it publishes. It fixes the active setpoint and heating state (R-1), adds an opt-in
post-command refresh so writes show up in good time (R-3), attaches each boiler relay to its own
building, and routes head settings only through proven write paths (W-3). Head unbind ships
**gated** (off by default, not yet validated through HA). One climate attribute is deprecated (see
below).

### Fixed

- **Active setpoint and heating state (R-1, #65).** On a schedule slot other than comfort, the
  integration published the **comfort** setpoint (e.g. 21 °C instead of 14 °C in setback) as the
  climate target and in the MQTT `setpoint`, and an `hvac_action` of `heating` while the head was
  not heating. The cloud payload already carried the right values: the active setpoint is now read
  from **DP 171 `OccupiedSetpoint`** (falling back to the current mode's setpoint, then DP 16), and
  the heating state from **DP 3 `work_state`** (`Heat` / `NoHeat`, falling back to the valve
  opening). Used by the room aggregation, the head climate `hvac_action` and the zigbee2mqtt
  `running_state`. Validated on real hardware after deployment (MQTT `setpoint` = active setpoint,
  `hvac_action` = `idle` on non-heating heads).
- **Boiler relays shown under the wrong building (#68).** On a multi-home account every relay was
  listed under the first home: the relay → room link carries Tuya *room* ids, which the home lookup
  (schedule *groups*) never matched. A relay now goes to the home holding the majority of its linked
  rooms, matched by normalised name. An **offline** relay now shows *Offline* instead of a stale
  *On* and no longer counts in *Relays on*; the per-relay count is relabelled *N linked rooms* (it
  was shown as "calling for heat"). Validated on real hardware.
- **Holiday sensor `on` for a *planned* holiday.** `vacation.detail` also returns a holiday that has
  not started yet (`isRunning: false`, measured on real hardware with a holiday two weeks ahead), and
  the *Holiday active* sensor treated any record as active. It now follows `isRunning` (unknown if
  the record lacks it) and gains a `scheduled` attribute; `get_holiday` / the `holiday` WebSocket
  command return `scheduled` too. The *holiday setpoint* sensor shows the temperature of the holiday
  on record, in progress or planned.
- **Post-command refresh (R-3) missing on some writes.** The room comfort/setback `number` entities
  (same write as the room climate) and the local-tunnel services `set_override`, `clear_override`
  and `set_window_detection` now mark the written heads for the per-device read: the head reports a
  tunnel write to the cloud in under a minute, but HA and MQTT took ~2.5–3 min to follow.
- **Preheat switch lagging ~13 min after a write.** After a write of attribute 0x0025 (validated on
  real hardware) the state only followed at the next full local survey. The head is now read back
  through the tunnel right after the write (only that head), never assumed: an unanswered read makes
  the switch unavailable until the next survey. A rejected or failed write now raises an error.

### Added

- **Post-command refresh (R-3, #66) — opt-in, off by default.** The bulk device list lags for
  several minutes after a command, so a write's result stayed invisible in HA and MQTT. With the new
  option **Post-command refresh** (`post_command_refresh`), heads just commanded are read through a
  per-device route (`smartlife.m.device.get`) for 300 s, at most 12 reads per poll, then return to
  the bulk poll. Validated on real hardware: a setpoint write shows up in HA and MQTT in about
  2 minutes, the weekly schedule left intact. That per-device read starts after a **15 s settle
  delay**, followed by one scheduled refresh: read right after the write, it returned the
  pre-command state and left the written switch one write behind until the next poll (found on
  1.1.0-rc1, fixed for rc2). Never optimistic.
- **New `active_setpoint` state attribute** on room and head climates: the setpoint in force.
- **Head unbind ("disconnect") — GATED, pending real-hardware validation through HA.** New service
  `danfoss_ally_cloud.disconnect_head` (and `CloudClient.async_device_reset`) unbinds a single head
  from the Zigbee network — the app's "disconnect". Cloud call `thing.m.device.reset` v3.0, sent
  under its signed/wire name `smartlife.m.device.reset`, body `{devId, resetFactory}` (captured on
  real hardware 2026-11-18, see `~/dev/danfoss-ally-signing-re/NOTES.md`, "GATE A/D"; already
  shipped guarded in the MCP connector, PR #5). `wipe_data` (= `resetFactory`): **false**
  ("disconnect") keeps the head's identity — re-added on its own gateway without a wipe, it returns
  with the **same devId** and name (rediscovery); **true** ("disconnect and wipe data") is a factory
  reset — the head returns with a **new devId**, identity and name **lost**, **irreversible**. In
  both cases the head leaves the network and disappears from the account, and its room membership is
  lost and must be reassigned.
  - **Triple-gated** (most destructive write in the integration): admin-only, behind the new option
    **Enable head unbind** (`enable_head_unbind`, default **off** → the service raises
    `unbind_disabled`), and requires an explicit `confirm: true` (`confirmation_required`). The
    target must be a known head of a verified product (`WRITE_VERIFIED_PRODUCTS`), else
    `unverified_product`; a gateway/relay target is refused (`unknown_head`). **No one-click path.**
  - **Pairing (add) is OUT OF SCOPE** and not exposed: opening the gateway's permit-join is an MQTT
    order (not an HTTP `m.*` call) and needs a physical action on the head, on site. See
    `docs/roadmap.md`.
  - **No real unbind has been performed through this integration.** Validating a real disconnect via
    HA needs the integrator present, a real head, and the Danfoss app signed out of path 1a (shared
    `deviceId` session, unless `distinct_device_id` is on).

### Changed

- **Head settings only through proven write paths (W-3, #69).** Validation showed that
  `tuya.m.custom.wkf.settings.change` is accepted but **not applied** for a head outside a room. The
  child-lock and window-detection switches no longer use it:
  - **head in a room** → written on the **room** (`s.m.dev.group.dp.publish`, proven). ⚠ This
    applies the setting to **every head of the room**; the switch exposes it through its
    `write_path`, `write_scope` and `room_head_count` attributes;
  - **isolated head, window detection** → **local tunnel** when `enable_local` is on and the head
    answered the last local survey (validated, W-4);
  - **isolated head otherwise, and always for the child lock** → the switch is **unavailable**
    rather than pretending to write. Attach the head to a room to make it writable.
  The Danfoss app writes isolated-head settings over Tuya cloud MQTT; that path is not implemented
  in 1.1.0 (see `docs/interface-contract.md` §4.2). Validated on real hardware with 1.1.0-rc1: the
  child lock written through a room applied to both of its heads within about 15 s; on an isolated
  head the child lock is unavailable.
- **Isolated-head climate now shows its active setpoint.** `DanfossHeadClimate` (heads outside a
  Danfoss room) already computed the active setpoint (DP 171 `OccupiedSetpoint`, the value the
  Danfoss app shows) but declared no features, so Home Assistant never published it as the
  climate's `temperature`. It now declares `TARGET_TEMPERATURE` so the target is visible, and a
  setpoint change is **refused** with a clear error (still no proven path-1a write for a head
  outside a room — the entity stays read-only, it does not pretend to write).
- **`disconnect_head` now unbinds any sub-device, not just heads** (mirrors the MCP connector
  PR #7). The target may be a head, sensor, relay or other sub-device; a **gateway is refused**
  (`gateway_target`) — unbinding it would drop all its heads at once. Unbind is a Tuya-generic call
  keyed on the device category, so there is **no verified-product gate** for it (that head-only
  check still guards the local-tunnel writes). The service **name `disconnect_head` is kept** for
  backward compatibility (it shipped head-only) and now documents the wider scope. The double-gate
  is unchanged: opt-in `enable_head_unbind` (OFF), admin (`allow_internal=False`), explicit
  `confirm`. Response now carries the device `category`. Error codes: target-not-found is now
  `unknown_target` (was `unknown_head`); a gateway target raises the new `gateway_target`.
  `category_of` treats any `wg*` Tuya category as a gateway (defensive). Real-hardware validation
  through HA remains **GATED** and not performed.

### Deprecated

- **`setpoints.setpoint` climate attribute.** It carried DP 16 (`temp_set`), which reports the
  **comfort** setpoint whatever the schedule slot — not the active setpoint, despite its name. The
  value is now published as `setpoints.temp_set`; `setpoints.setpoint` stays as a deprecated alias
  (same value) and will be removed in a future release. **Automations** reading
  `state_attr(..., 'setpoints').setpoint` should switch to `active_setpoint` (the setpoint in force)
  or `setpoints.comfort` / `setpoints.temp_set` (the comfort setpoint), depending on intent.
  Internally, `DanfossDevice.setpoints` uses the key `temp_set` (no longer `setpoint`).

### Validation status

Validated on real hardware (2026-11-18/19, release candidates rc1 to rc3 on a real install):
R-1, R-2 (open-window detection), R-3 and its settle delay, setpoint writes (comfort, setback,
override and back to schedule, weekly schedule intact), head settings routed by room / local tunnel
(W-3), window detection through the local tunnel, MQTT availability following `online`, preheat read
on the morning curves, relays per building, vacation `plan.leave` + `cancel` (through HA, option
turned back off after).

Not validated on real hardware, covered by unit tests: the rc3 fixes (#74: holiday `isRunning`,
R-3 on the room `number` and tunnel services, preheat read-back), beyond a smoke check of rc3 on the
install. Still **gated**: head unbind (`enable_head_unbind`, not validated through HA) and vacation
writes (`enable_vacation_write`; `plan.athome` and `leave.now` not validated). The preheat **write**
trial (an existing feature since 0.4.0) is read after the release.


## 1.0.1 — Frontend card bundle version fix

Patch release. The 1.0.0 artifact shipped the Lovelace card bundle still stamped `0.6.1` — the
versioned bundle was not rebuilt on the 1.0.0 version bump (the "bundle up to date" check is
path-filtered and did not run on a manifest-only commit). This only affected the card's internal
reload heuristic. The bundle is rebuilt so `CARD_VERSION` matches the release. No functional or
API change. HACS/Marketplace validation now runs with no ignored checks (brands served from the
local `brand/` folder).


## 1.0.0 — Coexistence, hardening and vacation writes (axis A)

Path-1a coexistence with the Danfoss app / MCP connector, plus 1.0 hardening, plus the new **gated**
vacation write. Validated in situ on the running install (2026-11-18): coexistence (the integration and the MCP connector keep independent Tuya sessions) and the four vacation writes (away / at-home / cancel / end-now), at-home requiring a Saturday program.

### Added

- **Vacation (holiday) writes — GATED, pending real-hardware validation.** Four services and
  WebSocket commands (contract §4.5/§5.2/§5.3): `set_vacation` (away, fixed temperature,
  `vacation.plan.leave`), `set_vacation_at_home` (follows the Saturday schedule,
  `vacation.plan.athome`), `cancel_vacation` (`vacation.cancel`) and `end_vacation`
  (`vacation.leave.now`). A vacation is set per home (gid), scoped to a room list (default: every
  room of the home). Routes captured 2026-11-18. **Doubly gated**: admin-only **and** behind the
  option **Use vacation writes** (`enable_vacation_write`, default **off**) — the services raise
  `vacation_disabled` until it is enabled for a supervised validation session. Values are validated
  before any send (`YYYYMMDD` / `HH:MM`, chronological period, setpoint bounds). `pydanfoss_cloud`
  gains `async_vacation_leave` / `async_vacation_athome` / `async_vacation_cancel` /
  `async_vacation_leave_now`. **No real heating write has been performed; each vacation action needs
  a real-hardware validation with the integrator present** (and confirmation that a bare path-1a
  call without the MiniApp envelope fields is accepted).

- **Distinct device id (coexistence).** The Tuya cloud keys a path-1a session on the request
  `deviceId`, not on the account or the `chKey` (proven on real hardware 2026-11-18): two clients
  sharing one `deviceId` share a single session and log each other out. The integration now derives
  its **own stable `deviceId`** from the captured one (same `sign_key`/`chKey`) via
  `api.derive_distinct_device_id`, so it keeps its own session alongside the app and the MCP
  connector. Controlled by the option **Use a dedicated device id** (`distinct_device_id`, default
  **on**); off reproduces the legacy shared-session behaviour. `CloudClient(..., distinct_device_id=…)`.
  Contract/architecture updated (`docs/architecture.md`). **Needs an in-situ confirmation on the
  school's Pi** (integration keeps its session while the MCP keeps its own).

### Changed

- **Boiler relay is read-only by design (doc alignment, contract §4.6/§7).** Confirmed on real
  hardware 2026-11-18 that the Danfoss app has **no** manual relay on/off: the relay is server-driven
  from the heat demand of the linked rooms. The only write lever is the room↔relay link
  (`set_relay_room`, already shipped). No DP `1` forcing path exists in the integration; the contract
  wording moves from "uncaptured" to "does not exist as an app action".

### Hardening

- Diagnostics redaction extended to options (defensive) and covered for session material
  (`sid`/`ecode`); confirmed all secrets (password, `sign_key`, `ch_key`, `device_id`, session,
  local keys, real device ids) are redacted.
- Test coverage raised (floor 92 → 93 %); new tests for the device-id derivation, the coexistence
  wiring, and the service-path write wrappers.
- mypy and `pip-audit -r requirements.txt` remain green in CI.

## 0.6.1 — Room head attach/detach + multi-home room create

Completes room management on top of 0.6.0. Room head **attach/detach** (deferred from 0.5.0) is
restored, and `create_room` is fixed for **multi-home** accounts. **Validated in situ on the running
install (2026-11-18):** multi-home `create_room` (explicit `home`) creates the room with its heads
grouped, then `attach_heads`, `detach_heads`, detach-to-one (group dissolves) and `delete_room` all
behave, on an isolated verified test room (issue #51).

### Added

- **Room management: attach / detach** — services and WebSocket commands `attach_heads` /
  `detach_heads` (contract §4.7/§5.2/§5.3). Admin-only, value-validated: the member list is the
  current schedule-group membership (read by group id, name-independent) unioned/differenced with
  the given heads, and the write addresses the type-4 room (`async_room_set_devices`, replace-list).
  Detaching every head is refused (`no_members_left` → use `delete_room`). Reuses the
  `_resolve_room_id` `" Group"`-label tolerance.
- **`create_room` home selection** — new optional `home` (gid) field on the service and WS command.

### Fixed

- **`create_room` on multi-home accounts** — the room must be created in the heads' home, otherwise
  the heads cannot join it and it is left empty. `home` selects it explicitly; when omitted it is
  inferred from the devices (the single home that contains them all). When a single home cannot be
  determined — heads span homes, or the backend does not filter the device list by gid — it fails
  with `ambiguous_home` (pass `home`) instead of silently picking the first home, and `unknown_home`
  when a head is in no home.
- **Room changes are visible immediately** — every structural write (create / rename / delete /
  attach / detach, and relay link) invalidates the room-topology cache before refreshing, so the
  new or changed room shows up in `get_rooms` and is targetable at once instead of only at the next
  hourly poll.
- Clearer `config_entry_id` handling: required only when several *config entries* exist (not several
  homes); distinct message when no account is configured.

## 0.6.0 — Full UI: room card and side panel (axis D)

The user-facing UI layer. A **presentation layer over the existing read commands and
already-validated writes** — it adds **no new cloud/local write primitive** (contract §8). Its only
writes reuse validated paths (`climate.set_temperature`, `schedule/set`, `schedule/restore`), so
nothing here needs fresh real-hardware validation. English base + i18n (fr kept); the frontend
bundle is rebuilt deterministically.

### Added

- **Room card (`danfoss-ally-room-card`)** — a per-room Lovelace card: current temperature, mode and
  setpoint; comfort/setback setpoints; a weekly schedule strip; per-head status (online, battery
  with low-battery emphasis, valve, window, child lock, mounting, inconsistent, fault). Admin
  actions reuse existing validated services only: setpoint ± via `climate.set_temperature` (shown
  only when the room is writable, its climate entity is known and the mode is comfort/setback),
  back-to-schedule (R4), and an "edit schedule" toggle that embeds the existing schedule card.
- **Side panel (`danfoss-ally-panel`, `panel_custom`)** — a read-first building/fleet overview: a
  totals header and, per home, a holiday badge, gateways online, a room health grid (offline, low
  battery, calling for heat, open window, faults) and the boiler relays. Registered from the
  integration (sidebar, `require_admin` false), best-effort.
- **Read plumbing** — `HeadState` now carries battery / valve / heat-request / window /
  window-detection / child-lock / faults; `Room` carries the live climate (temperature, setpoint,
  mode, heating, online) plus `writable` and `climate_entity_id`; new `get_overview` service and
  `overview` WebSocket command return a `FleetOverview` (§3.6), all aggregated from the coordinator
  cache with no extra cloud call.

### Notes

- No new write path: the UI reuses the setpoint/schedule writes validated in 0.2.0 / 0.4.0 / 0.5.0.
- Still out of contract (uncaptured, §7): holiday set/exit, direct relay on/off (DP 1); room head
  attach/detach remains deferred (0.5.1).

## 0.5.0 — Holiday, boiler relay and room management (axis B)

Brings holiday, boiler relay and room management into the contract
(`docs/interface-contract.md` §4.5–§4.7). Cloud-first and read-first. The write features are
**validated on real hardware (2026-11-18)**; the one write that could not be faithfully validated
with the current tooling (room head attach/detach) is **deferred to 0.5.1**. The `api/` layer stays
Home-Assistant-free and backward-compatible with `pydanfoss-cloud`.

### Added

- **Holiday (read only)** — per-home `binary_sensor` "holiday active" and `sensor` "holiday
  setpoint" (the raw holiday record is exposed as an attribute); read services `get_holiday` and
  WebSocket `holiday`. The app's holiday *set/exit* routes are not in the APK (runtime
  mini-program), so there is no holiday write (contract §7).
- **Boiler relay (read)** — per-relay `binary_sensor` "boiler relay" (DP 1) and `sensor` "rooms
  calling for heat" (linked rooms); read services `get_relays` and WebSocket `relays`.
- **Room management (write): create / rename / delete** — services and WebSocket commands
  `create_room`, `rename_room`, `delete_room` (+ read `get_room`). Admin-only, value-validated.
  **Validated on real hardware 2026-11-18.** Resolution tolerates Tuya's `"<name> Group"` auto-label
  on the implicit schedule-group (contract §4.7).
- **Room ↔ boiler-relay link (write)** — service and WebSocket `set_relay_room` links/unlinks a
  room to the relay (its heat demand drives the relay). Admin-only. **Validated on real hardware
  2026-11-18.**
- New `api/client.py` read methods (holiday, relay, room map, room-id resolver) and room/relay
  write methods, mirroring the calls validated by the MCP connector.

### Deferred to 0.5.1

- **Room head attach/detach** (add/remove a head in an existing room). The cloud replace-list on a
  group-backed room (type-4 room vs implicit type-5 schedule-group, §4.7) can't be faithfully
  validated with the current tooling — it needs the integration running in situ on the running
  0.5.0 install. The `async_room_set_devices` primitive ships (create_room uses it); only the
  standalone attach/detach operations/services/WS are withheld.

### Notes

- Still out of contract (uncaptured, §7): holiday set/exit, direct relay on/off (DP 1).

## 0.4.0 — Local tunnel wired (axis C)

Wires the local Zigbee tunnel primitives (ported in the `pydanfoss_cloud.local.tunnel` layer) to
Home Assistant as entities/services, and settles two findings from the C0 field validation
(2026-11-17). The cloud-first behaviour is unchanged; the tunnel features require the optional
**local tunnel** (`enable_local`) and act only on **isolated heads of a verified product**.

### Added

- **One-off setpoint override (C1)** — services `set_override` / `clear_override` (and WebSocket
  commands) write a "now" setpoint on a head over the tunnel (DP 171). An override lapses at the
  head's next scheduled change; `clear_override` re-applies the setpoint the schedule prescribes
  now.
- **Valve descaling (C2)** — service `set_descaling` sets a head's weekly valve-descaling day/time
  (0x4010/0x4011).
- **Open-window detection, local write (C3)** — service `set_window_detection` writes DP 116 over
  the tunnel (the authoritative read is attribute 0x4051).
- **Multi-gateway survey (C4)** — read-only service `get_local_survey` (and WebSocket command)
  returns, per reachable head, the tunnel reading summarized (comfort slots, comfort/setback
  setpoints, decoded attributes).

### Fixed

- **Settings write now uses `gwId = meshId` for isolated heads**, aligned on the schedule-write
  path (proven on real hardware, C0b). This lifts the lone `gwId = devId` divergence in
  `api/client.py`. `CloudClient.async_write_setting` gains an optional keyword `gw_id` (additive,
  backward-compatible).

### Documentation

- Interface contract §4.4: the one-off override (DP 171) is encoded in **hundredths of °C**, not
  the `10⁰` the official product schema announces (confirmed in the C0 trial); §4.1/§4.2 note the
  isolated-head `meshId` addressing as confirmed on real hardware.

### Write-safety

Every tunnel write targets an isolated head of a verified product, reachable through the tunnel,
with values validated before sending — otherwise a clean, translated error rather than a misleading
success. The write features **await per-feature real-hardware validation** (see each PR's
validation request); the survey (C4) and the documentation/`meshId` fixes are not blocked on it.

## 0.3.0 — English base language

The whole repository is now authored in **English** (code, docstrings, comments, docs),
with user-facing strings translated per Home Assistant's configured language. The **French
translation is kept** (`translations/fr.json`), so a Home Assistant set to French still shows
French labels.

### Migration — automatic, no action required

Entity `unique_id` slugs were anglicised (for example `…_consigne_confort` → `…_comfort_setpoint`,
`…_detection_fenetre` → `…_window_detection`). On the **first start after updating**, existing
entities are migrated automatically (`async_migrate_entries`): their **`entity_id`, history,
automations and dashboards are preserved**. The migration is idempotent and conservative.

- A Home Assistant running **in English** sees **no visible change** (the `entity_id`s were already
  English; only the internal `unique_id` is remapped).
- A Home Assistant running **in French** keeps its existing French `entity_id`s unchanged.

### Changed

- English as the base language across code, docstrings, comments, docs and `README`.
- Shared library **`pydanfoss-cloud` 0.2.0**: public API renamed to English
  (`FAULT_BITS`, `decode_fault`, `decode_device`, …) and published to PyPI. The MCP connector
  `danfoss-ally-mcp` was updated in lockstep.

### Fixed

- Diagnostics now **redact the account `username`** (the account e-mail — personal data that was
  previously left in clear).

## 0.2.0

- Per-room `climate`, `number` comfort/setback setpoints, weekly schedule card (read + write).

## 0.1.0

- Initial cloud read/write, local tunnel (preheat, schedule read), MQTT publisher.
