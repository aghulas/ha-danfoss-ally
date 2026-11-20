# Cloud-MQTT DP publish (protocol 2.3) — maintenance spec

Specification of the Tuya cloud MQTT path the integration uses to write an **isolated** head's
settings (those not grouped into a room), behind the `enable_cloud_mqtt` option (OFF by default).
It is the path the Danfoss app itself uses: `tuya.m.custom.wkf.settings.change` is accepted by the
cloud but **never applied** to an isolated head (W-3, docs/interface-contract.md §4.2), whereas a DP
**publish** over MQTT is. This file documents the wire format and the derivations **as implemented**
(`api/mqtt_publish.py`, `api/mqtt_client.py`) so the code stays maintainable. The reverse-engineering
method that established it is kept out of this public repository (see "Provenance" below).

## Frame (protocol 2.3)

```
header (12 bytes) = "2.3" | seq (uint32 big-endian) | origin (uint32 big-endian) | 0x00
body              = nonce (12 random bytes) | AES-GCM ciphertext | tag (16 bytes)
key               = the gateway's localKey, as ASCII bytes (16 chars -> AES-128)
plaintext (JSON)  = {"data": <data>, "protocol": <int>, "t": <epoch seconds>}   (compact, keys sorted)
```

- The 12-byte header is also the AES-GCM **additional authenticated data** (AAD); the nonce is
  prepended to the ciphertext.
- `protocol` = **5** for an outbound DP publish; inbound DP reports arrive as **4**.
- Encode/decode: `mqtt_publish.encode_frame` / `decode_frame`. A frame that fails to authenticate is
  rejected (wrong localKey or tampering).

## Addressing

- Topics: publish to `smart/mb/out/<gateway devId>`; the gateway answers on
  `smart/mb/in/<gateway devId>`. The topic carries the **gateway** devId, not the head's.
- `data` for a Zigbee sub-device (a head): `{"cid": <head node_id>, "ctype": 0, "dps": {<dp>: <v>}}`
  (`mqtt_publish.dp_publish_data`). `cid` is the head's Zigbee node id.

## Sequence / de-duplication

The receiver drops a repeated `(seq, origin)` pair ("cloud command repeat"). `origin` is random per
session, `seq` increments before each publish. Keep one `SeqOrigin` per gateway for the whole
session and never reset it mid-session (`mqtt_publish.SeqOrigin`, one per gateway in
`CloudMqttLink`).

## Broker and credentials (as implemented)

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

## Session policy (observed)

The broker allows **one active MQTT connection per session**. Two clients that present the **same**
session (same `sid`/`ecode`, hence the same username) conflict; two **different** sessions coexist.
The integration therefore connects with **its own** session (distinct deviceId), independent of the
Danfoss app's and the MCP connector's. Confirmed on real hardware: the integration's session is
accepted (`CONNACK rc=0`) while the phone app stays connected.

## Write and confirmation

`CloudMqttLink.publish_dp` sends the frame and `await_confirmation` waits for the gateway's inbound
protocol-4 `{cid, dps}` echo (matched on `cid` + the written DP/value) within a timeout; the entity
then falls back to a cloud re-read, and raises a clear error if still unconfirmed — never an
optimistic state. A link that is down makes the dependent switches and numbers unavailable.

## Link lifecycle (hardening)

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

## Validation status

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
  changed. The DP 116 "on" write ran on 1.2.0-rc1 and all the others on 1.2.0-rc2, whose
  cloud-MQTT write code is identical.
- **Supervised writes of 2026-11-19 (night) and 2026-11-20 (morning)**, on one isolated head
  following its weekly schedule, written once and restored: DP 119 (setback setpoint) and
  DP 118 + 16 (comfort setpoint), read back through the local tunnel (current setpoint and weekly
  schedule) and in the app. The head carried each new value into its own schedule transitions
  about a minute after the write; DP 16 set the current setpoint at once and the head returned to
  its schedule within five minutes. Every call returned in under a second. Build 1.2.0-rc4.
- **Scope today**: the MQTT write path carries **DP 30, 116, 18, 27, 120, 118, 16 and 119** as
  proven (`api.writes.MQTT_WRITE_DPS`). DP 1 (preheat) is implemented as a **candidate**
  (`MQTT_CANDIDATE_DPS`), closed, with a rule of its own: its write is
  confirmed by the local tunnel's read of attribute 0x0025 only, never by the echo or the cloud.
  Its supervised write of 2026-11-20 was **not passed** (the cloud's DP 1 changed, the head did
  not), so it stays closed (docs/cloud-mqtt-preheat-proposal.md). Other DPs (133/101 mounting/orientation) are added one at
  a time, each as a candidate first (docs/first-write-procedure.md).

## Provenance

The method used to recover this protocol (app decompilation, dynamic instrumentation, and the
credential/frame captures) is **not** in this public repository. It lives in the maintainer's
private research notes. This file is the maintenance specification only.
