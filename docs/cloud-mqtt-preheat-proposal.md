# Preheat over Tuya cloud MQTT (DP 1) — closed candidate, observation pending

Status: **candidate, closed, nothing shown on real hardware**. DP 1 is in
`api.writes.MQTT_CANDIDATE_DPS`: no install writes it over cloud MQTT unless it is listed in
`cloud_mqtt_supervised_dps` for the one head of `cloud_mqtt_supervised_head`. The code was written
ahead of the observation at the owner's request (2026-11-19), so that a supervised write is ready
if the observation is positive. **The observation below still comes first**: it needs no code, and
if it is negative DP 1 is removed from the candidates and the question is closed. Step-by-step
sheet: `docs/first-write-procedure.md`, "DP 1 — preheat".

## Why this DP is last

Preheat is the known trap of this integration (`docs/architecture.md`):

- over **HTTP**, writing DP 1 changed the gateway's cache and nothing else: the cloud showed the
  new value while the head's real preheat did not move;
- the head's real preheat is **bit 1 of Zigbee attribute `0x0025`** (programming operation mode),
  readable and writable only through the local tunnel — the path the preheat switch uses today,
  validated on real hardware;
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

## Observation proposed before any code (owner present)

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
- Confirmation (`mqtt_write.async_mqtt_write_preheat`, not `async_mqtt_write`, which refuses
  DP 1): the head is read through the tunnel **before** the publish (no answer: nothing is sent;
  already at the value: nothing is sent); after the publish it is read every 10 s until bit 1 of
  `0x0025` shows the value, for 60 s at most, then a clear error. The gateway's echo is not even
  listened to, the cloud is not read.
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
