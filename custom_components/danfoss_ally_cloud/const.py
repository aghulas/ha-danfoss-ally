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

# Conservative defaults: the account's quota and security come first.
DEFAULT_SCAN_INTERVAL = 90  # seconds
DEFAULT_DISTINCT_DEVICE_ID = True
DEFAULT_ENABLE_VACATION_WRITE = False
DEFAULT_MQTT_MODE = "off"
DEFAULT_MQTT_SOURCE = "cloud"
DEFAULT_MQTT_BASE_TOPIC = "danfoss_ally_cloud"
