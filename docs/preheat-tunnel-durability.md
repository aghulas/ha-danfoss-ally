# Preheat written through the tunnel alone does not survive the night

Status: **read-only finding of 2026-11-20, one night, one building.** No write was made for this
note. It changes what the preheat switch can claim: the tunnel write of attribute `0x0025` is
applied and read back, but **it is not durable** while the cloud holds another value. A change plan
follows; nothing in the code has changed yet.

## What was observed

Sources: Home Assistant history of the integration's preheat switches (fed by the tunnel survey
only), of the public-API preheat switches of the other Danfoss integration installed on the same
Home Assistant (the cloud's DP 1), of the valves and of the gateways' connectivity; the write
journals of the Home Assistant admin connector and of the MCP connector (cloud and local).

Four heads had bit 1 of `0x0025` changed on 2026-11-19 while the cloud's DP 1 kept its value. All
four were back at the cloud's value before the next morning, with no write from our side.

| Head | Change on 2026-11-19 | By | Cloud DP 1, whole period | Last read at the new value | First read back at the old value |
|---|---|---|---|---|---|
| P1 (classroom) | ON → OFF, 10:58 | preheat switch, tunnel | on | 23:39 (reload), then every pass | 04:54:52 |
| P2 (service room) | OFF → ON, 10:58 | preheat switch, tunnel | off | 23:39, then every pass | 04:55:02 |
| P3 (technical room) | ON → OFF, seen 22:04 | **not** a preheat write, see below | on | 23:39, then every pass | 04:04:37 |
| P4 (technical room) | ON → OFF, seen 21:40 (ON 21:56, OFF 22:04) | **not** a preheat write, see below | on | 23:39, then every pass | 04:54:14 |

- **The 94 other preheat switches did not flip** between 23:40 and 08:30 (some went unavailable and
  came back with the same value).
- **Nothing of ours wrote that night.** The admin connector's journal has no call between 23:41
  (a room setpoint, another building) and 08:30; the MCP connector's journals (cloud and local)
  have no entry on 2026-11-19 or 20. The integration has no timed job that writes a head.
- **The morning curves follow the reverted values**: P1 (back to ON) opened its valve at 07:12,
  78 min before its slot, and the cloud's "pre-heating" flag went on at 07:14; P2 (back to OFF)
  opened at 08:35, slot + 5 min, with no flag.
- P3 and P4 were not written by the preheat switch. Their bit changed during an evening of
  schedule and override service calls on one isolated head of that floor (21:40–22:02, release
  validation). Which call cleared the bit, and why P3 moved at all, is **not established**; the
  integration's own code writes `0x0025` only in `write_preheat`. They count here for one thing:
  a head whose bit 1 differs from the cloud's DP 1 was brought back to the cloud's value.

## When, and what was not seen

- The survey reads every head about every 16 min; a head that does not answer makes its switch
  unavailable, which the history records. A silent pass is therefore an unchanged read. That
  bounds the reverts: P3 between about 03:48 and 04:04; P1, P2 and P4 between about 04:38 and
  04:54. **Not one instant for all**, and not a fixed delay after the write (about 17 h 40 for P1
  and P2, 6 to 7 h for P3 and P4).
- The three gateways of the building stayed connected (cloud flag) all night. No other entity of
  the four heads changed in the hour around the reverts (valve, setpoint, window, cloud flags).
- **The sender and the frames were not observed.** No cloud-MQTT listen ran that night, and the
  Home Assistant core log of the night was not read (the instance was restarted at 09:27). "The
  gateway or the cloud re-imposes the cloud's value" is the reading that fits; whether it is a
  nightly job, the preparation of the day's schedule, or the head's own check-in is unknown.
- Which cloud store is re-imposed is unknown too: the public DP 1 and the app's settings block
  held the same (original) value on all four heads. On the morning's trial head (stage B of
  `docs/cloud-mqtt-preheat-proposal.md`) the two differed for 17 minutes only.
- The revert does not need a comfort slot or a heat demand: P3 has a flat frost-protection
  schedule (read through the tunnel on 2026-11-20, no slot on any day) and reverted like the
  others. All four heads are isolated ones, on two gateways.
- One night, one building, one firmware. Reverts on a night before a day without school, and on
  heads in a room, have not been looked at.

## Conclusion

On this evidence, **no: a preheat write made through the local tunnel alone does not hold.** Four
heads out of four, both directions, came back to the cloud's value within one night, and no head
whose two values agreed moved. The tunnel remains the only source that tells the head's real
preheat, and the only write seen to change it at once; it is not a complete write.

Consequence for what is already documented: the validation of 2026-11-19 ("written, read back,
still in place 6 min later") stands for the write itself, not for its durability.

## Change plan (not coded)

1. **Show the divergence first** (read-only, can ship alone). The switch keeps showing what the
   tunnel reads. When the cloud's DP 1 for that head differs from it, say so: an attribute on the
   switch (`cloud_value`, `cloud_aligned: false`) and a line in the diagnostics. A divergence is,
   on the evidence above, a revert to come.
2. **Make the write a pair**: tunnel write of `0x0025` and read-back as today, then align the
   cloud with what the head now says —
   - isolated head: the DP 1 publish over cloud MQTT (stage B: it changes the cloud's DP 1 and
     leaves the head alone) and the settings block through `settings.change`, the two calls
     `async_mqtt_write_preheat` already makes after PR 109;
   - head in a room: the room publish of DP 1 (contract §4.2), which applies to the whole room —
     to be decided whether a per-head preheat switch still makes sense there.
3. **Never a silent half-write.** If the alignment cannot be sent or is refused, the call fails
   with "applied on the head, cloud not aligned, expected to revert", and the divergence of point 1
   stays visible. The state shown never comes from the cloud.
4. The alignment over cloud MQTT needs `enable_cloud_mqtt`; without it only the HTTP block can be
   posted. Whether the block alone is enough decides what an install without cloud MQTT can offer.

## To prove on real hardware before the switch changes

- **A1 — the pair holds overnight.** Two isolated heads, same night (heads on a flat schedule
  will do, since one of those reverted):
  a control written through the tunnel alone (expected to revert) and a head written through the
  tunnel and then aligned. Read both through the tunnel the next morning. Without the control, a
  value that held proves nothing (the night may simply have had no revert).
- **A2 — which alignment is needed**: the MQTT publish alone, the settings block alone, or both.
  One more night per variant, or accept "both" if A1 passes.
- **A3 — the alignment leaves the head alone**: `0x0025` (both bits), setpoints and schedule read
  through the tunnel before and after; the settings block is posted with the current setpoints.
- **A4 — rooms**: the room publish of DP 1 on a test room, read back on each head.
- **A5 — another gateway and another night**, before the wording "validated" comes back.
- If possible during A1, a cloud-MQTT listen on the control head's gateway around 03:30–05:30, to
  see what is sent to the head when it reverts.

## Trial A1, started 2026-11-20 (result due the next morning)

Two isolated heads on the same gateway, both on a flat frost-protection schedule (no heat demand,
nobody relies on them), build 1.2.1-rc1. Each write was previewed and approved by the owner.

**Aligned head T — written by the pair alone.** DP 1 armed on T (10:25), `switch.turn_on` at
10:29:26: the DP 1 publish over cloud MQTT, then the settings block through `settings.change`
(`async_mqtt_write_preheat`). The call returned without error after 50 s, so the tunnel read
showed the value within that time. **No tunnel write was made on T.** Disarmed at 10:31; options
back at rest.

| T | Before (10:22) | After (10:31–10:33) |
|---|---|---|
| `0x0025` raw (tunnel) | 1 | **3** (bit 0 kept) |
| Weekly schedule, current setpoint (tunnel) | flat 5 °C, 5 | unchanged |
| Cloud DP 1 (per-device route) | false | **true** |
| Preheat switch | off | on, still on after the reload of the disarm |

This is the first pass of the second trial design of `docs/cloud-mqtt-preheat-proposal.md`: the
publish **with** the block makes the head take the value, where the bare publish did not. One
head, one direction (OFF to ON). Not read: cloud DP 172, the frames (no MQTT listen), the exact
delay.

**Control head C — tunnel only.** `switch.turn_off` on its preheat switch at 10:32:23 (2.6 s).

| C | Before (10:19) | After (10:33) |
|---|---|---|
| `0x0025` raw (tunnel) | 3 | **1** (bit 0 kept) |
| Weekly schedule, current setpoint (tunnel) | flat 5 °C, 5 | unchanged |
| Cloud DP 1 (per-device route) | true | **true** (not touched) |
| Preheat switch | on | off |

C is the head called P3 above: it reverted last night in this same situation. Its cloud record
disagrees with the head on more than preheat (the cloud shows manual mode and 21 °C, the head runs
its flat schedule at 5 °C); that was already so last night.

Expected the next morning, read through the tunnel: **C back at 3** (reverted to the cloud's
value), **T still at 3**. If C has not reverted, the night proves nothing (it precedes a day
without school) and the trial is to be repeated. T at 3 only shows that an aligned head is not
disturbed; it cannot show a revert that was avoided, since T was not written through the tunnel.
After the reading, C is to be put back to ON and T to OFF, or left, at the owner's choice.

## Docs that overstate the tunnel route today

- `docs/architecture.md`: "reachable only through the local tunnel" as if that write were
  complete; routing table row "Preheat"; "The tunnel stays the only preheat route".
- `docs/cloud-mqtt-preheat-proposal.md`: "the path the preheat switch uses today, validated on
  real hardware"; "The tunnel remains the only proven preheat route"; the assessment ("the tunnel
  already writes preheat directly").
- `custom_components/danfoss_ally_cloud/switch.py`, `DanfossPreheat` docstring: "Writing 0x0025
  is validated on real hardware (2026-11-19)".
- `CLAUDE.md` ("the real lever is the Zigbee attribute 0x0025"), `README.md`, `CHANGELOG.md`
  (1.1.0: "write of attribute 0x0025 (validated on real hardware)"), `docs/roadmap.md`,
  `docs/real-validation-plan.md` (P-1/P-2 assume a switch write that lasts until the morning).

The first two carry a pointer to this note; the others are left for the change that implements
the plan.
