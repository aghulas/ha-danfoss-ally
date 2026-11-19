# Cloud MQTT DP publish (protocol 2.3) — design note

Status: **study + codec prototype** (`custom_components/danfoss_ally_cloud/api/mqtt_publish.py`,
tests `tests/test_mqtt_publish.py`, synthetic data only). **Nothing is sent**: no MQTT connection,
no write to a head. A real publish needs Rémi's explicit go-ahead (see §6). Draft PR #71.

Progress 2026-11-19 (research, off the 1.1.0 critical path): §6.1 done (branch pushed, draft PR
#71); **§6.2 DONE — the broker password is reverse-engineered and now derived in pure Python**
(cmd 2 = `md5hex(md5hex(sign_key) + ecode)`, password = `[8:24]`; see §5.1); §6.3 offline
frame-check ready; §6.4 read-only connect script prepared with the real password, not run (needs
Rémi). The scripts that touch secrets live **outside this repo**, in `~/dev/danfoss-ally-signing-re/`
(`frida/capture_cmd2.js` + `frida/run_cmd2.py`, `tools/verify_mqtt_frame.py`,
`tools/mqtt_read_only.py`).

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
  mD=false)`. **Reproduced (2026-11-19):** cmd 2 = `md5hex( md5hex(sign_key) + ecode )` (32 hex),
  password = `[8:24]`. Derived in pure Python by `mqtt_publish.mqtt_password(sign_key, ecode)`; the
  integration already holds `sign_key`. No longer a blocker.

### 5.1 Static analysis of `doCommandNative` cmd 2 (2026-11-19)

Static read of `artifacts/arm64-v8a/libthing_security.so` (jadx gave only the obfuscated Java;
the native lib is stripped, so the JNI method table was rebuilt from the RELA relocations, not
from symbols):

- JNI table (`.data.rel.ro` @ `0x16320`): `doCommandNative` → fn `0x9b9c`, `encryptPostData` →
  `0xa428`, `getEncryptoKey` → `0xa570` (the last matches the signing session's `FUN_0010a570`).
- `doCommandNative` (`0x9b9c`) dispatches on the cmd argument at `0x9e44`: **cmd 1 → worker
  `0x94c0`** (request signature), **cmd 2 → worker `0x9364`**, else error.
- The cmd-2 worker `0x9364` builds a `std::string` from `DAT_00116560` — **the same composed
  secret as sign/getEncryptoKey** (`com.danfoss.ally_<deviceId>_<appSecret1>_<appSecret2>`) — and
  combines the input (the ecode) with it via `std::string` ops. It does **not** call the AES-GCM or
  `mbedtls_md_hmac` (`0xcda8`) primitives: all four callers of `0xcda8` sit inside
  `encryptPostData`/`getEncryptoKey` (`0xa4xx`+), none in the cmd-2 subtree. So cmd 2 is a lighter,
  string-level transform of `(sign_key, ecode)`, not the standard HMAC path.
- **Resolved by runtime read (2026-11-19).** frida on the AVD (`frida/run_cmd2.py` +
  `capture_cmd2.js`, spawn + 16 s delay + unpin), **synthetic** ecodes only, app force-stopped and
  emulator killed right after. cmd 2 returned a 32-hex string for each ecode and the
  `mbedtls_md_hmac` hook never fired, confirming it is a plain digest. Matched offline against the
  real `sign_key` (4/4 vectors): **`cmd2(ecode) = md5hex( md5hex(sign_key) + ecode )`**. So the
  broker password = that output `[8:24]`. Implemented as `mqtt_publish.mqtt_password(sign_key,
  ecode)`.

All of these are secrets (sid, ecode, chKey, username, password, localKey): never logged, never in
diagnostics or the repo. `mqtt_publish.py` never puts them in a repr or an error message.

## 6. Remaining steps (in order)

1. **Password (cmd 2)** — ✅ DONE (2026-11-19, see §5.1): `md5hex(md5hex(sign_key)+ecode)[8:24]`.
2. **Frame check against the capture**: the 2026-11-19 publishes were not saved as raw bytes. In
   the next capture, dump the MQTT payload (base64) and check locally with
   `~/dev/danfoss-ally-signing-re/tools/verify_mqtt_frame.py` (key read from the secrets file,
   outside the repo; self-tested on a synthetic frame). Expected:
   `{"data":{"cid":…,"ctype":0,"dps":{"30":…}},"protocol":5,"t":…}`.
3. **Connect only** (read): TLS connect with the derived credentials, subscribe
   `smart/mb/in/<gw>` and the user topic, decode inbound frames (DP reports). No publish. Validates
   creds + decoder for real without touching a head. Script ready (not run):
   `~/dev/danfoss-ally-signing-re/tools/mqtt_read_only.py` (0 `publish()` calls by design; needs the
   §5 password and a distinct deviceId).
4. **First write** (Rémi's go-ahead, on site): one reversible DP (e.g. 30 child lock on a test head),
   check in the app and on the head, then revert. Then extend per DP, only on
   `WRITE_VERIFIED_MODELS`, with value validation before send (CLAUDE.md write safety).
5. Then: async client (aiomqtt/paho, a new requirement), one connection per entry, `SeqOrigin` per
   gateway for the whole session, reconnect on `sid` refresh; switches of PR #69 routed here when the
   tunnel is down; move the codec to pydanfoss-cloud (it already lives in `api/`).

Open questions: whether the broker accepts a second clientId for the same user; whether the gateway enforces `t` freshness; ack format on
`smart/mb/in/<gw>` (protocol 4/5 DP report expected).
