# Roadmap

> **Note (2026-11):** releases now follow the **axis** plan agreed with the owner, which supersedes
> the per-version list below. Shipped: **0.3.0** (i18n), **0.4.0** (axis C — local tunnel wired),
> **0.5.0** (axis B — holiday read, boiler relay, room management; contract §4.5–§4.7). Remaining:
> **axis D**, then **axis A** (1.0 hardening + HACS inclusion). The per-version list below is kept
> for historical context.

- **v0.0** — skeleton: HA tree, config_flow/options, stubs, CI (hassfest + HACS + ruff + pytest).
- **v0.1** — cloud read-only: climate (temperature, setpoint) + sensors, on a real install.
- **v0.2** — validated cloud writes (setpoints, child lock, window) on verified models; values
  checked before sending.
- **v0.3** — optional local tunnel: preheat (0x0025) and reading the weekly schedule from the head.
- **v0.4** — MQTT publishing, `discovery` mode.
- **v0.5** — MQTT publishing, `zigbee2mqtt` mode (bridge/devices + z2m topics).
- **v0.6** — extraction of the `api/` layer into a library shared with the MCP connector.
- **v1.0** — hardening (tests, coverage, mypy, diagnostics), then an inclusion PR to the HACS
  Marketplace.

Cross-cutting goal: exercise the code on other installs (firmwares, product ids, gateway models) to
make the DP assumptions more reliable.

## Device lifecycle: unbind shipped (gated), pairing out of scope

- **Unbind ("disconnect") — shipped, GATED.** Any sub-device — head, sensor, relay or other — can
  be unbound from the network via the `disconnect_head` service (`smartlife.m.device.reset` v3.0
  `{devId, resetFactory}`, captured on real hardware 2026-11-18 — see
  `~/dev/danfoss-ally-signing-re/NOTES.md`, "GATE A/D"). A **gateway is refused** (it would drop all
  its heads). The scope was widened from heads-only to all sub-devices on 2026-11-18, mirroring the
  MCP connector (PR #7); unbind is a Tuya-generic, category-based call, so there is no
  verified-product gate on it. Triple-gated (admin with no user-less calls + the
  `enable_head_unbind` option, **off by default** + explicit `confirm`). `resetFactory=false` keeps
  the device's identity (same devId on re-pairing to its gateway); `resetFactory=true` is a factory
  reset (new devId, identity lost, irreversible). **Validating a real disconnect through HA is still
  pending** (integrator present, real device, app signed out of path 1a): it is left off by default
  until then.

- **Pairing (add) — OUT OF SCOPE, no path-1a route.** Re-adding/pairing a head is deliberately NOT
  exposed. Opening the gateway's permit-join is **not** an HTTP `m.*` call: the "open network" order
  travels over **MQTT** (`m1.tuyaeu.com:8883`) to the chosen gateway, outside the path-1a HTTP
  client, and completing a pairing requires a **physical action on the head, on site**. A full
  re-pairing (after a wipe, or onto another gateway) mints a new devId through the activator flow,
  again MQTT-driven. Covering it would need the gateway MQTT channel (and, to observe the Zigbee
  `leave`/join frames, a radio sniffer with the network key) — a separate track, not path 1a.

## Post-command freshness (R-3): per-device refresh after a write — shipped, GATED

Real-hardware validation (2026-11-18, on a test head) found that the bulk list route
`tuya.m.my.group.device.list` — the coordinator's only path-1a source of DP state — **lags for
several minutes after a command**, even with a forced refresh: it keeps returning the previous
schedule's valve (`pi_heating_demand`, DP 170), `work_state` (DP 3), active setpoint and mode while
the head is already physically updated. So a write round-trip (the user sets a setpoint/mode and
expects to see it in HA and MQTT in good time) stays frozen on the old state. The bulk endpoint lags
*itself*, so polling it faster does not help.

**Mechanism (coordinator, `note_commanded` + `_overlay_commanded`).** A head commanded through a
write (room setpoint, schedule set/restore) is marked "hot" for `POST_COMMAND_REFRESH_TTL` (300 s).
While hot, each poll reads it through the **per-device route** (`CloudClient.async_get_device_dps`,
`smartlife.m.device.get` v4.0) and **overlays** its fresh DPs onto the device the bulk poll produced
(`decode.apply_dps_overlay`): fresh DPs win key by key, the stable identity/topology and every DP the
per-device route does not carry keep their bulk value. After the window the head returns to the bulk
route. Bounded on purpose (the user's real Tuya account): only hot heads are individually read, at
most `POST_COMMAND_REFRESH_MAX_HEADS` (12) per poll, one read each; a read failure or an empty
response keeps the bulk value (never raises).

**Settle delay (`POST_COMMAND_SETTLE`, 15 s; 1.1.0-rc1 finding).** The cloud takes a command into
account in about 15 s. A per-device read made right after the write returns the **pre-command**
state: on rc1 the written switch stayed one write behind until the next poll, while its room
neighbour, read from the bulk list, was already right. So a hot head is **not** overlaid during the
first 15 s (the write's own immediate refresh keeps the bulk value), and **one extra refresh** is
scheduled at the end of the delay to read it once the cloud has it: the result shows up in ~15 s
instead of a full poll. Re-arming on a new command keeps a single pending refresh; it is cancelled
on shutdown. Still never optimistic: what is shown is what the cloud returns.

**GATED, off by default (`enable_post_command_refresh`, `CONF_POST_COMMAND_REFRESH`).** Two reasons:
it adds a per-device read pattern on the real account, and **that `smartlife.m.device.get` is fresher
than the bulk list for a HEAD is the R-3 hypothesis still to confirm on real hardware** — the
freshness observed in validation came from the MCP connector's *individual route*, which is the
**official Danfoss REST API** (`GET /ally/devices/{id}`), a different backend this integration does
not use. `async_get_device_dps` is the single seam: if validation shows `device.get` is not fresher
for a head, only that method's backing route changes (e.g. the official Danfoss per-device route, or
the local Zigbee tunnel), not the mechanism, the gating or the tests.

**Residual latency.** With the option **off** (default): unchanged — a write round-trip surfaces only
on the bulk route's own schedule, i.e. up to several minutes. With it **on** and the hypothesis
confirmed: a commanded head refreshes on the next poll after the write (the write path arms the
window before its own `async_request_refresh`, so even that immediate refresh overlays the fresh
state), and stays fresh for 5 minutes; uncommanded heads are unaffected. The TTL is a floor on how
long the overlay is trusted, not a guarantee the per-device route itself is instantaneous — to
measure on real hardware in the validation session.

**Confirmed on real hardware (2026-11-19).** With the option on, a room setpoint write showed up in
HA and in the published MQTT state within one to two polls, while the bulk list still returned the
old value: `smartlife.m.device.get` **is** fresher than the bulk list for a head. The option stays
off by default (extra reads on the user's account).

## Tuya cloud MQTT channel — staged, each stage gated

Background and routing: `docs/architecture.md`. The app writes an isolated head's settings with a DP
publish over Tuya cloud MQTT, the only path found that applies them (contract §4.2).

1. **Write, child lock first — shipped on `main`.** Option off by default; a link-state diagnostic entity; confirmation
   by the gateway's echo or a cloud re-read, never optimistic. Validated on real hardware
   2026-11-19 (session coexists with the phone app; write applied on the head).
2. **More DPs, one at a time**, each after its own supervised write read back from an independent
   source: window detection (compare with the local tunnel), bounds, isolated-head setpoints.
   Preheat last, read back as attribute 0x0025 (cloud DP 1 over HTTP only changed the gateway cache).
   A DP ships first as a **candidate**, closed unless listed in `cloud_mqtt_supervised_dps`, and is
   promoted after its supervised write (`docs/first-write-procedure.md`).
   - Window detection (DP 116): **proven 2026-11-19**, read back through the local tunnel and in
     the app. The tunnel stays the first route; cloud MQTT is the fallback.
   - Bounds (DP 18 upper, DP 27 lower, alone and with DP 120 in one frame): **proven 2026-11-19**,
     read back through the local tunnel and in the app.
   - Pause setpoint (DP 120): **proven 2026-11-19**, read back in the app and the cloud only (no
     tunnel read exists for it).
   - Comfort and setback setpoints (DP 118 + 16, DP 119): candidates, code shipped, **supervised
     writes pending**. Not run on 2026-11-19: the test head was in manual mode and could not be
     put in a comfort slot. To run on an isolated head that already follows a schedule, in a
     comfort slot. The trial must also settle whether a schedule rewrite is needed after the
     publish, as for rooms (R3).
   - Preheat (DP 1): **not implemented**. Written proposal, with the observation to make before
     any code and an assessment (probably not worth a second route):
     `docs/cloud-mqtt-preheat-proposal.md`.
3. **Measure inbound coverage**: which heads and DPs the broker pushes, and how often, over a full
   day. **Tooling shipped**: the listen-only option `cloud_mqtt_probe` (off by default) accounts the
   pushed reports per head and per DP and serves the aggregates in the diagnostics. The 24 h run on
   a real install is still to do; how to run and read it, and what it must show to start stage 4:
   `docs/cloud-mqtt-coverage.md`.
4. **Push as a read source**, if stage 3 shows full coverage: feed the coordinator from the pushed
   reports, drop the post-command per-device read, lengthen the polling period.
5. **Hardening before it is on by default anywhere**: kill switch, reconnect backoff, session
   rotation, redacted diagnostics for the link, "unofficial" wording in the README. **Code and docs
   done** (`docs/cloud-mqtt-publish.md`, "Link lifecycle"); the behaviour of an established
   connection across a real session renewal is still to observe on real hardware. The option stays
   off by default.

## Per-room schedules and embedded frontend

Work described by `docs/interface-requirements.md`, framed by the contract
`docs/interface-contract.md` (rules R1–R7). One batch = one branch = one pull request, validated on
real hardware on a test room.

- **Batch 0** — document upgrade (R4/R5) and alignment of the thermostat on R3 (no mode-setpoint
  write without rewriting the schedule).
- **Batch 1** — `api/` layer: `schedule.py` (model, conversions, R1 validation), rooms and schedule
  in `client.py`, decoding of the real state (DP 172).
- **Batch 2** — Home Assistant wiring: per-room device, entities, actions + WebSocket, write jobs
  (`WriteJob`), deferred local verification.
- **Batch 3** — embedded frontend base (`frontend/`, TypeScript + Lit, versioned compiled file,
  Lovelace registration, minimal card).
- **Batch 4** — read-only Schedule card (7-day grid, head states).
- **Batch 5** — editable Schedule card (slot editing, R1 validation, job tracking, back to
  schedule).
