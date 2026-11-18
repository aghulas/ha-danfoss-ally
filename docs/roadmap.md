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
