# Changelog

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
