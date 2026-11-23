# Tuya cloud MQTT channel

Everything about the Tuya cloud MQTT channel (the Danfoss Ally app's broker) in one place:

- §1–11 — the **interface map**, as the integration and the MCP connector see it: topics, message
  types, frame, the DPs actually pushed, what is read and written, what is still unknown;
- §12 — the **write path as implemented**: credential derivations, confirmation, link lifecycle;
- §13 — how to **measure push coverage** (the 24 h run, still to do);
- §14 — the **target routing** study: how much can move to this channel.

The status of each written DP is in `docs/interface-contract.md` §4.2; the supervised-write
procedure in `docs/first-write-procedure.md`.

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
**the MQTT identity is the HTTP session**. Derivations: §12.

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
- The plaintext JSON is compact with sorted keys. Encode / decode: `mqtt_publish.encode_frame` /
  `decode_frame`; the publish payload is built by `mqtt_publish.dp_publish_data`.
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
   every pass, whether or not the head pushes anything by itself. The measure of §13
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

## 11. Comparison with Tuya's published MQTT protocol (TuyaLink)

Tuya documents one MQTT protocol publicly: **TuyaLink**, the "Tuya MQTT Standard Protocol" of the
developer platform (pages read on 2026-11-21: the protocol overview, the topic list, properties /
actions / events, sub-device online / offline). It is **not the channel mapped above**. TuyaLink is
the **device ↔ cloud** side — what a gateway says to the cloud. This document maps the **app ↔
cloud** side, which Tuya does not publish. The two share the brokers and little else.

| | TuyaLink (published) | The app's channel (this document) |
|---|---|---|
| Broker | `m1.tuya<region>.com`, port 8883, TLS | the same hosts and port (§2) |
| MQTT | 3.1.1, QoS 0 / 1, keep-alive 60 s | the same (§2) |
| Topics | `tylink/<deviceId>/thing/…`, `…/device/…`, `…/ota/…`, `…/ext/…`, `…/channel/raw/…` | `smart/mb/in|out/<gateway-id>` (§3) |
| Payload | plain JSON: `msgId`, `time`, `data` | encrypted frame: `protocol`, `t`, `data` (§4) |
| Data model | named properties (`code`), actions, events | numbered DPs (`dps`) |
| Identity | the device's own certificate (`DeviceID` + `DeviceSecret`, HMAC-SHA256) | the app's HTTP session (§2) |
| Sub-device | `subDevices[].deviceId` in the gateway's report | `cid` in the payload (§3) |

What the published protocol **confirms** about ours:

- **One connection per identity.** A second connection under the same certificate forces the first
  one offline. This is the behaviour §2 describes for sessions, and the reason each client holds
  its own deviceId.
- **Offline is declared after 1.5 × the keep-alive** without a message.
- **The gateway is the proxy.** Sub-devices have no topic of their own; their data and their
  online state travel under the gateway's identity.

What it **suggests** for the unknowns of §10 — hypotheses, none observed on our channel:

- **Online / offline exists as an MQTT event on the device side.** The gateway publishes
  `device/sub/login` and `device/sub/logout` with the list of sub-devices. So the cloud learns a
  head's connectivity in real time; whether it relays that to the app's clients is the open
  question, and the user topic is the likely place.
- **A raw channel exists** (`channel/raw/up` / `raw/down`), the conceptual counterpart of DP 198 /
  199 carrying the head's Zigbee frames (§7).
- **Topology is queried and notified on the device side** (`device/topo/get`, `topo/change`).
  Nothing says it is exposed to the app's clients; fleet discovery stays on cloud HTTP.
- **The model is spontaneous report plus set**: no cloud → device "read the state now" appears in
  the pages read. That is consistent with the channel being event-driven (§8).

What it does **not** give us:

- **No listening path.** Subscribing to `tylink/` topics needs the gateway's device secret, and a
  connection under the gateway's identity would **force the real gateway offline**. Never to be
  tried.
- Whether the Ally gateway speaks TuyaLink or the older device protocol on its own side is not
  established; the comparison is about the protocol family, not a capture.
- Nothing about the app-side protocol numbers (§5), the frame (§4) or the user topic.

## 12. Write path as implemented (maintenance spec)

The path the integration uses to write an **isolated** head's settings (those not grouped into a
room), behind the `enable_cloud_mqtt` option (OFF by default). It is the path the Danfoss app
itself uses: `tuya.m.custom.wkf.settings.change` is accepted by the cloud but **never applied** to
an isolated head (W-3, `docs/interface-contract.md` §4.2), whereas a DP **publish** over MQTT is.
This section documents the derivations and the link **as implemented** (`api/mqtt_publish.py`,
`api/mqtt_client.py`) so the code stays maintainable; frame and addressing are in §3–5. The
reverse-engineering method that established it is kept out of this public repository (see
"Provenance" below).

### Sequence / de-duplication

The receiver drops a repeated `(seq, origin)` pair ("cloud command repeat"). `origin` is random per
session, `seq` increments before each publish. Keep one `SeqOrigin` per gateway for the whole
session and never reset it mid-session (`mqtt_publish.SeqOrigin`, one per gateway in
`CloudMqttLink`).

### Broker and credentials (as implemented)

- Broker: `ssl://m1.<region>.tuya…:8883` (EU = `m1.tuyaeu.com`), `region` from the config entry.
- clientId: `<package>_mb_<deviceId>_<md5hex(uid + "sdkfasodifca")>_DEFAULT`. The integration uses a
  **dedicated** deviceId derived from its own (`derive_distinct_device_id`), so its clientId cannot
  collide with the app's.
- username: `<partnerIdentity>_v1_<appId>_<chKey>_mb_<sid><last16(md5hex(md5hex(appId) + ecode))>`,
  where `appId` is the HTTP client id and `chKey` the installation channel key. Derivation:
  `mqtt_publish.mqtt_username`.
- password: the middle 16 chars of `md5hex(md5hex(sign_key) + ecode)` (`mqtt_publish.mqtt_password`).
- user topic: `<partnerIdentity>/mb/<uid>`.

`sign_key`, `uid`, `partnerIdentity`, `sid`, `ecode` all come from the integration's own session
(`CloudClient.session` / `CloudClient.mqtt_identity`, populated at login). They are secret and never
logged, put in diagnostics, or placed in the thread name.

### Session policy (observed)

The broker allows **one active MQTT connection per session**. Two clients that present the **same**
session (same `sid`/`ecode`, hence the same username) conflict; two **different** sessions coexist.
The integration therefore connects with **its own** session (distinct deviceId), independent of the
Danfoss app's and the MCP connector's. Confirmed on real hardware: the integration's session is
accepted (`CONNACK rc=0`) while the phone app stays connected.

### Write and confirmation

`CloudMqttLink.publish_dp` sends the frame and `await_confirmation` waits for the gateway's inbound
protocol-4 `{cid, dps}` echo (matched on `cid` + the written DP/value) within a timeout; the entity
then falls back to a cloud re-read, and raises a clear error if still unconfirmed — never an
optimistic state. A link that is down makes the dependent switches and numbers unavailable.

### Link lifecycle (hardening)

- **Open**: only when `enable_cloud_mqtt` or `cloud_mqtt_probe` is on. One connection per entry.
- **Close (kill switch)**: turning the option off reloads the entry; on unload the link sends
  `DISCONNECT`, which also ends the client's reconnect loop, then joins the client thread (in an
  executor, never on the event loop). `stop` is idempotent.
- **Reconnection**: exponential backoff from `RECONNECT_MIN_DELAY` (5 s) to `RECONNECT_MAX_DELAY`
  (300 s), reset by an accepted connection.
- **Session rotation**: before each reconnection the credentials are rebuilt from the HTTP client's
  current session (`creds_provider`), so a renewed `sid` / `ecode` is picked up.
- **Session invalidated elsewhere**: the broker then answers `CONNACK` 4 or 5. At the first refusal
  of a streak the link asks the integration for one cloud refresh (`on_auth_refused`): the HTTP call
  notices the invalid session and signs in again, and the next attempt carries the renewed
  credentials. After `MAX_AUTH_REFUSALS` (5) refusals in a row, about a minute, the link **stops for
  good** (state `refused`) until the entry is reloaded: it never presents refused credentials in a
  loop. Other return codes (broker unavailable…) are transient and only follow the backoff.
  Two cases behind that refresh (`tests/test_mqtt_session_renewal.py`): a session invalidated
  elsewhere is renewed **inside the HTTP request** (`CloudClient._request` signs in again and
  replays), so the refresh succeeds and the link recovers; a sign-in that is itself refused
  (password or installation secrets no longer valid) raises `ConfigEntryAuthFailed`, nothing can
  renew the session, and the link stops after its refusals — which is the wanted outcome. Home
  Assistant then offers the integration's reauthentication step (same account, new password, new
  installation secrets only if they changed), which updates the entry and reloads it.
- **States**: `idle`, `connecting`, `connected`, `refused`, `stopped`, shown by the "Cloud MQTT
  link" sensor (`state` attribute) and the `cloud_mqtt_link` diagnostics block (with the counters
  `connects`, `disconnects`, `auth_refusals`, `last_connack_rc`, `received`, `decoded`).
- **Nothing sensitive leaves the process**: the client thread is renamed (paho names it after the
  client id), log lines carry states and error types only, the `repr` of the credentials, gateway
  references, link and publish plan omit every secret and identifier, and an "unknown gateway"
  error does not name the gateway.

Not verified on real hardware: whether the broker drops an established connection when its session
is renewed or invalidated. The code handles both outcomes (kept: nothing to do; dropped: the path
above), but the 5-refusal limit has only been exercised with a faked client.

### Validation status

- **Session coexistence**: confirmed on real hardware (2026-11-19) — independent-session connect
  `rc=0`, inbound frames decoded, the phone app not evicted.
- **First write**: DP 30 (child lock) on an isolated test head (2026-11-19), confirmed in the cloud,
  in the app and physically on the head; no other head or setting affected.
- **Supervised writes of 2026-11-19 (evening)**, each on one isolated test head, written once and
  restored: DP 116 (window detection), DP 18 (upper bound), DP 27 (lower bound, alone and in one
  frame with DP 120) — read back through the local tunnel and in the app; DP 120 (pause setpoint)
  — read back in the app and the cloud only, since no tunnel read exists for it (a weaker proof).
  Every call returned in under a second, which is consistent with the gateway's echo; the
  confirmation source itself was not read from the debug log. No other setting of the head
  changed.
- **Supervised writes of 2026-11-19 (night) and 2026-11-20 (morning)**, on one isolated head
  following its weekly schedule, written once and restored: DP 119 (setback setpoint) and
  DP 118 + 16 (comfort setpoint), read back through the local tunnel (current setpoint and weekly
  schedule) and in the app. The head carried each new value into its own schedule transitions
  about a minute after the write; DP 16 set the current setpoint at once and the head returned to
  its schedule within five minutes. Every call returned in under a second.
- **Scope today**: the MQTT write path carries **DP 30, 116, 18, 27, 120, 118, 16 and 119** as
  proven (`api.writes.MQTT_WRITE_DPS`). DP 1 (preheat) is implemented as a **candidate**
  (`MQTT_CANDIDATE_DPS`), closed, with a rule of its own: its write is
  confirmed by the local tunnel's read of attribute 0x0025 only, never by the echo or the cloud.
  Its supervised write of 2026-11-20 was **not passed** (the cloud's DP 1 changed, the head did
  not), so it stays closed (`docs/preheat.md`). DP 133 (orientation) passed its trial on 2026-11-20
  and DP 101 (viewing direction) is still to run; both remain candidates. A DP is added one at a
  time, as a candidate first (`docs/first-write-procedure.md`).

### Provenance

The method used to recover this protocol (app decompilation, dynamic instrumentation, and the
credential/frame captures) is **not** in this public repository. It lives in the maintainer's
private research notes. This section is the maintenance specification only.

## 13. Measuring push coverage

Roadmap item "push coverage". Open question of `docs/architecture.md`: the Tuya cloud MQTT broker pushes DP reports, but for
**which heads**, **which DPs**, and **how often**? The answer decides stage 4 (the push as a read
source). This measure answers it without sending anything.

### What the option does

`cloud_mqtt_probe` (options, **off by default**):

- opens the cloud-MQTT link from the integration's own session and subscribes to the gateways'
  inbound topics. With `enable_cloud_mqtt` off, the link is **listen-only**: it has no send path
  (`can_publish` is false, `plan_dp` and `publish_dp` refuse), and no switch routes through it. With
  `enable_cloud_mqtt` on, both share the one connection the session allows;
- accounts every decoded frame per head and per DP: number of reports, first and last instant,
  median and longest interval (the median over the last 256 intervals of each series). It keeps
  **no DP value and no payload**;
- serves the result in the entry's **diagnostics**, under `cloud_mqtt_coverage`. A head is named by
  `device_index` (its position in the diagnostics `devices` list) and its display name; no device,
  node or gateway identifier appears. Nothing is logged;
- a listen-only link **closes itself after 48 h**, so a forgotten option does not keep a broker
  connection open on the account. The aggregates stay readable until the entry is reloaded.

The aggregates live in memory: **reloading the entry or restarting Home Assistant starts the measure
again** (changing any option reloads the entry).

### Running the measure

1. Pick an ordinary day of the heating season (schedules running).
2. Turn `cloud_mqtt_probe` on. The entry reloads; the "Cloud MQTT link" diagnostic sensor turns on.
3. Leave it for **24 h** without touching the options and without restarting Home Assistant.
4. Download the diagnostics (Settings → Devices & services → the entry → ⋮ → Download diagnostics).
5. Turn the option off.

### Reading the result

First the sibling block `cloud_mqtt_link`: `state`, `connects` / `disconnects` (a high count means
the link kept dropping: the gaps below are then the link's, not the heads'), `received` / `decoded`
(a gap between the two means frames this codec cannot read).

Then `cloud_mqtt_coverage`:

| Field | Meaning |
|---|---|
| `started`, `stopped`, `duration_s` | The window measured. Check it is the 24 h you expect |
| `frames`, `frames_by_protocol` | Everything decoded. Protocol `4` is a DP report |
| `frames_without_head_report` | Frames about a gateway itself, or carrying no DP |
| `heads_known`, `heads_seen` | Heads of the last cloud poll, and how many of them reported at least once |
| `heads_never_seen` | The heads that never reported, with `online` and `grouped`. An offline head is expected here; an **online** one is a coverage hole |
| `unknown_senders` | Senders matching no known head (sensor, relay, head added since): a count only |
| `dps` | Per DP: on how many heads it was seen, and the total of reports |
| `read_dps_never_pushed` | DPs the cloud read decodes that no head ever pushed |
| `heads[]` | Per head: `reports`, `first`, `last`, `median_interval_s`, `longest_interval_s`, `read_dps_missing`, and the same series per DP under `dps` |

Three questions to answer from it:

1. **Coverage.** Is every head that was online for the whole window in `heads[]`? Are the heads of
   `heads_never_seen` all offline? Does it hold for both grouped and isolated heads, and for every
   gateway?
2. **Content.** Do the reports carry the DPs the entities are built from: measured temperature (24),
   active setpoint (171), heating action (3), valve (170), mode (2), window (25), battery (34), and
   the settings (30, 116, 18, 27, 118, 119)? `read_dps_missing` lists, per head, what never came.
   A DP that changes rarely (battery, a setting) can be legitimately absent over 24 h: judge it on
   the DPs that did change that day.
3. **Cadence.** Per head, `longest_interval_s` is the longest silence. Compare it with the polling
   period (90 s by default) and with what the fleet did that day: a head that is idle reports
   little. The interesting series is temperature (24), which moves all day.

### What the measure must show to start stage 4

Stage 4 would feed the coordinator from the pushed reports, drop the post-command per-device read
and lengthen the polling period. It is worth starting only if, over a full day:

- **every head online for the whole window was seen**, grouped and isolated, on every gateway;
- **the fast-changing DPs are pushed** (24, 171, 3, 170, 2, 25): none of them in
  `read_dps_never_pushed`, and missing on a head only where that head's value did not change;
- **a change is pushed promptly**: for a head whose temperature moved, the median interval of DP 24
  is of the order of minutes, not hours;
- **the link holds**: few `disconnects`, `decoded` close to `received`.

If one of these fails, the push can still complement the polling (faster echo after a write) but not
replace it, and the polling period stays as it is. Stage 4 would in any case keep a slow poll as the
reference and as the source of `online`, and would need a first phase where pushed values are only
compared with polled ones before any entity reads them.

What this measure does not tell: whether a pushed value equals the value the cloud poll returns at
the same moment (no value is kept), and how the push behaves over a session rotation longer than the
window. Both belong to stage 4's own validation.

## 14. Target routing — how much can go through cloud MQTT

A design study, not a plan of record. It answers one question: **can the cloud MQTT channel carry
everything, so the integration drops cloud HTTP and the local tunnel?** The honest answer is **no —
not as a single channel** — but a large share of the *reads* can move there. This section sets the
**target routing** operation by operation, says what must be **proven** before each move, and names
what stays on HTTP or the tunnel for good.

It builds on `docs/architecture.md` (the current routing and the "three channels, one router"
principle), `docs/interface-contract.md` (the cases R1–R7 where the cloud lies or does not act), and
the interface map above (what two real listen-only captures showed on the channel).

### 14.1 What the cloud MQTT channel is, and is not

From the captures and the codec (`api/mqtt_client.py`, `api/mqtt_publish.py`):

- It is the **app's own control-and-telemetry path**: a setting changed in the app travels here, as
  a DP publish, and the head's reports come back on the same channel.
- It is **event-driven**: reports are **per-DP deltas**, never a full state on demand. There is a DP
  query (protocol 31) seen only in static analysis, never exercised.
- **DP 199 is the richest thing on it**: ~63 % of the traffic is the head's **raw Zigbee frame** —
  the very bytes the local tunnel reads on the LAN (programming mode `0x0025`, setpoint source,
  adaptation, and the `0x40xx` attributes when something reads them). The cloud receives it too.
- It **rides the same Tuya session** as cloud HTTP (same `sign_key`/`chKey`, a distinct `deviceId`).
  It is **not** a more reliable transport than HTTP: one connection at a time, invalidated by the
  same drift, opt-in with backoff and a clean shutdown.

So MQTT is strong for *streaming state* and *pushing a command*, weak for *asking a question now*
and *knowing the shape of the fleet*.

### 14.2 The four hard blockers against a single MQTT channel

1. **No discovery, no `online`.** No gateway-level or account-level frame was ever observed: no
   device list, no home/room structure, no online/offline event. The fleet is still bootstrapped
   from the HTTP device list, and `online` lives only there.
2. **No read on demand.** MQTT pushes deltas. "What is this head's state right now?" has no MQTT
   answer without a snapshot mechanism; the per-device HTTP route is the fresh read.
3. **Preheat has no cloud DP.** The real lever is the Zigbee attribute `0x0025` bit 1, reached only
   through the tunnel. Cloud DP 1 is a gateway-cache write, **proven not to reach the head**
   (2026-11-20; `docs/preheat.md`). No capture changes this.
4. **"MQTT accepts" is not "the head acts".** The project's non-negotiable: a channel is proven for
   an operation only by a supervised write read back from an **independent** source. Several write
   DPs are proven on MQTT; most settings are not, and a publish that the broker accepts earns no
   trust on its own.

These are the same reasons `docs/architecture.md` gives for keeping three channels. A single MQTT
channel would have to defeat all four; none is a tuning detail.

### 14.3 The realistic target: a router that leans on MQTT for reads

Not one channel — the **same router, with more reads sourced from the push**, HTTP kept for
discovery and fresh reads, the tunnel kept for preheat and the unproven attribute writes. The target
per operation:

#### Reads

| What | Today | Target | Move needs |
|---|---|---|---|
| Fleet discovery, home/room structure | Cloud HTTP | **Cloud HTTP (unchanged)** | — nothing on MQTT announces the fleet |
| `online` / connectivity | Cloud HTTP (`online`) | **Cloud HTTP**, maybe helped by the account topic | Establish that the account topic carries online/offline (§14.5) |
| Fleet state (temp, mode, valve, battery, window, faults) | Cloud HTTP bulk list (conservative poll) | **Cloud MQTT push overlaid on a slow HTTP baseline** | Decode the pushed DPs (24/169, 3, 25/173, 34…) into the overlay; keep a slow HTTP poll as the floor and for heads that stay quiet |
| Tunnel-grade state (programming mode, setpoint source, adaptation, window state, `0x40xx`) | Local tunnel survey (LAN) | **Cloud MQTT via DP 199**, tunnel as fallback | Decode DP 199 inbound (reuse `api/local/tunnel.py` `decode_frame`), and accept that the push is **opportunistic**: it carries an attribute only when something reads it, so the tunnel stays the on-demand reader |
| A head just commanded | Cloud HTTP per-device route | **Cloud MQTT echo** (already matched), HTTP re-read as fallback | Already the model; widen to more DPs as they are decoded |
| App message center | Cloud HTTP `smartlife.m.msg.list` | **Cloud HTTP (unchanged)** | — not on the gateway topics |

The headline move is row 3+4: **most of the read overlay from the push**, cutting the LAN tunnel
survey and the HTTP bulk poll down to a floor and a fallback. This is faithful to the principle —
each read still comes from a source proven to carry it — and it is where the fragility of polling a
real account is reduced.

#### Writes

The write side barely moves, because the discipline for proving a write is unchanged and most
settings are not proven on MQTT. The target is to **keep routing each write to its proven channel**
and to grow the MQTT column only through the existing supervised-trial procedure.

| Operation | Today (isolated head) | Target | Move needs |
|---|---|---|---|
| Comfort / setback setpoint | Cloud MQTT (proven) + HTTP settings block | **Unchanged** | — already MQTT |
| Pause setpoint, bounds, child lock, window detection | Cloud MQTT (proven) | **Unchanged** | — already MQTT |
| Preheat | Local tunnel (`0x0025`) | **Local tunnel (unchanged)** | — no cloud DP exists (blocker 3) |
| Radiator covered, setpoint offset, regulation speed, valve exercise, external sensor, external window, load balancing, adaptation on/off | Local tunnel, closed trial | **Local tunnel**, opened per DP as its trial passes | These are `0x40xx` manufacturer attributes; a cloud DP equivalent is not established. Moving any to MQTT = a **new candidate DP + its own supervised trial** (§4) |
| Weekly schedule | Cloud HTTP (schedule-following head only) | **Cloud HTTP (unchanged)** | — no MQTT schedule write seen |
| Holiday, room management, relay binding | Cloud HTTP | **Cloud HTTP (unchanged)** | — account/room scope, not a head DP |
| Setpoint override (now) | Local tunnel (DP 171) | Local tunnel; **cloud MQTT DP 171 is a candidate** | DP 171 publish is seen outbound (§6.1); a supervised trial read back by the tunnel would prove it, and would let an isolated head take an override without the LAN |

#### Writes deliberately **not** routed to MQTT

- **Mode (DP 2).** The app's mode change does travel as DP 2 on the channel (observed), but DP 2
  `manual` erases the schedule (R4) and `at_home`/`leaving_home` are labels (R5). The integration
  writes no DP 2 on any channel; the capture does not change that.
- Anything whose only confirmation would be the **echo** of the channel written (the preheat trap):
  it needs an independent read-back or it stays closed.

### 14.4 The rule that gates every move to MQTT

Unchanged from `docs/architecture.md` — restated because it is what makes "more via MQTT" safe:

- **One DP at a time.** A DP is a **candidate** (`api.writes.MQTT_CANDIDATE_DPS`), closed, until a
  supervised write on the one designated head, **read back from a source independent of MQTT**,
  promotes it to proven (`MQTT_WRITE_DPS`) in a change of its own.
- A **read** moved to MQTT needs the same honesty: the decoded push value is shown only where it is
  understood, and a DP whose scale or meaning is not established reads unknown with the raw value as
  an attribute, exactly as the tunnel survey does today.
- No optimistic state. After a write the entity shows what the channel returns; after a read it
  shows what was decoded, dated.

### 14.5 Open questions this study leaves

To be settled before the corresponding move, each by a real capture or a supervised trial:

| Question | What settles it | Unlocks |
|---|---|---|
| Does the account topic (`<partnerIdentity>/mb/<uid>`) carry online/offline, room changes, session eviction? | A listen-only subscription to it (a change to the connector's listener, which subscribes to gateway topics only today) | Cheaper `online`, less HTTP polling |
| Does the gateway forward to the cloud the answer to **every** tunnel read, including the weekly schedule? | A listen during a `get_local_survey` with schedules | How much of the tunnel survey can be sourced from the push |
| Is DP 171 (override) proven as an MQTT write on an isolated head? | A supervised trial, read back by the tunnel | An isolated-head "now" override without the LAN |
| Does a setting's echo differ between an isolated and a grouped head? | The targeted app-change capture repeated on an **isolated** head (the first was grouped) | Confidence in the push overlay for isolated heads |
| Does the DP query (protocol 31) return a full snapshot? | A supervised write-path trial of its own (a query is a publish on the outbound topic) | A read-on-demand over MQTT — would weaken blocker 2 |

### 14.6 Verdict

- **"Everything over MQTT" is rejected**: blockers 1–3 are structural (discovery, read-on-demand,
  preheat), and blocker 4 forbids trusting unproven writes.
- **"More over MQTT" is the target**, and it is a *read* story: decode the push — above all DP 199 —
  into the overlay, keep a slow HTTP baseline and the tunnel as the on-demand reader, and let the
  account topic and DP 171 be proven next. The writes stay on their proven channels and grow only
  through the supervised trial.
- First concrete step, lowest risk, highest value: **decode DP 199 inbound from the cloud push**
  (reusing the tunnel decoder), feeding the read overlay without the LAN tunnel. Everything else in
  §14.5 is a capture or a trial that gates a later move.
