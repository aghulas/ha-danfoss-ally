"""Constants of the Danfoss Ally (Cloud) integration.

The DEVICE / PROTOCOL constants (DP codes, setpoint bounds, allowed models, Zigbee attribute) live
in the reusable `api/const.py` layer (future pydanfoss-cloud library) and are re-exported here for
the rest of the integration. This file keeps only what is HA-specific (domain, platforms, data
keys, config options).
"""

from __future__ import annotations

from .api.const import (  # noqa: F401 - re-export for the integration (device/protocol)
    DP_AT_HOME_SETPOINT,
    DP_CHILD_LOCK,
    DP_COMFORT_SETPOINT,
    DP_HEAT_DEMAND,
    DP_HOLIDAY_SETPOINT,
    DP_LEAVING_HOME_SETPOINT,
    DP_LOWER_TEMP,
    DP_MANUAL_SETPOINT,
    DP_ORIENTATION,
    DP_PAUSE_SETPOINT,
    DP_PREHEAT,
    DP_SETBACK_SETPOINT,
    DP_SETPOINT,
    DP_TEMP_SET,
    DP_UPPER_TEMP,
    DP_VIEWING_DIRECTION,
    DP_WINDOW_DETECT,
    MODE_GROUP_SETPOINT_DP,
    MODE_SETPOINT_DP,
    ORIENTATION_VALUES,
    SETPOINT_MAX,
    SETPOINT_MIN,
    SETPOINT_STEP,
    WRITE_VERIFIED_MODELS,
    WRITE_VERIFIED_PRODUCTS,
    ZB_ATTR_PROGRAMMING_MODE,
)

DOMAIN = "danfoss_ally_cloud"

# Exposed platforms. v0.2: climate (setpoint) + sensors + switch (child lock, window detection).
# number comes with other numeric settings (max setpoint...).
PLATFORMS = ["climate", "sensor", "binary_sensor", "switch", "number", "select", "time"]

# Keys of hass.data[DOMAIN][entry_id].
DATA_COORDINATOR = "coordinator"
DATA_LOCAL = "local_coordinator"  # local fallback (tunnel), None if enable_local is off
DATA_MQTT = "mqtt_publisher"  # MQTT publisher, None if mqtt_mode = off
DATA_JOBS = "jobs"  # in-memory queue of write jobs (WriteJob)
DATA_SCHEDULES = "schedules"  # per-target schedule cache (read on demand)
DATA_VACATION_WRITE = "vacation_write"  # bool: vacation-write gate (CONF_ENABLE_VACATION_WRITE)
DATA_HEAD_UNBIND = "head_unbind"  # bool: head-unbind gate (CONF_ENABLE_HEAD_UNBIND)
DATA_CLOUD_MQTT = "cloud_mqtt"  # bool: cloud-MQTT isolated-head write gate (CONF_ENABLE_CLOUD_MQTT)
DATA_MQTT_LINK = "cloud_mqtt_link"  # CloudMqttLink | None: live link, created only on a gated step
# frozenset[int]: candidate DPs opened on the cloud-MQTT write path for a supervised trial.
DATA_MQTT_SUPERVISED_DPS = "cloud_mqtt_supervised_dps"
# str | None: device id of the ONE head the supervised trial is restricted to.
DATA_MQTT_SUPERVISED_HEAD = "cloud_mqtt_supervised_head"
# frozenset[str]: Danfoss head settings opened for a supervised trial of their LOCAL-TUNNEL write.
DATA_LOCAL_SUPERVISED_SETTINGS = "local_supervised_settings"
# str | None: device id of the ONE head that local-tunnel trial is restricted to.
DATA_LOCAL_SUPERVISED_HEAD = "local_supervised_head"
DATA_MQTT_COVERAGE = "cloud_mqtt_coverage"  # CoverageStats | None: only with cloud_mqtt_probe on
DATA_MESSAGES = "messages_coordinator"  # DanfossMessageCoordinator: the app's message center

# Message center of the app (docs/message-center.md): its own, slow poll, independent from the
# device poll. Messages are rare (a few a week on a 60-head account) and one read returns the
# whole list, so every 30 min costs 48 light calls a day.
MESSAGES_SCAN_INTERVAL = 1800  # seconds
# Device alerts kept in the sensor's attributes (newest first); the full list stays in memory only.
MESSAGES_RECENT = 10
# HA event fired once per NEW device alert (not for the backlog seen at the first start).
EVENT_MESSAGE = "danfoss_ally_cloud_message"

# LOCAL survey (Zigbee tunnel) interval: slow, ~8 s per head. Distinct from the cloud polling.
DEFAULT_LOCAL_SCAN_INTERVAL = 900  # seconds
# LOCAL settings pass (Danfoss attributes: orientation, radiator covered...): two more frames per
# head, for values that hardly ever change. At most once per interval, after a preheat survey.
LOCAL_SETTINGS_INTERVAL = 86400  # seconds

# --- Installation credentials and secrets (config_flow / options_flow) ---
# username/password/country_code: the app account's credentials (path-1a login).
# sign_key/device_id/ch_key: INSTALLATION material captured once (see README), stable, essential
# to the signature and encryption. SECRETS: never logged.
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_COUNTRY_CODE = "country_code"  # country calling code, e.g. "33" (France)
CONF_REGION = "region"  # datacenter: "eu" | "us" | "cn" | "in"
CONF_SIGN_KEY = "sign_key"
CONF_DEVICE_ID = "device_id"
CONF_CH_KEY = "ch_key"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLE_LOCAL = "enable_local"
# Coexistence: use a deviceId distinct from the app's / the MCP connector's captured one (same
# sign_key/chKey), so the integration keeps its own Tuya session instead of stealing theirs
# (docs/architecture.md). On by default; turn off only to reproduce the legacy shared-session
# behaviour. Changing it re-logs in with the other deviceId on the next reload.
CONF_DISTINCT_DEVICE_ID = "distinct_device_id"
CONF_MQTT_MODE = "mqtt_mode"  # "off" | "discovery" | "zigbee2mqtt"
CONF_MQTT_SOURCE = "mqtt_source"  # "cloud" | "local"
CONF_MQTT_BASE_TOPIC = "mqtt_base_topic"
# Vacation (holiday) WRITE gate. A vacation write acts on the live heating and its exact request
# shape is pending a real-hardware validation (Rémi present), so it is OFF by default: the vacation
# write services refuse (`vacation_disabled`) until it is deliberately enabled for a validation
# session. Reads (holiday active / setpoint) are unaffected.
CONF_ENABLE_VACATION_WRITE = "enable_vacation_write"
# Head UNBIND (disconnect) WRITE gate. Unbinding a head is the most DESTRUCTIVE cloud write: the
# head leaves the Zigbee network and disappears from the account, and re-pairing requires a physical
# action on site (not drivable from here). The cloud call itself was captured and validated on real
# hardware (via the MCP connector, 2026-11-18), but it has NOT been validated through this HA
# integration yet, so it is OFF by default: the disconnect_head service refuses (`unbind_disabled`)
# until it is deliberately enabled for a supervised validation session. See docs/roadmap.md.
CONF_ENABLE_HEAD_UNBIND = "enable_head_unbind"
# Post-command refresh (R-3). The bulk ``device.list`` poll lags for minutes after a command, so a
# just-changed head (valve, pi_heating_demand, work_state, active setpoint) and especially a write
# round-trip stay frozen on the old state in HA / MQTT. When ON, a head commanded in the last
# POST_COMMAND_REFRESH_TTL seconds is refreshed through the per-device route (fresher) on each poll,
# bounded by POST_COMMAND_REFRESH_MAX_HEADS reads per poll, then falls back to the bulk route. OFF
# by default: it adds a per-device read pattern on the user's real account, and that this route is
# fresher than the bulk list for a head is pending a real-hardware validation (see
# docs/roadmap.md) — enable it for that validation session.
CONF_POST_COMMAND_REFRESH = "post_command_refresh"
# Cloud-MQTT isolated-head WRITE path (EXPERIMENTAL, R&D). The Danfoss app writes an isolated head's
# settings by publishing the DP over Tuya cloud MQTT (not `settings.change`, which the cloud accepts
# but never applies — W-3). The frame codec and credential derivation are reverse-engineered and
# validated (decoder on 6/6 real frames, credentials byte-exact vs the app; docs/cloud-mqtt-channel
# .md), but NO publish to a real head has been validated yet. OFF by default: when ON, an isolated
# head's child-lock / window-detection switch may route through a dedicated-session MQTT link
# instead of being unavailable. Enable only for a supervised validation session (Rémi present).
CONF_ENABLE_CLOUD_MQTT = "enable_cloud_mqtt"
# Coverage measure of the Tuya cloud MQTT push (roadmap stage 3), LISTEN-ONLY. OFF by default. When
# ON, the cloud-MQTT link is opened (listen-only unless ``enable_cloud_mqtt`` is also on: one
# connection per session, so both share it) and every decoded inbound frame is accounted per head
# and per DP: counts, first and last instant, intervals. Aggregates only, served by the diagnostics
# with no identifier. It settles whether the push could become a read source (stage 4). A link that
# is listen-only closes itself after CLOUD_MQTT_PROBE_MAX_SECONDS, so a forgotten option does not
# keep a broker connection open on the user's account. See docs/cloud-mqtt-channel.md.
CONF_CLOUD_MQTT_PROBE = "cloud_mqtt_probe"

# Conservative defaults: the account's quota and security come first.
DEFAULT_SCAN_INTERVAL = 90  # seconds
DEFAULT_DISTINCT_DEVICE_ID = True
DEFAULT_ENABLE_VACATION_WRITE = False
DEFAULT_ENABLE_HEAD_UNBIND = False
DEFAULT_POST_COMMAND_REFRESH = False
DEFAULT_ENABLE_CLOUD_MQTT = False
# Candidate DPs opened on the cloud-MQTT write path for a SUPERVISED trial (a list of DP numbers as
# strings; EMPTY by default). A candidate (``api.writes.MQTT_CANDIDATE_DPS``) is implemented but
# not proven on real hardware: it stays closed, whatever ``enable_cloud_mqtt`` says, until it is
# listed here for its supervised first write (docs/first-write-procedure.md). Entries that are not
# candidates (unknown, or since promoted to proven) are ignored.
CONF_CLOUD_MQTT_SUPERVISED_DPS = "cloud_mqtt_supervised_dps"
# The ONE head a supervised trial applies to (its device id; EMPTY by default). The candidate DPs
# listed above open on this head ONLY: every other head keeps its normal routing, so an automation
# or a click elsewhere can never go out through the channel under trial. With no head designated
# no candidate opens anywhere, whatever is listed. A real device identifier: redacted in the
# diagnostics, never logged.
CONF_CLOUD_MQTT_SUPERVISED_HEAD = "cloud_mqtt_supervised_head"
# Danfoss head settings whose LOCAL-TUNNEL write is opened for a SUPERVISED TRIAL (a list of setting
# keys, ``local_write.LOCAL_TRIAL_SETTINGS``; EMPTY by default): radiator covered (0x4016),
# setpoint offset (0x404B), regulation speed (0x4020), valve exercise day / time (0x4010 / 0x4011),
# external measured room sensor (0x4015), external window open (0x4003), load balancing (0x4032).
# None is proven on real hardware: each write entity exists only while its setting is listed here,
# ``enable_local`` is on, and only for the ONE head chosen below (docs/first-write-procedure.md).
CONF_LOCAL_SUPERVISED_SETTINGS = "local_supervised_settings"
# The ONE head that local-tunnel trial applies to (its device id; EMPTY by default). With no head
# designated nothing opens, whatever is listed. A real device identifier: redacted in the
# diagnostics, never logged.
CONF_LOCAL_SUPERVISED_HEAD = "local_supervised_head"
DEFAULT_CLOUD_MQTT_PROBE = False
CLOUD_MQTT_PROBE_MAX_SECONDS = 48 * 3600  # a listen-only link closes itself after two days
# How long a commanded head stays "hot" (refreshed via the per-device route) after a write, and the
# cap on per-device reads per poll (so commanding a large room cannot burst the API). A hot head
# costs one extra read per poll for at most this window, then returns to the bulk route.
POST_COMMAND_REFRESH_TTL = 300  # seconds
POST_COMMAND_REFRESH_MAX_HEADS = 12
# Settle delay after a command. The cloud takes the command into account in about 15 s (observed
# 2026-11-19: a room setting was on both heads ~15 s after the write); a per-device read before that
# returns the PRE-command state and left the written entity one write behind until the next poll
# (rc1 finding). So a commanded head is not overlaid during this delay (the bulk value is kept), and
# one extra refresh is scheduled when it ends: the result shows up in ~15 s instead of a full poll.
POST_COMMAND_SETTLE = 15  # seconds
DEFAULT_MQTT_MODE = "off"
DEFAULT_MQTT_SOURCE = "cloud"
DEFAULT_MQTT_BASE_TOPIC = "danfoss_ally_cloud"

# v2.x MQTT Companion mode (docs/companion-contract.md)
CONF_CONNECTION_MODE = "connection_mode"
CONNECTION_MODE_CLOUD = "cloud"
CONNECTION_MODE_MQTT_COMPANION = "mqtt_companion"
CONF_MQTT_PREFIXES = "mqtt_prefixes"
DEFAULT_MQTT_PREFIXES = "zigbee2mqtt,danfoss2mqtt"
# Tick of the Companion's virtual-room feeds (companion_rooms.async_sync_telemetry). 6 min: longer
# than the 5-min per-head floor of the external-sensor feed (so consecutive ticks always clear it),
# and short enough that the 20-min keep-alive lands at 24-26 min, under the head's 30-min deadline.
COMPANION_TELEMETRY_INTERVAL = 360  # seconds
# The two periodic feeds to Zigbee2MQTT heads of a virtual room, each behind its own option
# (docs/z2m-cloud-parity.md §4). Closed by default; see __init__._async_setup_companion_entry for
# the one-time carry-over of an install that was already feeding its heads from a room sensor.
CONF_COMPANION_FEED_EXTERNAL_SENSOR = "companion_feed_external_sensor"
DEFAULT_COMPANION_FEED_EXTERNAL_SENSOR = False
CONF_COMPANION_FEED_LOAD_MEAN = "companion_feed_load_mean"
DEFAULT_COMPANION_FEED_LOAD_MEAN = False
