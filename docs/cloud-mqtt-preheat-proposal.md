# Preheat over Tuya cloud MQTT (DP 1) — proposal, not implemented

Status: **proposal only**. No code writes DP 1 over cloud MQTT, DP 1 is neither proven nor a
candidate in `api/writes.py`, and no option opens it. This note says what would have to be shown
before any code is written, and what the code would then look like.

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

## Implementation, only if the observation is positive

- DP 1 becomes a candidate (`MQTT_CANDIDATE_DPS`), boolean.
- The preheat switch keeps the **tunnel as its only source of state**. It never shows the cloud's
  DP 1.
- Routing: tunnel write first when the head answers locally (proven, immediate). Cloud MQTT only
  when the tunnel can still **read** the head but a tunnel write is not wanted or failed — in
  practice the same condition, so the second route adds little. Without a tunnel read there is no
  way to confirm the write, so **no tunnel, no preheat switch**, exactly as today.
- Confirmation: after the publish, `async_refresh_head` (tunnel read of `0x0025`) until bit 1 shows
  the value or a timeout; the gateway's echo and the cloud read are **not** accepted as
  confirmation for this DP. A dedicated confirmation rule, not `async_mqtt_write`'s default.
- Supervised trial as for the other DPs, read back through the tunnel.

## Assessment

Since the tunnel is needed to confirm the write, and the tunnel already writes preheat directly, a
cloud-MQTT route for DP 1 would not make preheat available on any head that lacks it today. Its
only value would be as a fallback when the tunnel can read but not write, which has not been
observed. Recommendation: run the observation (it is cheap and settles what the app's toggle really
does), and expect to **not** implement this route.
