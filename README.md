# Danfoss Ally (Cloud) — Home Assistant integration

An **unofficial** community integration for Danfoss Ally thermostatic heads, which talks to the
**same cloud API as the mobile app** — with no developer app, no API key, no shared quota.

Goals:
- simple setup (the app's credentials);
- all cloud features, including those absent from the public API (weekly schedule, window detection,
  child lock…);
- automatic fetching of the **gateways' local keys** for direct Zigbee access, with no emulator or
  Frida;
- **MQTT publishing** of the devices, in two configurable modes: HA MQTT Discovery, or a
  zigbee2mqtt-compatible topic structure.

## Disclaimer

An independent project, **not affiliated with Danfoss or Tuya**. The cloud API is undocumented and
obtained by observing the app's network protocol. It can change or be cut off at any time, which
would break the integration. Use at your own risk. Passwords are never requested by Home Assistant
outside the integration's sign-in screen.

## Installation (custom repository)

1. HACS → ⋮ → Custom repositories → add `https://github.com/aghulas/ha-danfoss-ally` (Integration
   category).
2. Install "Danfoss Ally (Cloud)", restart Home Assistant.
3. Settings → Devices & services → Add integration.

## Configuration

The configuration screen asks for:

- **Username / Password**: the Danfoss Ally / Smart Life app account.
- **Country calling code**: e.g. `33` for France.
- **Datacenter**: `eu`, `us`, `cn` or `in` (France → `eu`).
- **Installation secrets**: `sign_key`, `device_id` (`deviceId`), `ch_key` (`chKey`).

The three installation secrets are specific to one installation of the app and are **captured
once** (they stay stable afterwards). They are essential to the signature and encryption of the Tuya
mobile API; the server rejects an unknown `chKey`. The capture method is described in `docs/` (native
hook / network capture). These values, the password and the session material (`sid`/`ecode`) are
**secrets**: they are never written to the logs or the diagnostics (see `diagnostics.py`).

> **Coexistence with other path-1a clients.** The Tuya server keys a session on the `deviceId`
> request parameter, not on the account or the `chKey`. The integration therefore gives itself a
> **distinct, stable `deviceId`** derived from the captured one (same `sign_key`/`chKey`) so it
> keeps its own session and does not log out the Danfoss app or the MCP connector `danfoss-ally-mcp`
> (and vice-versa). This is on by default (option *Use a dedicated device id*); turn it off only to
> reproduce the legacy shared-session behaviour. Detail in
> [`docs/architecture.md`](docs/architecture.md) ("Tuya session and coexistence with the MCP
> connector").

## Embedded frontend (dashboard card)

The integration **ships its own Lovelace card** `danfoss-ally-schedule-card` (a room's schedule).
Nothing more to install: after installation via HACS and a restart, the card appears directly in the
**card picker** ("Add card").

![Danfoss Ally Schedule card](docs/images/schedule-card.png)

The card shows, read-only, for the chosen room: its name, the **comfort** and **setback** setpoints,
the **seven-day grid** (comfort slots positioned over 24 h), the **head states** (online, schedule
active, inconsistent, mounting — icons and tooltips), a **"refresh"** button and the **last-read
date**. Light / dark theme via Home Assistant variables, keyboard-usable, `en` / `fr` texts. Editing
will come later.

How it works:

- the integration serves its frontend at URL `/danfoss_ally_cloud/frontend/` and declares the
  resource `…/danfoss-ally-cloud.js?v=<version>` for **storage-mode** dashboards (the default) — no
  manual step needed;
- the card checks its version on load and **offers to reload** the page when a new version has been
  installed.

### YAML-mode dashboard

In YAML mode, resources are not managed by the frontend: add it once by hand.

```yaml
# configuration.yaml (or the dashboard's resource file)
lovelace:
  mode: yaml
  resources:
    - url: /danfoss_ally_cloud/frontend/danfoss-ally-cloud.js
      type: module
```

Then, in a manual card:

```yaml
type: custom:danfoss-ally-schedule-card
room_id: "13000000" # the room's group_id
```

### Developing the frontend

The TypeScript + Lit sources are in `frontend/`. The bundle **is versioned** in the repo
(`custom_components/danfoss_ally_cloud/frontend/danfoss-ally-cloud.js`) so HACS works from any branch
or tag. The **exact** build command (deterministic output, checked in CI):

```bash
npm --prefix frontend ci
npm --prefix frontend run build   # regenerates the versioned bundle
```

Other commands: `npm --prefix frontend test` (Vitest), `npm --prefix frontend run typecheck`, and
`npm --prefix frontend run demo` (demo page outside Home Assistant, synthetic test data, at
http://localhost:5173/demo/).

## Head settings (child lock, window detection)

- **Head in a room**: the switch writes the setting on the **room**, so it applies to **every head
  of that room** (attributes `write_path: room`, `room_head_count`).
- **Isolated head** (in no room): the cloud route accepts the request but does not apply it
  (real-hardware validation, 2026-11-19). Window detection then goes through the local tunnel if
  `enable_local` is on and the head answers locally; otherwise, and always for the child lock, the
  switch is **unavailable** rather than showing a state it cannot set.

## Status

**v0.1 — cloud read-only**: each head appears as a thermostat (temperature, setpoint); battery,
valve-opening and fault-code sensors; online / window binary sensors. No write yet. Embedded
frontend: `danfoss-ally-schedule-card` in **read** mode (setpoints, weekly grid, head states,
refresh). See `docs/roadmap.md`.
