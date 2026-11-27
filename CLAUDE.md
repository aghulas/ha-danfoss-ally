# ha-danfoss-ally — Home Assistant Danfoss Ally integration (v2 Bridge + Companion & v1.x Direct Cloud)

Guide for agent sessions on this repo. Goal: a community HA integration for Danfoss Ally heads,
room sensors (`014G2480`), and boiler relays (`014G2400`) — running in **v2.x Bridge + Companion**
mode over Mosquitto (`zigbee2mqtt` + `danfoss2mqtt`, `docs/companion-contract.md`), while keeping
the **1.4.x direct-cloud** line (path 1a + local tunnel + Tuya cloud MQTT) frozen for backward
compatibility.

## What we are building

- **HA domain**: `danfoss_ally_cloud` (distinct from MTrab's `danfoss_ally`, to coexist; its brand
  icons ship in `custom_components/danfoss_ally_cloud/brand/`).
- **Repo**: `aghulas/ha-danfoss-ally` (**public** on GitHub: every pushed branch and commit is
  visible; intended for the HACS Marketplace once hardened). Also packages `custom_components/danfoss_ally_cloud/api/` as `pydanfoss-cloud`
  (`pyproject.toml`, including the standalone `danfoss2mqtt` CLI daemon).
- Public release is intended: bring features to the community **and** exercise the code on other
  installs to make the assumptions more reliable.

## Guiding principle: proven routes only, zero optimistic state

In **v2.x**, Home Assistant connects solely to Mosquitto (`mqtt_companion.py`) and merges
`zigbee2mqtt` and `danfoss2mqtt` devices under a single model (`api/z2m_contract.py`). In
**1.4.x** (and inside `danfoss2mqtt`), a head is reachable through three channels: **cloud HTTP**
(path 1a), **Tuya cloud MQTT** (the app's broker; validated on real hardware, opt-in via
`enable_cloud_mqtt`) and the **local tunnel**. Each operation goes to the channel **proven for it
on real hardware**; with no proven channel up, the entity is unavailable. Routing tables and the
rules for adding a route: `docs/architecture.md` and `docs/companion-contract.md`.

"MQTT" means three distinct things here: **local Mosquitto Companion** (`mqtt_companion.py`, v2
integration ↔ `zigbee2mqtt`/`danfoss2mqtt`), **Tuya cloud MQTT** (`api/mqtt_client.py`, channel to
heads on Danfoss gateways), and legacy **MQTT publishing** (`mqtt_publisher.py`, v1 state export).
Always say which.

Cases established on real hardware where the cloud **lies or does not act**:

- The **switch to manual mode** (DP 2 `manual`) erases the head's schedule (R4); `at_home` /
  `leaving_home` published via DP 2 are only **labels** on the cloud side: the head keeps its
  schedule's setpoint (R5). The return to schedule = rewrite the room's schedule, then publish
  `at_home`. Detail and rules R1–R7: `docs/interface-contract.md`.
- Preheat: cloud DP 1 only touches the gateway cache; the real lever is the Zigbee attribute
  **0x0025**, reachable only through the local tunnel.
- `update_time` is event-driven: `online` is authoritative, not it.
- Settings of an **isolated** head: HTTP `settings.change` is accepted and never applied. A grouped
  head is written through its room; an isolated one through the local tunnel or cloud MQTT.
- The bulk list route lags by minutes after a change; the per-device route is fresher.

So never "all cloud", and never a fallback to a channel that merely accepts the call. A new DP on a
channel needs its own supervised write, read back from an independent source. The gateway keys are
fetched by the integration itself and serve both the local tunnel and the cloud-MQTT frames.

## Code map

- `custom_components/danfoss_ally_cloud/` — the integration.
  - `api/` — `pydanfoss-cloud` library (`pyproject.toml`): `client.py` (cloud API), `keys.py`
    (gateway keys), `local/tunnel.py` (Zigbee DP 198→199), `mqtt_publish.py` + `mqtt_client.py`
    (Tuya cloud MQTT), `z2m_contract.py` (bidirectional Z2M codec), `bridge_daemon.py`
    (standalone `danfoss2mqtt` daemon).
  - v2 Companion: `mqtt_companion.py`, `companion_rooms.py`, `companion_adapter.py`.
  - v1 Direct Cloud (frozen): `coordinator.py` (cloud polling + local overlay),
    `mqtt_publisher.py`, `mqtt_write.py`, `local_write.py`.
  - shared platforms & ops: `climate`, `sensor`, `binary_sensor`, `number`, `switch`, `select`,
    `time`, `operations.py`, `ops_rooms.py`, `ops_views.py`, `ops_local.py`, `services.py`,
    `websocket_api.py`, `config_flow.py`, `diagnostics.py`, `const.py`.
- `frontend/` — TypeScript + Lit Lovelace cards and panel (compiled bundle in
  `custom_components/danfoss_ally_cloud/frontend/danfoss-ally-cloud.js`).
- `docs/` — `architecture.md` (channels, routing), `interface-contract.md` (R1–R7, DPs),
  `companion-contract.md` + `v2-cutover.md` + `z2m-cloud-parity.md` (2.x), `cloud-mqtt-channel.md`,
  `preheat.md`, `first-write-procedure.md` (supervised trials), `roadmap.md`, `reuse.md`; trial
  records in `docs/validation/`.
- `tests/` — pytest-homeassistant-custom-component.

## Reuse (do not rewrite)

See `docs/reuse.md`. In short: the app's signature in `~/dev/danfoss-ally-signing-re`; keys, DPs,
tunnel and fault decoding in `~/dev/danfoss-ally-mcp` (`tuya/pilote_tuya.py`, `local.py`,
`modeles.py`); official DP names in `~/dev/danfoss-app-capture/dp_schema_officiel.md` (source of
truth).

## Non-negotiable rules

- **Secrets**: session token, password, gateways' localKey, real device identifiers — never in the
  logs (stderr included), the diagnostics or the repo. `diagnostics.py` redacts. `git grep` before
  any push.
- **Tuya fragility**: we ride the Tuya app's auth; it can be invalidated or changed. Robust
  re-authentication, conservative polling defaults (this is the user's real account), "unofficial"
  framing in the README.
- **Write safety** (different from the MCP): here no prepare→confirm token; safety comes from
  **value validation** before sending and from entities being unavailable rather than lying (e.g.
  the preheat switch is unavailable if the local tunnel is down). Only extend writes to models
  verified on real hardware (`const.WRITE_VERIFIED_MODELS`).
- No school data or real key in the tests: synthetic data only.

## Tests and quality

```
python3.14 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy custom_components/danfoss_ally_cloud
.venv/bin/pytest -q
```

If `frontend/` changed, also run (and commit the rebuilt bundle
`custom_components/danfoss_ally_cloud/frontend/danfoss-ally-cloud.js`):

```
npm --prefix frontend ci && npm --prefix frontend run typecheck && npm --prefix frontend test
npm --prefix frontend run build
```

Everything green before commit: these are exactly the commands CI runs (`.github/workflows/`: `test`
= ruff + mypy + pytest with the coverage threshold, `frontend` = typecheck + vitest + build +
"bundle up to date" check, plus `hassfest` and `hacs`). The test harness tracks the production HA
line (Python 3.14, `pytest-homeassistant-custom-component` pinned in `requirements-dev.txt`, bumped
with prod HA); a non-required `test-ha-floor` job re-runs the tests on Python 3.12 / HA 2025.1.x.
`main` is protected: those four checks are required, so a PR cannot merge while one is red. Aim
eventually for the level of a serious integration: high coverage, redacted diagnostics, dependency
audit.

## Publishing (HACS / Marketplace)

Prerequisites already in place: `manifest.json` (domain, name, semver version, codeowners,
documentation, issue_tracker, iot_class, config_flow), `hacs.json`, CI workflows, a single component
under `custom_components/`. Brand icons ship in the component's `brand/` folder (HA >= 2026.3;
`home-assistant/brands` no longer accepts new custom integrations). Remaining before inclusion:
tagged releases, then an inclusion PR (only the
owner/major contributor can submit it). Installable as a custom repository already.

## Commit, push, discipline

- Commit and push **only when Rémi asks**. One branch per non-trivial change. Messages in English,
  the body listing the changes and the real-hardware validation, then the attribution lines
  indicated by the session.
- Before a push: `git grep` to check for the absence of secrets.

## Links with the rest of Hesto

claude.ai project notes to keep consistent: `claude/connecteur-danfoss-ally.md` (MCP connector,
lessons, fleet), `claude/danfoss-cles-locales-voie-a.md` (key method),
`claude/tunnel-zigbee-danfoss-dp198.md` (tunnel). The field lessons (incidents of 2026-11-01,
preheat, DP pitfalls) come from there.
