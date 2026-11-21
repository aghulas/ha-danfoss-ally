# Tuya cloud MQTT — interface map

A map of the Tuya cloud MQTT channel (the Danfoss Ally app's broker) as the integration and the
MCP connector see it: topics, message types, frame, the DPs actually pushed, what is read and what
is written, and what is still unknown.

It complements, and does not replace:

- `docs/cloud-mqtt-publish.md` — the wire format and the credential derivations as implemented;
- `docs/cloud-mqtt-coverage.md` — how to run the 24 h coverage measure;
- `docs/interface-contract.md` §4.2 — the status of each written DP.

"MQTT" here always means **Tuya cloud MQTT**, the channel to the heads, never the MQTT publishing
to the user's own broker.

## 1. Sources and method

| Source | What it gives |
|---|---|
| `api/mqtt_publish.py`, `api/mqtt_client.py` | Codec, credentials, link — the reference for everything marked *implemented* |
| Captures of 2026-11-21 (below) | Everything marked *observed* |
| The maintainer's private research notes (app decompilation) | Everything marked *static analysis*: read in the app's code, never seen on the wire by this project |
| The official product schema of the head (76 DPs) | DP names, access and scales |

**Capture.** One listen-only session on a real install, Saturday 2026-11-21, 14:37 to 15:07 local
time (30 min), through the MCP connector's own session: subscription to the inbound topic of the
10 gateways, nothing published. Heating season, weekend: every head in its setback period, no
schedule transition and no user action in the window. The connector returns, per sender, the
number of reports and per DP a count and the **last** value; it does not return the frames
themselves (no `seq`, `origin`, `t`, size or arrival time). Figures:

| | |
|---|---|
| Frames decoded and authenticated | 1080 (0.6 per second over the fleet) |
| Senders | 94: 93 heads and one room sensor |
| Frames that are not a `{cid, dps}` report | 0 |
| Protocol numbers seen | 4 only |
| Frames carrying more than one DP | 35: `{24, 169}` (28), `{140, 141}` (6), `{25, 173}` (1) |
| Distinct DPs seen | 11 on heads (24, 25, 34, 107, 108, 111, 140, 141, 169, 173, 199), 2 on the room sensor (1, 2) |

**Second capture (targeted).** Same install, 2026-11-21 evening, a five-minute listen during which
the owner changed a setpoint, a mode and the child lock of one head in the app (§6.1). It supplies
the command and settings DPs the quiet first window could not, on that one head.

Everything below is anonymised: `<gateway-id>` is a gateway's devId, `<node-id>` a sub-device's
Zigbee node id, `<head>` the one head of the second capture, `<account>` anything derived from the
account or the session. Example payloads carry measurements only.

## 2. Broker and session

| | | Status |
|---|---|---|
| Host | `m1.tuya<region>.com` (EU: `m1.tuyaeu.com`), port 8883, TLS with certificate check | implemented, observed |
| MQTT | 3.1.1, clean session, keep-alive 60 s, QoS 1, no retained message | implemented |
| Client id | `<package>_mb_<deviceId>_<md5hex(uid + salt)>_DEFAULT` | implemented, byte-exact against the app |
| User name | `<partnerIdentity>_v1_<appId>_<chKey>_mb_<sid><16 hex chars>` | same |
| Password | 16 hex chars derived from the signing key and the session's `ecode` | same |

The credentials are derived from the HTTP session (`sid`, `ecode`, `uid`, `partnerIdentity`) and
from the installation material the HTTP signature already uses. There is no separate MQTT login:
**the MQTT identity is the HTTP session**. Derivations: `docs/cloud-mqtt-publish.md`.

The broker accepts **one connection per session**. Three clients therefore hold three sessions,
each under its own deviceId: the app, the integration (a deviceId derived for MQTT), the MCP
connector. During the capture the connector's session stayed connected for the 30 minutes.

## 3. Topics

| Topic | Direction | Carries | Status |
|---|---|---|---|
| `smart/mb/in/<gateway-id>` | gateway → clients | Reports of the gateway's sub-devices, and the echo of a write | observed; the only topic subscribed |
| `smart/mb/out/<gateway-id>` | client → gateway | DP publish to a sub-device | implemented; proven for eight DPs |
| `<partnerIdentity>/mb/<uid>` | cloud → the user's clients | Account-level events (static analysis: the app subscribes to it) | derived (`mqtt_publish.user_topic`), **never subscribed**, content unknown |

Segments: `smart` is fixed; `mb` is the "mobile" side (it is also in the client id and the user
name); `in` / `out` are named from the **app's** point of view; the last segment is the
**gateway's** devId. A head has no topic of its own: it is addressed inside the payload by its
node id (`cid`). A frame is encrypted with the key of the gateway named in the topic, so a
subscriber needs each gateway's local key; the integration fetches them from the device list.

One subscription per gateway is needed (10 here). Whether a wildcard subscription is accepted was
not tried.

## 4. Frame

```
header (12 bytes) = "2.3" | seq (uint32 BE) | origin (uint32 BE) | 0x00
body              = nonce (12 bytes) | AES-128-GCM ciphertext | tag (16 bytes)
key               = the gateway's local key (16 ASCII characters)
AAD               = the header
plaintext         = {"data": <data>, "protocol": <int>, "t": <epoch seconds>}
```

- There is **no signature besides the GCM tag**. A frame that authenticates under a gateway's key
  is taken as that gateway's; all 1080 frames of the capture authenticated.
- `seq` / `origin`: the receiver drops a repeated pair. A sender keeps one random `origin` per
  session and increments `seq` before each publish (first frame: 3). Static analysis for the
  app's receiver, and the gateway is assumed to do the same; the values the **gateways** put in
  their own frames have not been looked at.
- `t` is informational: no freshness window is known.
- Only protocol version 2.3 is implemented, and every frame received was 2.3. Versions 2.1 / 2.2 exist in
  the app (AES-ECB, another layout) and are refused, not guessed.

## 5. Message types

| `protocol` | Direction | Meaning | Status |
|---|---|---|---|
| 4 | in | DP report of a sub-device: `{"cid": "<node-id>", "dps": {…}}` | observed: 1080 of 1080 frames |
| 5 | out | DP publish: `{"cid": "<node-id>", "ctype": 0, "dps": {…}}` | implemented, proven on real hardware |
| 22 | out | DP publish, a variant used by another builder of the app | static analysis only |
| 31 | out | DP query | static analysis only |
| 63 | out | Sub-device add / cancel (pairing) | static analysis only |
| 51, 200 | — | Configuration | static analysis only |

What a report looks like once decrypted. The envelope is the one the codec decodes; the DP values
are from the capture; the connector does not return `t`:

```json
{"data": {"cid": "<node-id>", "dps": {"24": 161, "169": 1617}}, "protocol": 4, "t": <epoch seconds>}
```

A report carries **one DP that changed, sometimes two that go together** (§1), never a full state. There is no command /
acknowledgement pair: a write is acknowledged by the ordinary report of the DP it changed, on the
inbound topic, which is why the integration matches the echo on `cid` + DP + value.

Not seen in 30 minutes: any frame about a gateway itself (online state, firmware, sub-device
list), any frame without `cid`, any protocol other than 4.

## 6. DPs observed

Heads (product schema `03wvrwpv`). "Heads" is the number of heads that pushed the DP at least
once, out of 93. The value column is the range of the **last** values, one per head.

| DP | Official code | Access | Heads | Value seen | Meaning and scale |
|---|---|---|---|---|---|
| 24 | `temp_current` | ro | 24 | 151 … 177 | Measured temperature, tenths of °C |
| 169 | `local_temperature` | ro | 53 | 1333 … 1846 | Same measurement in hundredths of °C, always in the frame that carries DP 24 and also alone. The schema says scale 10⁰: wrong, like DP 171 |
| 34 | `battery_percentage` | ro | 7 | 62 … 67 | % (the head's raw value halved, see §7) |
| 25 | `window_state` | ro | 1 | `close` | Open-window state |
| 173 | `open_window` | ro | 1 | 0 | Open-window state as a number; came with DP 25 on the same head |
| 107 | `LoadRadiatorRoomMean` | rw | 39 | −94 … 20 | Room mean of the load, identical on every head of a room. Presumably written by the gateway (load balancing) and reported back |
| 108 | `Load_estimate` | ro | 39 | −101 … 172 | The head's own load estimate. The chattiest decoded DP: 87 reports, up to 11 per head |
| 111 | `SetpointChangeSource` | ro | 92 | `Schedule`, `Externally` | Source of the current setpoint. Twice per head (once on one head): see §7 |
| 140 | `room_sensor` | rw | 6 | `true` | The room regulates on a room sensor. Pushed once, to all six heads of one room together |
| 141 | `sensor_avg_temp` | rw | 6 | 176 | That sensor's temperature, tenths of °C, pushed with DP 140 |
| 199 | `gw_from_device` | rw | 92 | base64 | The head's raw Zigbee frame, see §7 |

Room sensor (another product; the connector does not index it, so it appears as an unknown node):

| DP | Meaning | Value seen |
|---|---|---|
| 1 | Temperature, tenths of °C | 172, then 175 |
| 2 | Humidity, tenths of % | 619, then 574 |

Three reports of each in 30 minutes. DP 141 pushed to the heads (176) is within a degree of it
and was not pushed at the same instant; that it is the same sensor is likely, not established.

**Not pushed in the window**, although the integration's entities are built from them: mode (2),
heating action (3), setpoints (16, 118, 119, 120, 121, 171), bounds (18, 27), child lock (30),
window detection (116), faults (45, 184), mounting (149), heat request (162), valve opening
(170), operation mode (172). The window had no schedule transition, no heat demand change worth
a report and no user action, so this said nothing about whether they are pushed: it was the main
gap of this capture. A second, targeted capture closed most of it (§6.1).

### 6.1 DPs pushed by a targeted change in the app (one head)

A second, five-minute capture settled the main gap above. With a listen running, the owner changed
three things **in the app** on one head (`<head>`, grouped, not isolated): its setpoint, its mode
and its child lock. That head then pushed its command DPs and a near-complete state snapshot (120
frames in ~3 minutes, against 1–8 for a quiet head). What each change carried:

| Change in the app | DP(s) | Value seen | Note |
|---|---|---|---|
| Setpoint | **171** `OccupiedSetpoint` | 550 → 1400 | Hundredths of °C (5.5 → 14.0 °C), the same scale as the tunnel's DP 171 (R3). Room-level setpoints came with it: DP 109 / 112 / 119 = 140, DP 110 / 114 / 120 = 55 (scale not asserted here) |
| Mode | **2** `mode` | `manual` → `leaving_home` | DP 111 `SetpointChangeSource` flipped `Schedule` → `Externally` at the same time. Confirms the mode travels as DP 2 on this channel; R4/R5 are unchanged — nothing is written to DP 2 here |
| Child lock | **30** `child_lock` | `true` | A boolean, as the isolated-head write already uses (§8) |

The same snapshot also carried, for that head, settings the first capture never saw: DP 101
`viewing_direction` (`false`), DP 133 `thermostat_orientation` (`Horizontal`), DP 116 window
detection (`true`), DP 18 / 27 bounds (215 / 50 = 21.5 / 5.0 °C), DP 172 operation mode (3) and
DP 173. So the channel does carry a head's full settings state; the first capture was quiet only
because nothing had changed. The per-DP summary used here does not tag direction: a command is a
protocol-5 publish out and its echo a protocol-4 report in (§5), both on the head's DP, and the
120 frames mix the two. The tested head was grouped, so whether the echo of a setting differs on
an **isolated** head is still open (§10).

## 7. DP 199: the head's Zigbee traffic is pushed too

DP 199 (`gw_from_device`) is the upstream half of the gateway's Zigbee tunnel. It is the same DP
the local tunnel reads on the LAN, and the cloud receives it as well: **682 of the 1080 frames**
of the capture are DP 199 alone. Layout (`api/local/tunnel.py`):

```
40 01 | cluster (uint16 LE) | 04 01 01 | counter (1 byte) | ZCL frame
```

The byte called `counter` is written `00` in the frames the integration sends (DP 198). In the
head's frames it increases by one per frame of that head. That reading comes from the first and
last value of a few heads, not from a full series.

Kinds of ZCL frame seen, each decoded from a last value:

| Cluster | ZCL frame | Content | Decoded DP that follows |
|---|---|---|---|
| `0x0201` thermostat | Report Attributes, `0x0000` (int16) | Local temperature, hundredths of °C | 169, with 24 in the same frame about half the time |
| `0x0201`, manufacturer `0x1246` | Report Attributes, `0x404A` (int16) | Load estimate | 108 |
| `0x0201`, manufacturer `0x1246` | Report Attributes, `0x4040` (int16) | Load room mean | 107 |
| `0x0201`, manufacturer `0x1246` | Report Attributes, `0x4000` (enum8) | Window state | 173 / 25 expected; not paired in this capture |
| `0x0201`, manufacturer `0x1246` | Report Attributes, `0x404D` (bitmap8) | Adaptation run status | 175 expected; not seen as a DP |
| `0x0001` power | Report Attributes, `0x0021` (uint8) | Battery, in half percent (126 → DP 34 = 63) | 34 |
| `0x0B05` diagnostics, manufacturer `0x1246` | Report Attributes, `0x4000` (bitmap16) | Software error code (0) | 184 expected; not seen as a DP |
| `0x0020` poll control | Check-in (cluster command `0x00`) | The sleepy head's periodic check-in | none |
| `0x0201` thermostat | **Read Attributes Response**: `0x0012`, `0x0015`, `0x0016`, `0x0025`, `0x0030` | Current setpoint, bounds, programming mode, setpoint source | 111 |

Three consequences.

1. **A decoded DP and its raw frame arrive as two frames.** The gateway forwards the head's ZCL
   report in DP 199 and, separately, the DP it maps it to. The pairs in the table are matched by
   value (for example `0x404A` = −4 and DP 108 = −4 on the same head).
2. **The tunnel's answers are visible from the cloud.** The last row is not spontaneous: it is the
   answer to a Read Attributes of exactly the five attributes of the integration's local survey
   (`ATTRS_STD`), and DP 111 — the mirror of attribute `0x0030` — arrived **twice on 91 heads and once on one** in 30 minutes, which fits a survey pass about every 15 minutes. So a read made through
   the LAN tunnel is answered on DP 199 **to the cloud as well**, and any cloud-MQTT subscriber
   receives it. A listener therefore gets, without asking anything, the current setpoint
   (`0x0012`), the bounds, and the real programming mode (`0x0025`: schedule and preheat bits) of
   every head the integration surveys. That the sender of those reads is the integration's survey
   is inferred from the attribute list and the cadence, not proven.
3. **Some head attributes reach the cloud only as raw frames.** The adaptation status and the
   error code were seen in DP 199 with no decoded DP after them in this window.

## 8. Read and write through this channel

| | Today | Status |
|---|---|---|
| **Write**: DP publish to an **isolated** head | DP 30, 116, 18, 27, 120, 118 + 16, 119 (`api.writes.MQTT_WRITE_DPS`) | Proven, each by its own supervised write |
| Write, candidates | DP 1 (preheat: supervised write **not passed**), 101, 133 | Closed |
| **Read**: the echo of a write | Matched on `cid` + DP + value, then a cloud re-read if it does not come | Implemented |
| Read: coverage counters | `cloud_mqtt_probe`: counts per head and per DP, no value kept | Implemented; the 24 h run is pending |
| Read: entity state from the push | — | Not implemented (roadmap stage 4) |

How it fits the routing rules of `docs/architecture.md`:

- The channel **acts where cloud HTTP only accepts**: settings of an isolated head. It is the
  app's own path for them.
- It does **not** make cloud DP 1 a preheat lever: the 2026-11-20 write changed the cloud's value
  and not the head. The capture adds a way to see the real bit without the tunnel being the one
  that reads it: attribute `0x0025` travels in DP 199 whenever anyone reads it (§7).
- DP 2 labels (R5) and the manual switch (R4) are untouched by anything **written** here: a mode
  change made in the app did push DP 2 (`manual` → `leaving_home`, §6.1), but this channel writes
  no DP 2 of its own.
- `online` is still only in the HTTP device list: nothing about a head or a gateway going offline
  was pushed.

## 9. Gaps between the channel and what the integration uses

Findings to weigh, none implemented here.

1. **DP 199 is ignored on the inbound side.** `mqtt_coverage` counts it like any DP, and nothing
   decodes it. Yet it is 63 % of the traffic and carries values the cloud DPs do not
   (programming mode `0x0025`, setpoint source, adaptation status). `api/local/tunnel.py`
   (`decode_frame`, `decode_attributes`) already decodes these frames; only Report Attributes
   (`0x0A`) and the poll-control check-in are not handled by it.
2. **The local survey could be confirmed, or fed, from the cloud push.** The survey's own answers
   come back on this channel. A head that does not answer on the LAN within the tunnel's timeout
   may still have its answer pushed here. Not tried.
3. **The coverage measure will be dominated by tunnel traffic.** `heads_seen` will be close to
   the whole fleet for any install with the local survey on, because DP 111 and DP 199 arrive at
   every pass, whether or not the head pushes anything by itself. `docs/cloud-mqtt-coverage.md`
   should read coverage per DP, and treat DP 111 and DP 199 apart. Worth a follow-up change to
   the probe's summary.
4. **`READ_DPS` misses pushed DPs.** DP 169 is pushed twice as often as DP 24 (57 reports on 53 heads
   against 28 on 24) and has ten times its resolution; DP 107, 108, 140, 141 and 173 are pushed and not
   decoded by the cloud read path.
5. **The room sensor is pushed** (temperature, humidity) and would be an unknown sender to the
   probe (`unknown_senders`), which only indexes heads.
6. **The user topic is derived and never subscribed.** If account-level events travel there
   (device online / offline, room changes, session eviction), nobody is listening.
7. **No inbound frame is ever surfaced when it fails to decode**: the link counts `received` and
   `decoded`, and the connector only counts decoded frames. A frame under another protocol
   version, or one that fails authentication, is invisible in both tools.

## 10. Unknowns, and what would settle them

| Unknown | What would settle it |
|---|---|
| Are mode and setpoints pushed (DP 2, 171, 109/112/119)? | **Observed (§6.1)**: a setpoint and a mode change in the app push DP 171 and DP 2, with a near-complete state snapshot. Still open for DP 3, 170, 162 (no heat-demand change in the window) |
| Is a setting changed **in the app** pushed (DP 30, 116, 18, 27, 101, 133)? Does the echo differ between an isolated head and a room? | **Observed (§6.1)** on a grouped head: DP 30 (child lock), 101, 133, 116, 18, 27 all travel. The isolated-vs-room difference is still open — the tested head was grouped |
| Is a window event pushed promptly (DP 25, 173)? | The owner opening a window near a head during a listen |
| Does anything announce a head or a gateway going offline or coming back? | A head with its batteries removed for the time of a listen; a gateway unplugged is more intrusive and not asked for |
| What travels on the user topic `<partnerIdentity>/mb/<uid>`? | A listen-only subscription to it. Needs a change to the connector's listener, which subscribes to gateway topics only |
| Which frames fail to decode, and how many? | The connector returning `received` beside `decoded`, and the count per protocol for frames without `cid` |
| What `seq`, `origin` and `t` do gateways put in their frames? Is `t` the report time or the forwarding time? | The connector returning those three fields for a few frames. Needed before the push can time-stamp a value |
| Is the tunnel `counter` byte really a per-head frame counter? | The full series of DP 199 values of one head, not only the last one |
| Who sends the Read Attributes whose answers are seen in §7? | Turning the integration's local survey off for one listen: DP 111 should stop |
| Does the gateway forward to the cloud the answer to **every** tunnel read, including the weekly schedule? | A listen during a `get_local_survey` with schedules; the schedule answer would be a cluster command `0x00` of `0x0201` in DP 199 |
| Protocols 22, 31, 63, 51, 200: does a DP query (31) return a full state? | Not to be tried without a supervised-write procedure of its own: a query is a publish on the outbound topic |
| Is a wildcard subscription accepted? | Low value; not worth a trial on a real account |
