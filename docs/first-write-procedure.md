# First real cloud-MQTT write — supervised procedure (Rémi on site)

The codec, credentials and decoder are validated (docs/cloud-mqtt-publish.md §5–§6); what is NOT
yet proven is that a **publish** over Tuya cloud MQTT actually applies a setting on an isolated head.
This is the one step that writes to real hardware, so it is done once, deliberately, with Rémi
present and ready to revert. **No publish happens before Rémi says go, in this session.**

## Preconditions

- A head that is **isolated** (not grouped into a room) and on a `WRITE_VERIFIED_PRODUCTS` model —
  so the only plausible paths are MQTT (this test) or the local tunnel.
- Choose the **least consequential, reversible DP**: **DP 30 (child lock)**. It is a comfort toggle,
  instantly reversible, and visible both in the Danfoss app and on the head's screen. Do **not** use
  a setpoint/mode DP for the first write.
- The integration drives MQTT from its **own dedicated session** (dedicated deviceId,
  `RD_DEVICE_ID_MARKER`), so the write cannot disturb the app, the iPhone app or the MCP connector.
- Note the head's current child-lock state (to restore it).
- Have the Danfoss app open on the head's page (to observe), and physical access to the head.

## Steps

1. **Baseline**: read the head's child-lock in HA and in the app; confirm they agree and the head is
   `online`. Record the value `V0`.
2. **Arm**: enable the experimental option (`enable_cloud_mqtt`, OFF by default) for this entry, and
   bring up the dedicated-session MQTT link (the gated connect — a separate, explicit step; it only
   connects + subscribes, it does not publish on its own). Confirm the child-lock switch for the
   isolated head is now `available` with `write_path: cloud_mqtt`, `write_scope: head`.
3. **Write** `not V0`: toggle the switch once. The integration publishes one DP-30 frame to
   `smart/mb/out/<gateway>` for that head's `cid`. No optimistic state is set.
4. **Observe** (allow a few seconds; the cloud is not real-time):
   - the gateway should answer with a protocol-4 DP report on `smart/mb/in/<gateway>` echoing
     `{"dps": {"30": <new>}}` for this `cid` (the inbound frames already decode — §6.3);
   - the Danfoss app should show the new child-lock value;
   - the head itself (screen / physical lock behaviour) should reflect it.
   All three must agree. If only the cloud/app flips but the head does not, treat it as **not
   applied** (the W-3 failure mode) and stop.
5. **Restore**: toggle back to `V0`; confirm app + head return to baseline.
6. **Record** in docs/cloud-mqtt-publish.md: head model, firmware, whether the head physically
   applied it, and the observed ack frame. On success, the model may be considered for
   `WRITE_VERIFIED_MODELS` for the MQTT path (value validation before send still applies).

## Stop criteria (abort and revert immediately)

- The head does not physically reflect the change within ~30 s while the app does (cloud lie) →
  stop, do not extend to other DPs or models.
- CONNACK is refused (`rc != 0`), or the publish raises → stop; the write did not go out. Re-check
  the session (a stale/rotated `sid` is the known cause) before retrying.
- Any effect on a head other than the target (e.g. a second head reacts) → stop; the addressing
  (`cid`) is wrong.
- Any doubt about reversibility → stop and revert.

## Scope limits

- Only DP 30 for the first write; extend to DP 116 (window detection) and others **one at a time**,
  each confirmed on the head, before adding a model to `WRITE_VERIFIED_MODELS`.
- Never a setpoint/schedule/mode write in this first supervised pass.
- Disable `enable_cloud_mqtt` again after the session unless the feature is being kept on for a
  specific head under observation.
