# Roadmap

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
