# ha-danfoss-ally — Home Assistant Danfoss Ally integration via the cloud API (the non-public one, the app's)

Guide for Claude Code sessions on this repo. Goal: a community HA integration that drives the
Danfoss Ally heads via the **cloud API** (path 1a), with no developer app and no shared quota, with
gateway-key fetching and MQTT publishing of the devices.

## What we are building

- **HA domain**: `danfoss_ally_cloud` (distinct from MTrab's `danfoss_ally`, to coexist; its brand
  icons ship in `custom_components/danfoss_ally_cloud/brand/`).
- **Repo**: `aghulas/ha-danfoss-ally` (private at first, intended for the HACS Marketplace once
  hardened).
- Public release is intended: bring features to the community **and** exercise the code on other
  installs to make the assumptions more reliable.

## Guiding principle: three channels, one router

A head is reachable through three channels: **cloud HTTP** (path 1a), **Tuya cloud MQTT** (the app's
broker; validated on real hardware, opt-in via `enable_cloud_mqtt`) and the **local tunnel**. Each
operation goes to the channel **proven for it on real hardware**; with no proven channel up, the
entity is unavailable. Routing tables and the rules for adding a route: `docs/architecture.md`.

"MQTT" means two things here: **Tuya cloud MQTT** is a channel to the heads; **MQTT publishing**
(`mqtt_publisher.py`) sends our state to the user's own broker. Always say which.

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
  - `api/` — Danfoss access: `client.py` (cloud API), `keys.py` (gateway keys), `local/tunnel.py`
    (Zigbee DP 198→199), `mqtt_publish.py` + `mqtt_client.py` (Tuya cloud MQTT). To extract
    eventually into a library shared with the MCP connector (`manifest.json` → requirements).
  - `coordinator.py` — conservative cloud polling + local overlay.
  - platforms: `climate`, `sensor`, `binary_sensor`, `number`, `switch`.
  - `mqtt_publisher.py` — modes `discovery` / `zigbee2mqtt`, source `cloud` / `local`.
  - `config_flow.py`, `diagnostics.py`, `const.py`.
- `docs/` — `architecture.md`, `roadmap.md`, `reuse.md`.
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
