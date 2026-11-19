# Real-hardware validation plan — coherence app ↔ HACS ↔ MQTT

> Goal (owner's framing, 2026-11): on-site we do not see more than the **official Danfoss app**
> already shows. So validation = **coherence**. If the three views agree — the official app, the
> `danfoss_ally_cloud` entities in HA, and the MQTT we publish — the write/read path is validated.
> Runs as a **dedicated session**: Rémi drives the official app, Claude reads HA state + the MQTT
> broker live (connectors `homeassistant-admin` / `danfoss-ally` / `mqtt`) and confirms agreement.

## 0. Prerequisites (before the session)

- [ ] Integration `danfoss_ally_cloud` **enabled** on the HA host. It is installed but was
      left disabled — re-enable it, confirm the config entry loads (`ha_integrations`).
- [ ] **Distinct deviceId** from the MCP connector in the config entry (coexistence, PR #59) — else
      the two share one Tuya session and invalidate each other. Confirm both the app-side MCP and the
      integration stay logged in.
- [ ] MQTT publishing configured in the options: `mqtt_mode = discovery` **or** `zigbee2mqtt`,
      `mqtt_source = cloud`, `mqtt_base_topic` (default `danfoss_ally_cloud`). Note which mode — it
      changes the topic/field names used below.
- [ ] Mosquitto reachable from the `mqtt` connector (`mqtt_statut`).
- [ ] Pick **one test room / one head** that is easy to watch physically (valve audible/visible).
- [ ] Note the cloud lag: a change takes **a few minutes** to surface (cloud is not real-time).
      Wait and re-read rather than concluding a mismatch.

## 1. Read coherence — the state fields

For the chosen head, read the same value in all three places and tick only if they match
(within rounding and the cloud lag).

| Quantity | Official app | HA entity | MQTT `discovery` field | MQTT `zigbee2mqtt` property |
|---|---|---|---|---|
| Measured temp | room/head temp | `climate` current_temperature · `sensor` temperature | `temperature` | `local_temperature` |
| Setpoint | current setpoint | `climate` target_temperature · `number` comfort/setback | `setpoint` | `occupied_heating_setpoint` |
| Valve / heat demand | valve % (if shown) | `sensor` valve_opening · `climate` hvac_action | `valve_opening` | `pi_heating_demand` + `running_state` |
| Battery | battery % | `sensor` battery | `battery` | `battery` |
| Window open | open-window flag | `binary_sensor` window | `window_open` | `window_open` |
| Online | reachable/online | `binary_sensor` connectivity | availability topic (`online`/`offline`) | `<name>/availability` |
| Fault | fault/error | `sensor` fault | — | — |

**How Claude reads each side during the session**
- HA entities: `danfoss-ally` connector (`danfoss_appareils(recherche=…)`, `danfoss_sante`) and/or
  `homeassistant-admin` (`ha_entite`).
- MQTT: `mqtt` connector — `mqtt_topics` to list, `mqtt_lire` for a retained payload,
  `mqtt_surveiller` to watch live while Rémi acts. Topics:
  - discovery: `danfoss_ally_cloud/<device_id>` (state), `…/<device_id>/availability`.
  - z2m: `danfoss_ally_cloud/<friendly_name>` (state), `…/bridge/devices` (exposes), `…/bridge/state`.

- [ ] **R-1** All seven rows agree on first read (no writes yet).
- [ ] **R-2** Toggle the physical window-open condition (open a window / cool the head) → app flag,
      `binary_sensor` window, and MQTT `window_open` all flip together.
- [ ] **R-3** Let the valve drive heat (or lower setpoint hard) → valve %, `hvac_action`/running_state,
      and `pi_heating_demand` move consistently.

## 2. Write coherence — Claude writes, the app confirms

The true setpoint lever is at **room level** (DP118 / DP109+119 + schedule rewrite), per the
interface contract R1–R7 — not the mode DP (that path was wrong, PR #8). Each write below is done
with the integration's own prepare→(review)→confirm or the HA service, then confirmed in the app.

- [ ] **W-1 Setpoint (comfort / at_home)** — set a new comfort setpoint via HA (`number`
      comfort_setpoint or `set_override`/schedule service). Confirm in the app: new setpoint shows.
      **Check R4**: the room's **weekly schedule is NOT wiped** (open the schedule in the app).
- [ ] **W-2 Setback (leaving_home)** — same for the setback setpoint.
- [ ] **W-3 Child lock (DP30)** — toggle the `switch` child_lock → app child-lock state matches.
      (Only on models in `WRITE_VERIFIED_PRODUCTS`; switch is unavailable otherwise.)
- [ ] **W-4 Window detection (DP116)** — `set_window_detection` / `switch` → app setting matches.
- [ ] **W-5 Return to schedule** — after an override, run the "back to schedule" path (rewrite the
      room schedule, then publish `at_home`, R4/R5). Confirm the app returns to the scheduled
      setpoint and the schedule is intact.
- [ ] **W-6 Vacation / holiday — GATED.** Default OFF (`CONF_ENABLE_VACATION_WRITE = False`). To test:
      enable the option on the config entry first, then `set_vacation` / `set_vacation_at_home` /
      `cancel_vacation` / `end_vacation`. Confirm in the app: holiday/away period appears with the
      right dates and setpoint. **This is the main unvalidated write (CIBLE 2).**

After **every** write: re-read the MQTT state topic and confirm the new value propagated (publishing
is read-only mirror of cloud values, so the write must round-trip cloud → coordinator → MQTT).

- [ ] **W-7** For each of W-1…W-6 that changes a published field, MQTT reflects it after the cloud lag.

## 2b. Unbind (disconnect) — DESTRUCTIVE, GATED (CIBLE 3)

Validates the `disconnect_head` service (`smartlife.m.device.reset` v3.0 `{devId, resetFactory}`)
end-to-end through HA. The cloud call is already validated via the MCP connector (2026-11-18, real
hardware); this confirms the **HA integration** path. **Destructive and irreversible on-site work**:
the sub-device leaves the Zigbee network and must be **physically re-paired** (permit-join is MQTT +
a button press, not drivable from here).

Prereqs (besides section 0):
- [ ] Enable `enable_head_unbind` on the config entry (OFF by default). Confirm the service refuses
      with `unbind_disabled` while it is off.
- [ ] Pick a **disposable test sub-device** you accept to re-pair on site (a single head or a sensor,
      not a production-critical one). The gateway must stay — the service must refuse it.
- [ ] Be **on site**, app available: re-pairing needs a physical action + the app's "Add device". The
      integration's own distinct deviceId (coexistence, PR #59) means the Danfoss app can stay signed
      in during the HA unbind.

- [ ] **U-1 Gates** — `disconnect_head` with a gateway target → `gateway_target`; without `confirm` →
      `confirmation_required`; from a non-admin / user-less (automation) context → `not_admin`;
      nothing is sent in any of these.
- [ ] **U-2 Disconnect (`wipe_data=false`)** — `disconnect_head {target=<test head>, confirm=true}`.
      Confirm: the device leaves the account (gone from the app, from HA, `danfoss_appareil` → 404).
      Re-pair via the app on **its own gateway** → returns by rediscovery with the **same devId/name**
      (heating config back to defaults — reassign its room).
- [ ] **U-3 Sub-device category** — repeat U-2 on a **sensor** (and a relay if available): accepted
      and unbound, confirming a `capteur`/`relais` is handled, not only a head.
- [ ] **U-4 Wipe (`wipe_data=true`), optional** — on a head you accept to re-provision: returns with a
      **NEW devId**, identity/name LOST (irreversible). Rename + reassign the room after re-pairing.

Record the product_id/firmware of each device unbound and whether rediscovery kept the devId.

## 3. Validated on the history curves, not the instantaneous view

- **Preheat (local tunnel, Zigbee 0x0025)** — the cloud *lies*, so the official app's instantaneous
  state will **not** reflect the preheat lever. But it **is observable on the morning curves**: plot
  temperature + `valve_opening` over the early morning and read **when the head starts heating** and
  **whether it starts before its scheduled slot**. That is the validation.
  - [ ] **P-1** Preheat ON (via the `switch`, `enable_local` on + gateway reachable): the valve opens
        / temperature rises **before** the scheduled comfort slot — visible as an earlier ramp.
  - [ ] **P-2** Preheat OFF: heating starts **at** the scheduled slot (no early ramp).
  - [ ] **P-3** The `switch` is **unavailable** when the local tunnel is down (not lying as ON/OFF).
  - Source of the curves: HA history/recorder for `sensor.*_temperature` and `sensor.*_valve_opening`,
    or the retained MQTT state sampled over the morning. Compare the first-heating timestamp to the
    room's scheduled comfort start.
- **`online` vs `update_time`** — availability must follow `online`, not `update_time` (event-driven).
  Spot-check that a head going unreachable flips availability to `offline`.

## 4. Pass / fail

- **Pass** = sections 1 and 2 all ticked (within rounding + cloud lag), schedule never wiped on a
  setpoint write (R4), and section 3 noted.
- On W-6 pass → consider making vacation writes **on by default** (flip `DEFAULT_ENABLE_VACATION_WRITE`)
  and lift the GATED mentions on the 0.6.x in-situ features.
- Section 2b (unbind) is a **separate, destructive pass** — not required for a read/write-coherence
  pass. On U-2/U-3 pass, keep `enable_head_unbind` **off by default** (it stays a deliberate,
  supervised action); just record that the HA unbind path is validated.
- Record results and the firmware/product_id of the test head (cross-install reliability goal).

---

## Session script (what Claude does live)

1. Confirm prerequisites (section 0) via `ha_integrations`, `danfoss_sante`, `mqtt_statut`.
2. Snapshot the chosen head: HA entities + current MQTT retained payload. Print the section-1 table
   filled in.
3. For each R-/W- step: Rémi acts in the app (or asks Claude to issue the HA write), Claude waits the
   cloud lag, re-reads HA + MQTT, and reports match/mismatch.
4. Produce a filled results table + the firmware/product_id note at the end.
