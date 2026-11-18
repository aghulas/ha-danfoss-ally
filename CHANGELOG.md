# Changelog

## Unreleased — Coexistence + hardening (axis A, toward 1.0)

Path-1a coexistence with the Danfoss app / MCP connector, plus 1.0 hardening. No new cloud/local
write primitive; the boiler-relay change below is documentation only. The version bump and tag are
left to the integrator.

### Added

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
