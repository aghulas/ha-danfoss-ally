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

If the account later refuses the sign-in (password changed, installation secrets no longer valid),
Home Assistant shows a **Re-authenticate** prompt for the entry: enter the new password of the same
account, and the installation secrets only if they changed. The entry is updated and reloaded; there
is no need to delete and re-add it.

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

## MQTT publishing: what is published

`mqtt_mode` publishes the integration's state to **your own broker** (nothing to do with the Tuya
cloud MQTT channel below). Read-only: no command topic.

| Device | `discovery` | `zigbee2mqtt` |
|---|---|---|
| Thermostatic head | temperature, active setpoint, battery, valve opening, window; availability | same values under z2m property names, plus `running_state`; availability; listed in `bridge/devices` |
| Boiler relay | one binary sensor (on/off); availability | not published |
| Room sensor, gateway, anything else | not published | not published |

- **Boiler relays** are published in `discovery` mode only: the `zigbee2mqtt` device list describes
  thermostats to a z2m consumer, and a relay does not fit that description.
- **Room sensors are not published, on purpose for now**: the integration does not decode that
  category at all (it creates no Home Assistant entity for them either), because their data points
  have not been verified on real hardware. Publishing them needs that verification first.
- Topics: `<base>/<device id>` (state, JSON) and `<base>/<device id>/availability` in `discovery`
  mode; `<base>/<name>` and `<base>/<name>/availability` in `zigbee2mqtt` mode.

## Head settings (child lock, window detection)

- **Head in a room**: the switch writes the setting on the **room**, so it applies to **every head
  of that room** (attributes `write_path: room`, `room_head_count`).
- **Isolated head** (in no room): the ordinary cloud route accepts the request but does not apply it
  (real-hardware validation, 2026-11-19). Window detection then goes through the local tunnel if
  `enable_local` is on and the head answers locally; otherwise the switch is **unavailable** rather
  than showing a state it cannot set.

## Devices and entities that are no longer provided

At each start the integration removes what it can no longer provide, so nothing lingers as a
"restored, unavailable" orphan:

- the device (and all its entities) of a head, relay or sensor that has **left the account**;
- the **preheat** switches when the local tunnel option (`enable_local`) is off — they only exist
  through the tunnel. If the tunnel is enabled but could not start, they are kept;
- the "Cloud MQTT link" sensor when the cloud-MQTT option is off.

A device is only removed when the integration is sure it is gone, and never in bulk:

- the cloud's device list must be **complete** (every home answered) and **the same as at the
  previous start** (same homes, same number of devices in each). Whenever it differs — first
  start, a home that did not answer, a shorter list — nothing is removed; the next start that
  shows the same picture again does it. A device that left is therefore cleaned up one restart
  later;
- at most **3 devices per start, or 5 % of the entry's devices** if that is more. Above that,
  nothing is removed and a warning in the log says so: delete them yourself from their device page
  if they really left the account.

Room and home devices are never removed automatically (their presence depends on reads that may
fail at start-up). A room that was dissolved can be deleted by hand from its device page: the
"Delete" action is offered for any device the integration no longer provides.

### Cloud-MQTT write path for isolated heads (experimental, off by default)

The Danfoss app writes an isolated head's settings by publishing the DP over Tuya cloud MQTT. The
integration can do the same, **gated behind the `enable_cloud_mqtt` option (off by default)**.

- **What it does**: when enabled, the integration opens one Tuya cloud MQTT connection from its own
  session (its own deviceId, so it coexists with the app and does not log it out) and lets an
  **isolated** head's **child-lock** switch write via MQTT instead of being unavailable, adds its
  **setpoint bounds** and its **comfort, setback and pause setpoints** as numbers, and gives its
  **window-detection** switch a fallback when the local tunnel is not available. A
  diagnostic **"Cloud MQTT link"** sensor shows whether the connection is up. Each write is confirmed
  by the gateway's reply (or a cloud re-read) with a timeout and a clear error — it never shows a
  value it did not confirm.
- **Scope**: child lock (DP 30), window detection (DP 116), upper and lower setpoint bounds (DP 18,
  DP 27), pause setpoint (DP 120), comfort setpoint (DP 118 + 16) and setback setpoint (DP 119),
  each validated on real hardware (2026-11-19 and 2026-11-20). An isolated head carries a new
  comfort or setback value into its own schedule; setting the comfort value outside a comfort
  period makes the head heat towards it for a few minutes before it returns to its schedule; the
  comfort write is refused for a head in manual, pause or holiday mode (not validated). Window
  detection keeps going through the local tunnel when it is available; cloud MQTT is its fallback.
  Other settings are added one at a time after their own supervised validation. Until then they
  are present in the code but **closed**: the options `cloud_mqtt_supervised_dps` (empty by
  default) and `cloud_mqtt_supervised_head` (none by default) open one, on that one test head
  only, for a first write done in person. Leave both empty in normal use.
- **Requirement**: the path uses `paho-mqtt` (declared in `manifest.json` as `>=1.6.1,<3`, the MQTT client Home Assistant's own MQTT integration already ships — HA pins the exact version); Home Assistant installs it automatically. No manual step.
- **Unofficial and optional.** Nothing in the integration needs this channel: with the option off
  (the default) no connection to the Tuya broker is ever opened, and an isolated head's child lock
  is simply unavailable. It reproduces what the Danfoss app does and is not a documented or
  supported API; Danfoss or Tuya can change or close it without notice.
- **Risks for your account.** The channel keeps a **long-lived connection** to the Tuya MQTT broker
  from a client that is not the app, which is more visible than the spaced HTTP polling. It rides
  the same account session as the rest of the integration. The provider could react by refusing
  the connection, invalidating the session (the integration then signs in again) or restricting
  the account; none of this has been observed, but it cannot be ruled out. Use it knowingly, on an
  account you are entitled to use this way.
- **What limits the exposure.** One connection per config entry, from the integration's own session
  (the app and other clients are not logged out). Reconnection backs off exponentially from 5 s to
  5 min. Credentials are rebuilt from the current session before each reconnection. If the broker
  refuses them five times in a row the link **stops for good** until the integration is reloaded,
  rather than retrying forever. No credential, client id or device identifier is written to the
  log or the diagnostics.
- **Kill switch.** Turn `enable_cloud_mqtt` off: the entry reloads and the connection is closed.
  The "Cloud MQTT link" sensor (attribute `state`: `connecting`, `connected`, `refused`,
  `stopped`) and the `cloud_mqtt_link` block of the diagnostics show what the link is doing.
- **First write.** Expect to validate a first write of each setting on a test head yourself (see
  `docs/first-write-procedure.md`).

### Measuring what the Tuya cloud MQTT broker pushes (listen-only, off by default)

The option `cloud_mqtt_probe` opens the same connection in **listen-only** mode (nothing is sent to
the heads) and counts, per head and per DP, the reports the broker pushes. The aggregates are in the
entry's diagnostics, with no device identifier. It exists to decide whether those pushed reports
could later replace part of the polling; it is not needed for normal use. It opens a long-lived
connection on your account (same caveat as above) and closes itself after 48 h. How to run and read
it: `docs/cloud-mqtt-coverage.md`.

## Status

**v0.1 — cloud read-only**: each head appears as a thermostat (temperature, setpoint); battery,
valve-opening and fault-code sensors; online / window binary sensors. No write yet. Embedded
frontend: `danfoss-ally-schedule-card` in **read** mode (setpoints, weekly grid, head states,
refresh). See `docs/roadmap.md`.
