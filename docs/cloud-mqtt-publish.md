# Cloud MQTT DP publish (protocol 2.3) — design note

Status: **study + codec prototype** (`custom_components/danfoss_ally_cloud/api/mqtt_publish.py`,
tests `tests/test_mqtt_publish.py`, synthetic data only). **Nothing is sent**: no MQTT connection,
no write to a head. A real publish needs Rémi's explicit go-ahead (see §6).

## 1. Why

Real-hardware validation W-3 showed that `tuya.m.custom.wkf.settings.change` is accepted but not
applied for an isolated head. The app capture of 2026-11-19 showed that the Danfoss app writes
**every** head setting (DP 1 preheat, 30 lock, 116 window, 133 mounting, 101 view direction, 18/27
bounds, 118+16 comfort, 119 setback, 120 pause) with `AbsThingDevice.publishDps({dp: value})` →
`publishDpsInPipeline` → **Tuya cloud MQTT**, topic `smart/mb/out/<gateway devId>`, protocol 2.3.
`settings.change` only runs in parallel for `{1, 118, 119, 121}` (cloud workflow store). See
`docs/interface-contract.md` §4.2 (PR #69).

## 2. Sources (decompiled Danfoss app, Thing SDK)

APK `~/dev/danfoss-app-capture/play/com.danfoss.ally.apk`, decompiled per dex with jadx
(`classes4.dex` MQTT + device, `classes5.dex` utils/config beans, `classes9.dex` interior beans,
`classes3.dex` user config). Classes are obfuscated; the `compiled from` names are:

| Role | Class (obfuscated) | Original name |
|---|---|---|
| 2.3 encoder | `sdk.mqtt.qpbpqpq` | `MqttControl2_3` |
| JSON + AES helpers | `sdk.mqtt.qqddbpb` | `PublishMapper` |
| AES-GCM | `smart.android.common.utils.AesGcmUtil` | — |
| 2.3 decoder | `sdk.mqtt.qbpppdb` | `MsgProtocol2_3` (jadx fallback mode) |
| version dispatch | `sdk.mqtt.qbqqdqq` | `MqttControlModel` |
| builder → publish | `sdk.mqtt.qdpppbq.publishDevice` | `MqttServerManager` |
| DP publish data | `sdk.device.dqdpbbd.sendCommand` / `bdpdqbp(String,String,int,JSONObject)` | — |
| protocol numbers | `sdk.device.dddbppd` | — |
| (seq, origin) | `smart.interior.device.confusebean.SandO` | — |
| broker creds (SDK app) | `sdk.mqtt.dqqbdqb` | `SdkMqttCertificationInfo` |
| connect config | `sdk.config.UserConfigSessionLogoutManager.getMqttConfigInfo` | — |
| MQTT options | `sdk.mqtt.qdpppbq.initMqttConfig`, `sdk.mqttmanager.model.bdpdqbp.reinitialize` | — |

## 3. Frame 2.3

```
header (12 B) = "2.3" | seq uint32 BE | origin uint32 BE | 0x00        ← also the GCM AAD
body          = nonce (12 random B) | AES-GCM ciphertext | tag (16 B)
key           = gateway localKey as ASCII bytes (16 chars → AES-128)
plaintext     = {"data":<data>,"protocol":<int>,"t":<epoch s>}       (fastjson: fields sorted, compact)
```

- Encoder: `MqttControl2_3` concatenates `pv.getBytes()`, `intToBytes2(s)`, `intToBytes2(o)`, `{0}`
  (`intToBytes2` = 4 bytes big-endian), encrypts `PublishBean2_3` with
  `AesGcmUtil.encryptBytes2BytesAppendNonce(localKey.getBytes(), json, header)` (nonce first, then
  ciphertext‖tag, 128-bit tag), and prepends the header.
- Decoder (`MsgProtocol2_3`): splits 3+4+4+1, reads `sequence` and `origin`, **drops a repeated
  (seq, origin)** (`"cloud command repeat"`, 12003), then decrypts `frame[12:]` with AAD = header.
  So inbound `smart/mb/in/<gw>` frames have the same layout and the gateway very likely applies the
  same replay check.
- `seq`/`origin` (`SandO`): `origin` random in [1000, 1 001 000) per device and process, `seq`
  starts at 2 and is incremented before each publish (first frame = 3). The builder sets
  `Sn = s` as well (not in the frame).
- `t` = `TimeStampManager.getCurrentTimeStamp()` cast to int → epoch **seconds** (server-synced).
- Only pv 2.3 is implemented; 2.2/2.1 use AES-ECB with other layouts (`MqttControl2_2/2_1`) and are
  refused, not guessed. The gateway's `pv` comes from the device list (`DeviceBean.getPv()`).

## 4. Addressing the head

`sendCommand(gwDevId, dps, localId=nodeId, ctype, mbid, sandO)` looks up the **gateway** bean (pv,
localKey) and builds, for a Zigbee sub-device:

```json
{"data": {"cid": "<head node id>", "ctype": 0, "dps": {"30": true}}, "protocol": 5, "t": 1763…}
```

- topic `smart/mb/out/<gateway devId>` (the head's `mesh_id`), key = gateway localKey (already
  fetched by `keys.async_fetch_gateway_keys`), `cid` = head node id (`DanfossDevice.node_id`, the
  same `cid` the local tunnel uses), `ctype` = 0 on the plain DP path, `mbid` omitted when empty.
- protocol 5 = DP publish (`dddbppd`; 22 = variant, 31 = DP query, 63 = sub-device add/cancel).
- The app subscribes to `smart/mb/in/<gw>` before publishing (to receive the ack / DP report).
- MQTT: QoS 1, not retained, clean session, keep-alive 60 s.

## 5. Broker and credentials

- Broker: `ssl://<mobileMqttsUrl>:8883`, `mobileMqttsUrl` from the region domain config
  (`User.domain` in the login response; EU = `m1.tuyaeu.com`, already seen in captures).
- Config (`getMqttConfigInfo`, appTag `"os"`): `uid`, `ecode`, `partnerIdentity`, `token = sid`,
  all from the login `User` the integration already receives.
- **clientId** = `com.danfoss.ally_mb_<deviceId>_<md5hex(uid + "sdkfasodifca")>_DEFAULT`.
  Same deviceId as the app ⇒ same clientId ⇒ the broker kicks one of them. Use the distinct deviceId
  (`derive_distinct_device_id`) as for the HTTP session conflict.
- **username** (Danfoss is an SDK app, `ThingSmartNetWork.mSdk = true` → `SdkMqttCertificationInfo`):
  `<partnerIdentity>_v1_<appId>_<chKey>_mb_<sid><last16(md5hex(md5hex(appId) + ecode))>`
  where `appId = ThingSmartNetWork.mAppId` (= HTTP `clientId`) and `chKey =
  getChKey(ctx, appId)` — **the same native call that fills the HTTP `chKey` parameter**
  (`ThingApiParams`), i.e. the installation chKey the config flow already stores.
  (`md5AsBase64` is misnamed: lowercase MD5 hex.)
- **password** = middle 16 chars of `ThingNetworkSecurity.doCommandNative(ctx, 2, ecode, null,
  mD=false)`. **Command 2 of libthing_security is not reproduced yet** (cmd 1 = request signature is).
  This is the only blocker for a pure-Python client.

All of these are secrets (sid, ecode, chKey, username, password, localKey): never logged, never in
diagnostics or the repo. `mqtt_publish.py` never puts them in a repr or an error message.

## 6. Remaining steps (in order)

1. **Password (cmd 2)**, no write involved: one frida RPC on the AVD (`danfoss34`, app attached,
   `sign_oracle.js` already exposes `doCommandNative(ctx, cmd, data)`) with **synthetic** ecodes, then
   match a static formula (candidates: HMAC-SHA256 / MD5 keyed by the app secret, as for cmd 1).
   ⚠ Launching the app on the emulator invalidates the integration's session (shared deviceId):
   do it when Rémi is there.
2. **Frame check against the capture**: the 2026-11-19 publishes were not saved as raw bytes. In
   the next capture, dump the MQTT payload (base64) and check locally (outside the repo, key read
   from the secrets file) that `decode_frame(localKey, payload)` gives
   `{"data":{"cid":…,"ctype":0,"dps":{"30":…}},"protocol":5,"t":…}`.
3. **Connect only** (read): TLS connect with the derived credentials, subscribe
   `smart/mb/in/<gw>` and the user topic, decode inbound frames (DP reports). No publish. Validates
   creds + decoder for real without touching a head.
4. **First write** (Rémi's go-ahead, on site): one reversible DP (e.g. 30 child lock on a test head),
   check in the app and on the head, then revert. Then extend per DP, only on
   `WRITE_VERIFIED_MODELS`, with value validation before send (CLAUDE.md write safety).
5. Then: async client (aiomqtt/paho, a new requirement), one connection per entry, `SeqOrigin` per
   gateway for the whole session, reconnect on `sid` refresh; switches of PR #69 routed here when the
   tunnel is down; move the codec to pydanfoss-cloud (it already lives in `api/`).

Open questions: whether the broker accepts a second clientId for the same user; whether the gateway enforces `t` freshness; ack format on
`smart/mb/in/<gw>` (protocol 4/5 DP report expected).
