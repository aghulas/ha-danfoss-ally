# Message center (the app's "Messages" screen) — read route and format

The Danfoss Ally app shows a message center (low battery, device added/removed, firmware update,
new login on the account…). It is the Tuya message center, reachable through the same signed
mobile API as the rest of path 1a. **Read-only**: this integration never marks a message read
and never deletes one.

Established on 2026-11-21 against the real account (session under the connector's distinct
deviceId), read-only. Everything below is anonymised.

## How the route was found

- The account-level **notification switches** (`smartlife.m.msg.notice.switch.status`, exposed
  by the MCP connector as `danfoss_tuya_notifications`) only say which categories push to the
  phone, not the messages themselves.
- The app's dex (`~/dev/danfoss-ally-signing-re/artifacts/dex`) carries the message-center
  methods under the SDK's `thing.m.msg.*` names: `list`, `list.by.json`, `days.by.json`,
  `maxtime`, `new`, `read.all`, `read.batch`, `remove`, `notice.*`. As for every `m.*` call, the
  SDK rewrites `thing.` to `smartlife.` before signing (see `smartlife.m.device.reset`).
- Version grid, probed read-only (`read.*` and `remove` were **not** called):

| Method | Version | Result |
| --- | --- | --- |
| `smartlife.m.msg.list` | 1.0 | `API_OR_API_VERSION_WRONG` |
| `smartlife.m.msg.list` | **2.0** | **list of every message, newest first** |
| `smartlife.m.msg.list` | 3.0 / 4.0 | `{datas: [], pageNo, totalCount: 0}` with `msgType/offset/limit`; `REMOTE_API_PARAM_ALL_INPUT_LOSS` with `pageNo/pageSize` (paged variant, parameters not found) |
| `smartlife.m.msg.new` | 1.0 | `{alarm: bool, family: bool, notification: bool}` (the app's "new" badges) |
| `smartlife.m.msg.maxtime` | 1.0 | epoch seconds of the newest message |
| `smartlife.m.msg.list.by.json`, `days.by.json` | 1.0–4.0 | input-loss / server error (parameters unknown) |

`tuya.m.msg.list` answers exactly like `smartlife.m.msg.list`.

**v2.0 ignores `msgType`, `offset` and `limit`**: it always returns the whole list (34 messages
on the real account, spanning about four weeks). The integration therefore calls it without a
body and does the filtering itself.

## Format (v2.0, one element)

Anonymised sample of a device alert:

```json
{
  "id": 2100000000000000001,
  "idStr": "2100000000000000001",
  "time": 1793470865,
  "dateTime": "2026-10-31 18:21",
  "msgType": 4,
  "msgTypeContent": "Low Battery Warning",
  "msgTitle": "Low Battery Warning",
  "msgCode": "SMART_MSG_V3",
  "bigMsgType": 1,
  "msgContent": "Your radiator thermostat <room> #1 is experiencing a low battery level, please consider changing it's battery soon. …",
  "msgSrcId": "<devId of the head>",
  "homeId": "<gid>",
  "homeName": "<home name>",
  "readStatus": 0,
  "uid": "<account uid>",
  "sceneId": "<opaque>",
  "icon": "<url>",
  "actionURL": "<url>",
  "isExpirePics": false,
  "isExpireVideos": "<opaque>",
  "isHandleRosettaTemplate": false,
  "isNeedPullEncKey": false
}
```

| Field | Meaning | Used by the integration |
| --- | --- | --- |
| `idStr` | message id as a string (`id` is an int above 2^53: **use `idStr`**) | dedup key only, never exposed |
| `time` | epoch seconds (UTC) | yes, timestamp |
| `dateTime` | local wall time of the account, day not zero-padded (`2026-11-4 16:07`) | no (derive from `time`) |
| `msgType` / `msgTypeContent` | category (see below) | yes |
| `msgCode` | template code | yes |
| `msgTitle` | present on alerts only | yes, else falls back to `msgTypeContent` |
| `msgContent` | rendered text in the account language (contains device / room names) | yes |
| `msgSrcId` | **devId of the head concerned** (checked: every alert's `msgSrcId` is a devId of the account; removed devices give an unknown id) | mapped to the HA device, never exposed raw |
| `bigMsgType` | `1` on device alarms | yes (alert flag) |
| `homeId`, `homeName` | home of the device, only on some messages | no |
| `readStatus` | `0` on all 34 messages of the real account while `msg.new` reports no new message: **meaning unconfirmed** (not a usable unread flag) | exposed as is, not interpreted |
| `uid`, `sceneId`, `icon`, `actionURL`, `isExpire*`, `isHandle*`, `isNeedPullEncKey` | account / template plumbing | dropped |

Categories seen on the real account:

| `msgType` | `msgTypeContent` | `msgCode` | Example |
| --- | --- | --- | --- |
| `4` | Low Battery Warning | `SMART_MSG_V3` (`bigMsgType: 1`) | low battery on a head |
| `-1` | Home Message | `ADD_SUB_DEVICE_FOR_LOCATION_MSG_V2` | "Danfoss Ally™ Radiator Thermostat … can be used now." |
| `-1` | Home Message | `DEVICE_USER_DELETE_MSG_V2` | "… removed <head name>." |
| `-1` | Home Message | `MSG_CENTER_UPGRADE_INFO_INFORM_CLIENT_V3_*` | Zigbee module firmware update done |
| `0` | System Notification | `LOGIN_MSG_CENTER` | a new phone/session logged in (the connector's and the integration's own logins show up here) |

No "device offline" message was present on the account at the time; by Tuya's convention it is
an alarm like the low-battery one (`msgType > 0`, `SMART_MSG_*`). The integration treats
`msgType > 0` or `bigMsgType == 1` as a **device alert**, everything else as information.

## What the integration does with it

See `coordinator.DanfossMessageCoordinator` and `sensor.py` (`DanfossMessagesSensor`):

- a dedicated, slow poll (`MESSAGES_SCAN_INTERVAL`, 30 min) of `smartlife.m.msg.list` v2.0,
  independent from the device poll; a failed read makes only the message sensor unavailable;
- **only device alerts count**: `bigMsgType == 1` or `msgType > 0` (low battery today; offline
  and faults are expected to share the shape). New logins (`msgType` 0, which include the
  connector's and this integration's own re-logins) and home messages (`msgType` -1: device
  added/removed, firmware update) are noise for HA: they appear neither in the sensor nor in the
  event;
- one account-level sensor: state = time of the latest device alert, attributes `alert_count`,
  `last_alert` and the 10 most recent `alerts`, without any identifier (`idStr`, `uid`,
  `msgSrcId`, `homeId`, URLs are dropped; the head is given by its HA name);
- an HA event `danfoss_ally_cloud_message` per **new device alert**, with the HA `device_id` of
  the head when known and the raw `msg_type` / `big_msg_type` (to filter on a type not named
  yet). Filtering is done by the integration rather than left to the user, because a login
  message is fired at every re-login of the integration itself;
- "new" is decided by a **high-water mark**, never by `readStatus` (no read notion: `read.*` is
  never called): the newest `time` seen plus SHA-256 digests of the `idStr` at that second
  (`idStr` kept as a string, never an int). It is persisted per entry in `.storage`, so an alert
  arriving while HA is down fires at the next start; with no stored mark (first start) the
  backlog only seeds it. It never moves backwards;
- diagnostics: counts per category, codes and newest time only (no text, no id);
- no persistent notification.
