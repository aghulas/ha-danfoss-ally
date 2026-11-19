# Changelog

## Unreleased — 1.2.0 (gated cloud-MQTT write path for isolated heads)

Adds the write path the Danfoss app uses for **isolated** heads (those not grouped into a room),
which `tuya.m.custom.wkf.settings.change` does not reach (W-3): a DP publish over Tuya cloud MQTT.
Reverse-engineered from the app and **validated on real hardware (2026-11-19)** — see
docs/cloud-mqtt-publish.md. **Off by default**; existing installs are unchanged.

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
  cloud, the app and physically on the head.** DP 30 only for now (`MQTT_WRITE_DPS`); other settings
  follow one per supervised validation.
- **"Cloud MQTT link" connectivity binary sensor** (diagnostic, present only when the link exists),
  so the link never fails silently; reconnect uses exponential backoff and picks up a refreshed
  `sid`.

- **`cloud_mqtt_probe` option (OFF by default): listen-only measure of the cloud-MQTT push.** Counts
  the DP reports the broker pushes, per head and per DP (number, first and last instant, median and
  longest interval, heads never seen), and serves the aggregates in the diagnostics with no device
  identifier and no DP value. Without `enable_cloud_mqtt` the link has no send path and closes
  itself after 48 h. Tooling for roadmap stage 3; the 24 h run on a real install is still to do
  (docs/cloud-mqtt-coverage.md).

- **Window detection (DP 116) as a cloud-MQTT candidate, closed by default.** A DP now ships first
  as a candidate (`MQTT_CANDIDATE_DPS`) that only the new option `cloud_mqtt_supervised_dps` (empty
  by default) opens, for its supervised first write; the switch then shows `write_trial: true`.
  Outside a trial, an isolated head's window detection still goes through the local tunnel first.
  **Not validated on real hardware yet.**
- **Setpoint bounds of an isolated head (DP 18 upper, DP 27 lower) as cloud-MQTT candidates, closed
  by default.** Two `number` entities per isolated head, present only while their DP is open. Values
  are checked before sending (schema range and step, ordering, no bound that excludes the comfort
  or setback setpoint). Raising the lower bound above the pause setpoint also sends DP 120 in the
  same frame. **Not validated on real hardware yet.**
- **Comfort, setback and pause setpoints of an isolated head (DP 118 + 16, 119, 120) as cloud-MQTT
  candidates, closed by default.** Three `number` entities per isolated head, present only while
  their DPs are open. They had no path at all before. Written as the app does: MQTT publish, then
  for comfort and setback the whole settings block over HTTP. Values are checked against the head's
  own bounds before sending. **Not validated on real hardware yet**; the trial must also settle
  whether a schedule rewrite is needed after the publish.
- The cloud-MQTT write confirmation falls back to one read of the head through the per-device
  route when the gateway's echo does not come (it used the bulk list, which lags for minutes).

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

## Unreleased — Local tunnel: non-blocking start

### Fixed

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

## Unreleased — Home Assistant 2026 deprecations

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
