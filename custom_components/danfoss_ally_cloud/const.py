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
    DP_MANUAL_SETPOINT,
    DP_PAUSE_SETPOINT,
    DP_PREHEAT,
    DP_SETBACK_SETPOINT,
    DP_SETPOINT,
    DP_TEMP_SET,
    DP_UPPER_TEMP,
    DP_WINDOW_DETECT,
    MODE_GROUP_SETPOINT_DP,
    MODE_SETPOINT_DP,
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
PLATFORMS = ["climate", "sensor", "binary_sensor", "switch", "number"]

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
DATA_MQTT_PROBE = "cloud_mqtt_probe"  # CloudMqttListener | None: the listen-only probe, when on

# LOCAL survey (Zigbee tunnel) interval: slow, ~8 s per head. Distinct from the cloud polling.
DEFAULT_LOCAL_SCAN_INTERVAL = 900  # seconds

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
# validated (decoder on 6/6 real frames, credentials byte-exact vs the app; docs/cloud-mqtt-publish
# .md), but NO publish to a real head has been validated yet. OFF by default: when ON, an isolated
# head's child-lock / window-detection switch may route through a dedicated-session MQTT link
# instead of being unavailable. Enable only for a supervised validation session (Rémi present).
CONF_ENABLE_CLOUD_MQTT = "enable_cloud_mqtt"
# Cloud-MQTT LISTEN-ONLY probe (R&D diagnostic, distinct from the write gate above). When ON, the
# integration opens ONE read-only Tuya cloud MQTT connection from ITS OWN session (its distinct
# deviceId — no secret is taken from HA storage), subscribes to smart/mb/in/<gw> for the known
# gateways, decodes inbound frames, and records a redacted result in diagnostics. It has NO publish
# path at all (a listener class with no send method, not just a flag). It auto-stops after
# CLOUD_MQTT_PROBE_MAX_SECONDS and when the option is turned off. Purpose: measure whether an
# independent session is accepted by the broker while the phone app is connected (coexistence) —
# CONNACK rc + per-gateway frame counts land in diagnostics. OFF by default; enable only for a
# supervised validation window. See docs/cloud-mqtt-probe.md.
CONF_ENABLE_CLOUD_MQTT_PROBE = "cloud_mqtt_probe"

# Conservative defaults: the account's quota and security come first.
DEFAULT_SCAN_INTERVAL = 90  # seconds
DEFAULT_DISTINCT_DEVICE_ID = True
DEFAULT_ENABLE_VACATION_WRITE = False
DEFAULT_ENABLE_HEAD_UNBIND = False
DEFAULT_POST_COMMAND_REFRESH = False
DEFAULT_ENABLE_CLOUD_MQTT = False
DEFAULT_ENABLE_CLOUD_MQTT_PROBE = False
CLOUD_MQTT_PROBE_MAX_SECONDS = 600  # the listen-only probe auto-stops after this (10 min)
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
