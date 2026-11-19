# First real cloud-MQTT write — supervised procedure (Rémi on site)

The codec, credentials, inbound decoding and an independent live connection are all validated
(docs/cloud-mqtt-publish.md §5–§6, real-hardware probe `rc=0`, coexistence OK). What is NOT yet
proven is that a **publish** over Tuya cloud MQTT actually applies a setting on an isolated head.
This is the one step that writes to real hardware: done once, deliberately, with Rémi present and
ready to revert. **No publish happens before Rémi's explicit go-ahead, at the keyboard, in his
session or the validation session.**

## What the code does now (gated)

- `enable_cloud_mqtt` (options, **OFF by default**) opens a live `CloudMqttLink` from the
  integration's **own** session (its distinct deviceId; coexists with the app — proven). A
  **"Cloud MQTT link"** connectivity binary_sensor shows whether it is connected.
- With the option on and the link connected, an **isolated** head's **child-lock** switch (DP 30)
  routes through MQTT (`write_path: cloud_mqtt`). Only **DP 30** uses this path for now; window
  detection (DP 116) still goes through the tunnel or stays unavailable.
- A toggle **validates the value** (DP 30, boolean) before sending, then **publishes and waits for
  confirmation**: the gateway's inbound protocol-4 `{cid, dps}` frame echoing DP 30, within
  `MQTT_CONFIRM_TIMEOUT` (15 s); on timeout it falls back to a cloud re-read, and if the value still
  differs it raises a **clear error** (never a silent/optimistic success).

## Preconditions

- Test head: an **isolated** head (not grouped into a room) on a `WRITE_VERIFIED_PRODUCTS` model —
  an isolated test head on a verified model. Confirm it is isolated and `online`.
- Note its current child-lock value `V0` (to restore).
- Danfoss iPhone app open on that head's page (to observe; also confirms coexistence).
- Physical access to the head (to read its screen / lock behaviour).
- Deploy commit: the **tip of branch `claude/stoic-lalande-4577d6`** (PR #71, draft), exact SHA given
  with this deliverable, deployed over **`main`** (rc2 or the released 1.1.0). This is the 1.2.0
  gated MQTT work; **never merged to `main` without this validation**.

## Steps

1. **Baseline**: read child-lock in HA and in the app; confirm they agree and the head is `online`.
   Record `V0`.
2. **Arm**: enable `enable_cloud_mqtt` for the entry. The entry reloads; the link connects. Confirm
   the **"Cloud MQTT link"** sensor is `connected`, and the test head's child-lock switch shows
   `write_path: cloud_mqtt`, `write_scope: head`, and is `available`.
3. **Write** `not V0`: toggle the child-lock switch once. The integration publishes one DP-30 frame
   to `smart/mb/out/<gateway>` for this head's `cid` and waits for the confirmation.
   - If the service call **returns without error**, a confirmation (inbound frame or cloud re-read)
     was seen.
   - If it **raises** "write not confirmed", nothing is claimed — treat as not applied.
4. **Observe** (a few seconds; the cloud is not real-time):
   - the Danfoss app shows the new child-lock value;
   - the head itself reflects it (screen / lock behaviour).
   Both must agree with the switch. If the cloud/app flips but the head does not, treat it as **not
   applied** (the W-3 failure mode) and stop.
5. **Restore**: toggle back to `V0`; confirm app + head return to baseline.
6. **Record** in docs/real-validation-results.md: head model, firmware, whether the head physically
   applied it, and that the confirmation path fired. On success, DP 30 for this model may be
   considered validated for the MQTT path.

## Stop criteria (abort and revert immediately)

- The head does not physically reflect the change within ~30 s while the app does → stop; do not
  extend to other DPs or models.
- The switch write **raises** (not confirmed, or publish error) → stop; investigate (link
  connected? sensor shows connected? sid fresh?). The write may or may not have reached the head —
  read the head before retrying.
- Any effect on a head other than the test head → stop; the addressing (`cid`) is wrong.
- The iPhone app gets disconnected when the link connects → stop; re-check the coexistence result.
- Any doubt about reversibility → stop and revert (turn `enable_cloud_mqtt` off; the entry reloads
  and the link closes).

## Scope limits

- Only **DP 30** (child lock) for the first write. Extend to DP 116 (window detection) and others
  **one at a time**, each confirmed on the head, and only then widen `MQTT_WRITE_DPS` /
  `WRITE_VERIFIED_MODELS`.
- Never a setpoint/schedule/mode write on this path in this first pass.
- Turn `enable_cloud_mqtt` off after the session unless keeping it on for a specific supervised head.

## Returning to the released build

Turn `enable_cloud_mqtt` off (the link closes on reload), then redeploy `main` / the released build
over `custom_components/danfoss_ally_cloud/` and restart. Nothing persists except the option value
in the entry, inert without this branch's code.
