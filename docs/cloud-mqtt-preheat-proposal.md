# Preheat over Tuya cloud MQTT (DP 1) — closed candidate, stage A positive, stage B failed

Status: **candidate, closed, not to be promoted as it stands.** Two observations on 2026-11-20, on
the same isolated head, 25 minutes apart:

- **Stage A, positive**: the Danfoss app's toggle reaches the head. Bit 1 of `0x0025` followed
  within a minute, both ways, bit 0 kept.
- **Stage B, failed**: the integration's own publish of `{"1": true}` over cloud MQTT changed the
  cloud's DP 1 and **nothing on the head**, 15 minutes later still. The write raised "not
  confirmed", as designed; the preheat switch never showed the value.

So whatever the app does to switch preheat on an isolated head, a bare DP 1 publish over cloud MQTT
is not it, or not all of it. **Why is not known.** DP 1 stays in `api.writes.MQTT_CANDIDATE_DPS`
(closed: nothing is written unless it is listed in `cloud_mqtt_supervised_dps` for the head of
`cloud_mqtt_supervised_head`). Owner's decision (2026-11-20): **keep it as a closed candidate** in
1.2.0, not remove it. Arming it as it stands can only reproduce stage B. The tunnel remains the
only proven preheat route. Sheet:
`docs/first-write-procedure.md`, "DP 1 — preheat".

**Later the same day**: the tunnel route is proven for the write, not for its durability. Four
heads whose `0x0025` bit differed from the cloud's DP 1 went back to the cloud's value within one
night (`docs/preheat-tunnel-durability.md`). This changes the assessment at the end of this page:
the cloud's value is not a side matter, and the two calls of the second trial design (the DP 1
publish and the settings block) are the first candidates to align it after a tunnel write.

## Why this DP is last

Preheat is the known trap of this integration (`docs/architecture.md`):

- over **HTTP**, writing DP 1 changed the gateway's cache and nothing else: the cloud showed the
  new value while the head's real preheat did not move;
- the head's real preheat is **bit 1 of Zigbee attribute `0x0025`** (programming operation mode),
  readable and writable only through the local tunnel — the path the preheat switch uses today,
  validated on real hardware for the write and its read-back, not for its durability
  (`docs/preheat-tunnel-durability.md`);
- the app does publish `{"1": bool}` over cloud MQTT for an isolated head (contract §4.2), and also
  posts DP 1 in its settings block over HTTP.

So for DP 1, every confirmation the other DPs rely on is worthless: the gateway's echo and the
per-device cloud read can both say "true" from the cache while the head has not changed. A DP 1
write over cloud MQTT is trusted only if **attribute `0x0025` read through the tunnel** shows it.

## What is not known

1. Whether a cloud-MQTT `{"1": bool}` publish changes bit 1 of `0x0025` on the head at all, or only
   the gateway cache, as over HTTP.
2. If it does, after how long, and whether bit 0 (schedule) is preserved.
3. Whether the gateway's echo of DP 1 means anything (it may come from the cache).
4. What the cloud's DP 1 and DP 172 (the mirror of `0x0025`) show afterwards, and when.

## Observation (stage A) as it was proposed

Nothing to build: the publish can be done from the app itself, which is the reference.

1. Isolated test head, online, tunnel answering. Read `0x0025` through the tunnel: `V0` (note both
   bits). Read the cloud's DP 1 and DP 172.
2. In the **Danfoss app**, toggle preheat on that head (the app publishes `{"1": …}` over MQTT).
3. Read `0x0025` through the tunnel at about 20 s, 1 min, 5 min and 15 min. Read cloud DP 1 and
   DP 172 at the same instants.
4. Toggle back in the app; read again.

Outcomes:

- **Bit 1 of `0x0025` follows** the app's toggle, bit 0 preserved → the MQTT publish is a real
  lever. Go to "Implementation" below.
- **Bit 1 does not move** while the cloud's DP 1 does → cloud MQTT is as blind as HTTP for preheat.
  Record it and close the question: the tunnel stays the only route, and DP 1 is never added to
  this channel.
- **Bit 1 moves only after minutes** → usable only if the delay is bounded and the entity stays
  unavailable or unchanged until the tunnel shows it; probably not worth a second route.

This observation changes a setting on a real head (through the app): it is the owner's to do, like
any supervised write.

## Stage A result (2026-11-20)

One isolated head on the verified model, online, in a room nobody relies on (flat 5 °C schedule,
valve closed, no heat demand throughout). The owner toggled preheat in the Danfoss app; this side
only read. Sources: raw `0x0025` through the local tunnel; cloud DP 1 through the public
per-device route (`switch`); cloud DP 172 through the app API's device read (decoded preheat
flag — whether that read is per-device or the bulk list was not checked, so its timing is
indicative). Times are the read times; a tunnel read takes about 8 s.

| Instant | `0x0025` raw (tunnel) | bit 1 | bit 0 | cloud DP 1 | cloud DP 172 (preheat) |
|---|---|---|---|---|---|
| baseline, 08:37 (read twice) | 1 | 0 | 1 | false | off |
| toggle ON in the app, reported just before the next read | | | | | |
| about +20 s (08:38:48) | 1 | 0 | 1 | **true** | off |
| about +1 min (08:39:34–46) | **3** | **1** | 1 | true | **on** |
| about +5 min (08:43:45) | 3 | 1 | 1 | true | on |
| about +15 min (08:53:35) | 3 | 1 | 1 | true | on |
| toggle OFF in the app, reported just before the next read | | | | | |
| about +20 s (08:54:40) | 3 | 1 | 1 | **false** | on |
| about +1 min (08:55:43) | **1** | **0** | 1 | false | **off** |

Reading:

- **Positive.** Bit 1 followed the app's toggle between about 20 s and 1 min, in both directions;
  bit 0 never moved; the value held for 15 min; the head ended at its baseline (`0x0025` = 1).
  Nothing else on the head changed (setpoints, schedule, window detection).
- **Cloud DP 1 runs ahead of the head**: at +20 s, both ways, the cloud already showed the new
  value while the head still had the old one. This is the reason the echo and the cloud read are
  refused as confirmation, observed directly: for some tens of seconds they would have confirmed
  a write the head had not applied.
- **Cloud DP 172 moved with the head**, not with DP 1 — consistent with it being a report from
  the head.
- The 60 s confirmation window of `async_mqtt_write_preheat` (a tunnel read every 10 s) covers the
  delay seen here, with little margin: one head, two toggles. Stage B should record the delay.
- Limits: one head, one gateway, one firmware; the publisher was the app, not the integration
  (see stage B below for the integration's own publish).

## Stage B result (2026-11-20)

Same head, build 1.2.0-rc4, trial armed on that head only (`enable_cloud_mqtt` on, DP 1 listed).
After arming: the head's preheat switch showed `write_path: cloud_mqtt`, `write_trial: true`, the
preheat switch of another isolated head `write_path: local`. One write, `switch.turn_on`, at
09:00:39.

| Instant | `0x0025` raw (tunnel) | cloud DP 1 | cloud DP 172 (preheat) | switch in Home Assistant |
|---|---|---|---|---|
| before, 09:00 | 1 | false | off | off |
| about +1 min (09:01:54) | 1 | **true** | off | off |
| about +5 min (09:05:41) | 1 | true | off | off |
| about +15 min (09:15:34) | 1 | true | off | off |

- The call failed at 09:01:41 with "cloud-MQTT preheat write not confirmed: the frame was sent,
  and 61 s later the head's attribute 0x0025 [...] does not show the value". No retry, no other
  write. Whether the gateway echoed the DP was not looked at (the code does not listen to it).
- **Not passed.** The head never applied the value; the cloud's DP 1 took it at once and kept it.
  This is the HTTP failure, reproduced over cloud MQTT by the integration's frame — and the case
  the tunnel-only confirmation exists for: an echo or a cloud read would have reported success.
- **The app's toggle showed OFF afterwards**, in step with the head, while the public API's DP 1
  said `true`. The app's preheat toggle therefore does not display that DP 1, and the sheet's
  resync step ("set the app's toggle to the head's value") had nothing to do as written. The
  owner then did a round trip in the app (ON, then OFF) between 09:16 and 09:18; at 09:18:52 the
  public API's DP 1 was back to `false` and the head at `0x0025` = 1 (read again at 09:19:24, with
  DP 172 off). The intermediate ON was not read.
- The trial was disarmed at 09:17; the options are back at rest. Nothing else changed on the head
  or on any other head.
- Open question: what differs between the app's toggle and the integration's publish. Not
  investigated. First lead, **not verified**: the app capture (interface contract §4.2) shows that
  for preheat the app sends `settings.change` over HTTP with the whole settings block **in
  addition** to the MQTT publish; the integration sent the MQTT frame alone. That HTTP call alone
  is known not to write the head, but the pair was never tried from the integration. Other
  possibilities: other DPs in the same frame, an ordering or timing condition.

## Why the app's toggle works and the bare publish does not (2026-11-20, later)

Desk review, then one read-only observation on the same head.

**Desk review.**

- The integration's DP 1 frame has the same format, addressing and protocol as the frames of the
  proven DPs (30, 116, 18, 27, 120, 118 + 16, 119), which the head applies; only the payload
  differs. In stage B the gateway did take it (the cloud's DP 1 changed). The wire format is not
  the suspect.
- The raw record behind "the app toggles preheat with `publishDps({"1": bool})`" (contract §4.2)
  could not be found again. The HTTP capture of the same day is at hand: for the isolated head it
  holds five `settings.change` calls, **all with `"1": true`** — setpoint changes, no preheat
  toggle. What the app sends for preheat on an isolated head is therefore not backed by evidence
  that can be re-read today.

**Observation**: cloud-MQTT listen on the gateway's inbound topic (the MCP connector's own
session; counts and last value per DP, no frame list), while the owner toggled preheat in the
app, ON then OFF. The head was read through the tunnel during the ON phase and **not at all**
during the OFF phase, so that tunnel traffic seen then could not be this side's.

| Phase | Reported by the gateway for the head | Head (`0x0025`, tunnel) |
|---|---|---|
| ON (51 s of listening) | DP 1 = true within 2 s; DP 172 = 3; DP 111 ×3; DP 199 ×32 (this side's two tunnel reads are among them) | 1, then 3 about 40 s after the toggle |
| OFF (59 s, no tunnel read from this side) | DP 1 = false; DP 172 = 1; **DP 199 ×12** | 1 (read after the listen) |

The DP 199 frames of the OFF phase (the Zigbee tunnel's answers), as far as the tool shows them
(the last value at three instants): first a Poll Control check-in (cluster 0x0020, command 0),
then ZCL **Default Responses with status success to cluster-specific command 0x01 of the
thermostat cluster**, with consecutive sequence numbers (0x0f … 0x13 seen). Command 0x01 of that
cluster, client to server, is Set Weekly Schedule.

Reading:

- After the app's toggle, **something sends the head a run of Set Weekly Schedule commands
  through the Zigbee tunnel**, and the head then reports DP 172 with the new preheat bit. The
  integration does not write schedules on its own and this side sent nothing: the sender is the
  cloud (or the app through it). Who exactly, and on which call of the app, was **not** observed.
- That is the difference with stage B: a bare DP 1 publish changes the cloud's DP 1 and triggers
  no reprogramming of the head. It also matches what is established for rooms (R3: a setting is
  only carried into the head by a schedule rewrite).
- Still unknown: the app's outbound MQTT frames and its HTTP calls for this toggle (first
  suspect: `settings.change` with the whole block, which the app posts for the settings of that
  block, and/or a save of the weekly schedule); the complete list of tunnel frames (whether one of
  them writes `0x0025`); whether the same happens on another head or firmware.
- Next trial, **coded, not run**: publish DP 1 **and** post the settings block with DP 1
  changed, as the integration already does for the setpoints of that block, under the same
  tunnel-only confirmation (`mqtt_write.async_mqtt_write_preheat`; confirmation window raised
  from 60 to 120 s). If that is not enough, a capture of the app (emulator) is the way to see
  what it really sends.

## Implementation (shipped closed; used only if the observation is positive)

- DP 1 is a candidate (`MQTT_CANDIDATE_DPS`), boolean, and the one member of
  `MQTT_TUNNEL_CONFIRMED_DPS`: the DPs the gateway's echo and the cloud read cannot confirm.
- The preheat switch keeps the **tunnel as its only source of state**. It never shows the cloud's
  DP 1. Without a tunnel there is **no preheat switch**, exactly as before.
- Routing: the tunnel writes preheat, always, except on the designated trial head while DP 1 is
  armed (`enable_cloud_mqtt` on, DP 1 listed, isolated head on a verified model). There the write
  goes out over cloud MQTT **only**: the tunnel never writes that head's preheat during the trial,
  and with the link down the call fails, so a result cannot be credited to the wrong channel. The
  switch shows `write_path: cloud_mqtt` and `write_trial: true` in that state, `write_path: local`
  otherwise.
- Write and confirmation (`mqtt_write.async_mqtt_write_preheat`, not `async_mqtt_write`, which
  refuses DP 1): the settings block is built first (a value unknown: nothing is sent); the head is
  read through the tunnel **before** anything goes out (no answer: nothing is sent; already at the
  value: nothing is sent); then the publish, then the block over HTTP (since the second trial
  design of 2026-11-20; stage B ran with the publish alone); then the head is read every 10 s
  until bit 1 of `0x0025` shows the value, for 120 s at most, then a clear error. The gateway's
  echo is not even listened to, the cloud is not read.
- After a "not confirmed", the frame has been sent: the head may apply it late, and the cloud's
  DP 1 may differ from the head. The integration has no way to put that cache back (asking for the
  head's own value publishes nothing, since the tunnel could not confirm it); the sheet does it
  from the Danfoss app, checked by a read of cloud DP 1.
- What the code does **not** check: bit 0 of `0x0025` (the switch only knows bit 1) and the
  cloud's DP 1 / DP 172. The sheet makes the supervisor read them by hand.
- No route outside a trial yet. If the trial passes, promoting DP 1 is a change of its own that
  must also decide when cloud MQTT is preferred to the tunnel (see the assessment).

## Assessment

Since the tunnel is needed to confirm the write, and the tunnel already writes preheat directly, a
cloud-MQTT route for DP 1 would not make preheat available on any head that lacks it today. Its
only value would be as a fallback when the tunnel can read but not write, which has not been
observed. Recommendation: run the observation (it is cheap and settles what the app's toggle really
does), and expect to **not** promote this route — and to remove the candidate if the observation is
negative.

After stages A and B (2026-11-20): the app's toggle works, the integration's bare DP 1 publish
does not. The assessment of the route's usefulness is unchanged (the tunnel is needed to confirm
the write and already writes preheat directly), and it now also has a cost: finding out what the
app really sends. The owner chose to keep DP 1 as a closed candidate. A next trial, if any, should
first change what is sent (the lead above: the MQTT publish together with `settings.change`, as
the app does), under the same tunnel-only confirmation, rather than repeat stage B.
