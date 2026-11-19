# Cloud-MQTT listen-only probe — deploy & test (validation session)

Goal: settle whether the Tuya broker accepts an **independent** session of the account on MQTT while
the phone app is connected (→ one-per-**session**, coexistence works, the cloud-MQTT write path is
viable) or refuses it (→ one-per-**account**). Earlier probes borrowed the app's own session and
could not tell (see docs/cloud-mqtt-publish.md §6.3b). This probe runs **inside the integration**,
from **its own session** (its distinct deviceId — no secret is taken from HA storage).

## What it does / safety

- **Listen-only, no publish path.** The probe is a dedicated class (`CloudMqttListener`) with **no
  send method at all** — not a disabled flag; a test asserts the object exposes nothing publish-like.
  It opens one TLS connection, subscribes to `smart/mb/in/<gw>` for the known gateways, decodes
  inbound frames, and records a redacted result. It never writes to a head.
- **Own session**, distinct from the app / iPhone / MCP connector. The clientId uses a probe-dedicated
  deviceId; the username carries the integration's own `sid`/`ecode`. Enabling the probe forces one
  fresh login of the integration's own session.
- **Auto-stops** after `CLOUD_MQTT_PROBE_MAX_SECONDS` (600 s = 10 min) and on unload/reload (turning
  the option off reloads the entry, which stops it).
- **Gated OFF by default** (`cloud_mqtt_probe`), separate from the write gate `enable_cloud_mqtt`.
- **No secret in the result**: diagnostics expose only CONNACK rc/text, timestamps, per-gateway
  received/decoded counts, a few sample `(protocol)` tuples (the `cid` is redacted), and the last
  error. Never sid/ecode/username/password/localKey or raw payload.

## Commit to deploy

The **tip of branch `claude/stoic-lalande-4577d6`** (PR #71, draft), rebased on `main` which already
contains #73 (the R-3 settle delay) — so it layers cleanly on 1.1.0-rc2. The exact SHA is given with
this deliverable in the status message. Deploy that commit's `custom_components/danfoss_ally_cloud/`
over the Pi; **do not merge to `main`**.

Dependency: the probe uses **paho-mqtt**, already bundled by Home Assistant — nothing to install.

## Test procedure

1. Deploy the commit; restart HA.
2. Open the Danfoss **iPhone app** on a head page and keep it open (so the app's MQTT is connected).
3. In the integration's options, turn **`cloud_mqtt_probe` ON**. The entry reloads and the probe
   connects once from the integration's own session; it auto-stops after 10 minutes.
4. Download the integration's **diagnostics** (Settings → Devices & services → the entry → ⋮ →
   Download diagnostics). Read `cloud_mqtt_probe`:
   - `connack_rc`, `connack_text` — the broker's verdict.
   - `total_received` / `received_per_gateway`, `total_decoded` / `decoded_per_gateway`.
   - `sample_frames` (protocol only; cid redacted), `last_error`.
5. While the probe is connected, **watch the iPhone app**: does it stay connected / keep updating, or
   does it get kicked (logged out of MQTT)? Note which.
6. Turn `cloud_mqtt_probe` **OFF** (or just let it auto-stop); confirm the entry reloaded.

## Verdict criteria

- **`connack_rc` = 0** (and ideally some decoded frames), **app stays connected** → an independent
  session CAN hold MQTT concurrently: **one-per-session, coexistence works, write path viable.**
- **`connack_rc` = 0** but the **app gets kicked** → the broker allows one MQTT per account and the
  last connector wins; coexistence would fight the app → write path **not** viable as-is.
- **`connack_rc` = 5** (not authorised) with the integration's **own fresh** session → one-per-account
  (or a stricter auth we haven't modelled) → write path **not** viable without usurping the single
  session. Record it as a final result; keep the codec + listen-only decode, shelve the write path.
- **Other rc / `last_error` set** → report it (a TLS error means the CA bundle wasn't found).

## Returning to `main`

The probe is only on this branch. To revert the Pi, redeploy `main` (or 1.1.0-rc2) over
`custom_components/danfoss_ally_cloud/` and restart; nothing persists except the option value in the
entry, which does nothing without this branch's code. No data migration, no cleanup needed.
