# Preheat — field findings and the closed cloud-MQTT candidate

What is established on real hardware about preheat, what is not, and what is left to do. Trial
records: `docs/validation/2026-11-preheat-curves.md` (morning curves, P-1 to P-3),
`docs/validation/2026-11-real-hardware-validation.md` (switch writes and the night read-out) and
`docs/validation/2026-11-preheat-dp1-pair.md` (publish + settings block). Trial sheet for DP 1:
`docs/first-write-procedure.md`, "DP 1 — preheat".

## Summary

| Question | Answer | Evidence |
|---|---|---|
| Where is the head's real preheat? | Bit 1 of Zigbee attribute `0x0025` (bit 0 = schedule; 0 = manual). Read and written through the local tunnel | 2026-11-19, read back at once |
| Does preheat ON make the head heat ahead of its slot? | Yes: valve open 52 to 448 min before the slot, median about 4 h 10 (70 heads). OFF: opening at the slot | Morning curves of 2026-11-19 |
| Does cloud DP 1 over HTTP reach the head? | No: it changes the gateway cache only | Earlier field incident; reproduced over MQTT (stage B) |
| Does a bare DP 1 publish over cloud MQTT reach the head? | **No** (stage B, 2026-11-20) | Head unchanged 15 min later, cloud DP 1 changed |
| Does the DP 1 publish **followed by the settings block** reach it? | Yes, once: one head, OFF to ON, in under a minute | 2026-11-20, build of the abandoned 1.2.1 line |
| Does a tunnel-only write last? | **No**: the head goes back overnight to the value the cloud holds | Night of 2026-11-19, 3 heads (a 4th is doubtful) |
| Do other tunnel-only settings revert too? | Not the one tried: a valve exercise day held one night on one head | 2026-11-21 |

Consequences in the code today:

- The preheat switch reads the tunnel only and never shows the cloud's DP 1. Without a tunnel
  answer for a head, its switch is unavailable.
- The switch writes `0x0025` through the tunnel and reads it back. That write is real and
  immediate, **but not durable** while the cloud's DP 1 holds the other value.
- DP 1 over cloud MQTT is a **closed candidate** (`api.writes.MQTT_CANDIDATE_DPS`): nothing is sent
  unless DP 1 is listed in `cloud_mqtt_supervised_dps` for the head of `cloud_mqtt_supervised_head`.
  Owner's decision (2026-11-20): keep it closed, do not remove it, do not promote it.

## Why the echo and the cloud confirm nothing for DP 1

The gateway's echo and the per-device cloud read can both say "true" from the cache while the head
has not changed. A DP 1 write is trusted only if **`0x0025` read through the tunnel** shows it
(`MQTT_TUNNEL_CONFIRMED_DPS`). Stage A showed it directly: for some tens of seconds the cloud's
DP 1 ran ahead of the head, both ways.

## The cloud-MQTT candidate (2026-11-20, one isolated head, flat 5 °C schedule)

**Stage A — the app's toggle reaches the head.** The owner toggled preheat in the Danfoss app; this
side only read.

| Instant | `0x0025` raw (tunnel) | cloud DP 1 | cloud DP 172 (preheat) |
|---|---|---|---|
| baseline | 1 | false | off |
| toggle ON, about +20 s | 1 | **true** | off |
| about +1 min | **3** | true | **on** |
| +5 min, +15 min | 3 | true | on |
| toggle OFF, about +20 s | 3 | **false** | on |
| about +1 min | **1** | false | **off** |

Bit 1 followed within a minute, both ways; bit 0 never moved; nothing else changed on the head.
Cloud DP 172 moved with the head, not with DP 1.

**Stage B — the integration's bare publish does not.** One `{"1": true}` frame over cloud MQTT:
cloud DP 1 true at +1 min and still at +15 min, `0x0025` unchanged at 1, DP 172 off. The call
raised "not confirmed" after 61 s, as designed, and the switch never showed the value. Afterwards
the app's toggle showed OFF, in step with the head: the app does not display that DP 1. The cache
was put back by a round trip in the app.

**What the app's toggle triggers** (read-only cloud-MQTT listen the same day): within 2 s the
gateway reports DP 1, then a run of ZCL Default Responses to thermostat command `0x01` (Set Weekly
Schedule) comes back through the tunnel (DP 199), then the head reports DP 172 with the new bit.
Something on the cloud side reprograms the head; a bare DP 1 publish does not trigger it. The
app's own outbound frames and HTTP calls for this toggle were not captured.

**The pair — publish, then the settings block.** `mqtt_write.async_mqtt_write_preheat` now sends
the DP 1 frame, then `settings.change` with the whole block `{"1", "118", "119", "121"}`, and
waits up to 120 s for the tunnel to show bit 1. Run once on the same kind of head: `0x0025` went
1 → 3 inside the 50 s call, bit 0 kept, schedule and setpoint unchanged, no tunnel write. Not
tried: the block alone, the reverse direction, another head.

How the trial write behaves (unchanged): the head is read through the tunnel before anything goes
out (no answer or already at the value: nothing is sent); while DP 1 is armed on the trial head
the tunnel never writes that head's preheat, so a result cannot be credited to the wrong channel;
the code checks bit 1 only, not bit 0 nor the cloud's DP 1 / DP 172.

## A tunnel-only write does not survive the night (read-only finding, 2026-11-20)

Heads whose `0x0025` bit 1 differed from the cloud's DP 1 on the evening of 2026-11-19:

| Head | Change on 2026-11-19 | Cloud DP 1 | Back at the cloud's value |
|---|---|---|---|
| P1 | ON → OFF, 10:58, preheat switch (tunnel) | on | between 04:38 and 04:54 |
| P2 | OFF → ON, 10:58, preheat switch (tunnel) | off | between 04:38 and 04:54 |
| P3 | ON → OFF seen 22:04, not a preheat write, unexplained | on | between 03:48 and 04:04 |
| P4 | ON → OFF seen 21:40, not a preheat write | on | between 04:38 and 04:54 |

- The 94 other preheat switches did not flip that night, and nothing of ours wrote: no call in
  the connectors' journals, no timed job in the integration.
- The morning curves followed the reverted values (P1 opened 78 min before its slot, P2 at the
  slot + 5 min).
- Not one instant for all, and not a fixed delay after the write. The gateways stayed connected.
  P3 has a flat frost-protection schedule: the revert needs neither a comfort slot nor a heat
  demand.
- **P4 is doubtful evidence.** It is probably the head of that evening's schedule trial, whose
  bit followed its changes of mode (manual clears the whole attribute; the head later settles
  back to mode 3 with preheat on by itself). See `docs/isolated-head-schedule-writes.md`. The
  finding rests on P1 and P2, and on P3, unexplained.
- **The sender and the frames were not observed** (no cloud-MQTT listen ran that night). "The
  gateway or the cloud re-imposes the cloud's value" is the reading that fits; which store, and
  on what trigger, is unknown. One night, one building, one firmware, isolated heads only.

## Change plan for the preheat switch (not coded)

1. **Show the divergence** (read-only, can ship alone): when the cloud's DP 1 differs from what
   the tunnel reads, say so on the switch (`cloud_value`, `cloud_aligned: false`) and in the
   diagnostics. A divergence is, on the evidence above, a revert to come.
2. **Make the write a pair**: tunnel write and read-back as today, then align the cloud — for an
   isolated head, the DP 1 publish and the settings block; for a head in a room, the room publish
   of DP 1 (which applies to the whole room: decide whether a per-head switch still makes sense).
3. **Never a silent half-write**: if the alignment cannot be sent, the call fails with "applied on
   the head, cloud not aligned, expected to revert". The state shown never comes from the cloud.
4. The alignment over cloud MQTT needs `enable_cloud_mqtt`; whether the HTTP block alone is enough
   decides what an install without it can offer.

## To prove on real hardware first

- **A1 — the pair holds overnight.** Concluded on real hardware (2026-11-24/25, record:
  [`docs/validation/2026-11-preheat-trial-a1.md`](validation/2026-11-preheat-trial-a1.md)). Both the
  control head (`C-0 Sanitaires Filles`) and the aligned head (`C-0 Sanitaire Garçons`) held
  `pre_chauffage: false` (attribute `0x0025` bit 1 = 0) through the 03:53 nocturnal sync window.
  Major discovery: writing the tunnel causes the gateway to autonomously push an upstream Tuya
  `{"1": false}` report to the cloud (captured at 19:57:26 on `smart/mb/in/<gw>`), keeping the
  cloud cache aligned.
- **A2 — which alignment is needed**: the publish alone, the block alone, or both.
- **A3 — the alignment leaves the head alone**: both bits of `0x0025`, setpoints and schedule
  read through the tunnel before and after.
- **A4 — rooms**: the room publish of DP 1 on a test room, read back on each head.
- **A5 — another gateway and another night**, before the word "validated" comes back.
- If possible during A1, a cloud-MQTT listen on the control head's gateway around 03:30–05:30, to
  see what is sent when it reverts.

## Preheat on MQTT-companion / danfoss2mqtt heads — unavailable, and why (2026-11-23)

A head reached through the v2.x **Companion** (subscribing to `zigbee2mqtt` / `danfoss2mqtt`) has
**no preheat switch**, and this is **by design**, not a missing feature. Confirmed in code:

- The preheat switch (`switch.DanfossPreheat`) is created only when the entry owns a **local
  tunnel** coordinator (`async_setup_entry`: `if local is not None`, then `dev.mesh_id in gws`). A
  Companion entry (`_async_setup_companion_entry`) builds its store from the MQTT bridges alone
  (`companion_adapter.build_companion_store`): it holds **no `DATA_LOCAL`**, no `DATA_MQTT_LINK`,
  and no supervised-trial options. So the preheat block is skipped for **every** companion head,
  `zigbee2mqtt` and `danfoss2mqtt` alike.
- `danfoss2mqtt` heads additionally carry **no `mesh_id`** (`z2m_contract.decode_z2m_descriptor`
  leaves it `None` unless the bridge metadata sets it), so even the `mesh_id in gws` guard would
  exclude them — but the `local is None` check already settles it.
- The supervised **DP 1 cloud-MQTT trial** cannot run on such a head: it publishes over the
  integration's **own** `CloudMqttLink` (`can_publish(mesh_id)` — needs a `mesh_id`) and is
  confirmed by the **local-tunnel** read-back alone (`MQTT_TUNNEL_CONFIRMED_DPS`, `mqtt_write`).
  A companion head has neither link nor tunnel, so arming the trial there would be unroutable and
  unconfirmable. **A DP 1 preheat trial can only be armed from a direct-cloud (1.4.x-style)
  entry** on an isolated head the integration reaches through its own tunnel + dedicated cloud
  MQTT — exactly the P-series heads above.

This respects the project rule "the entity is absent rather than lying": with no proven write path
behind it, no preheat switch is offered. The absence is made **explicit** (not silent) through the
`preheat` block of the config-entry diagnostics (`companion_mode`, `switch_exposed`, `reason`).

Preheat on a companion head, where a lever exists at all, is the bridge's business: the
`programming_operation_mode` command of the per-device contract (`companion-contract.md` §2.3),
honoured by the bridge that owns the head. The autonomous `danfoss2mqtt` cloud bridge declines it
for an isolated head today (see `docs/z2m-cloud-parity.md`).

## Assessment of the cloud-MQTT route

The tunnel is needed to confirm a DP 1 write, and the tunnel already writes preheat directly: a
cloud-MQTT route makes preheat available on no head that lacks it today. Its value is as the
**alignment half of the pair** above, not as a route of its own. Promotion, if any, is a change of
its own after A1 to A5.
