"""Constantes de l'intégration Danfoss Ally (Cloud).

Les constantes APPAREIL / PROTOCOLE (codes DP, bornes de consigne, modèles autorisés, attribut
Zigbee) vivent dans la couche réutilisable `api/const.py` (future bibliothèque pydanfoss-cloud) et
sont ré-exportées ici pour le reste de l'intégration. Ce fichier ne garde que le propre de HA
(domaine, plateformes, clés de données, options de configuration).
"""

from __future__ import annotations

from .api.const import (  # noqa: F401 - ré-export pour l'intégration (device/protocole)
    DP_AT_HOME_SETPOINT,
    DP_CHILD_LOCK,
    DP_CONSIGNE_CONFORT,
    DP_CONSIGNE_REDUIT,
    DP_HEAT_DEMAND,
    DP_HOLIDAY_SETPOINT,
    DP_LEAVING_HOME_SETPOINT,
    DP_MANUAL_SETPOINT,
    DP_PAUSE_SETPOINT,
    DP_PREHEAT,
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

# Plateformes exposées. v0.2 : climate (consigne) + capteurs + switch (verrou enfant,
# détection fenêtre). number viendra avec d'autres réglages numériques (borne haute…).
PLATFORMS = ["climate", "sensor", "binary_sensor", "switch"]

# Clés de hass.data[DOMAIN][entry_id].
DATA_COORDINATOR = "coordinator"
DATA_LOCAL = "local_coordinator"  # repli local (tunnel), None si enable_local désactivé
DATA_MQTT = "mqtt_publisher"  # publicateur MQTT, None si mqtt_mode = off
DATA_JOBS = "jobs"  # file en mémoire des lots d'écriture (WriteJob)
DATA_SCHEDULES = "schedules"  # cache des programmes par cible (lecture à la demande)

# Intervalle du relevé LOCAL (tunnel Zigbee) : lent, car ~8 s par tête. Distinct du polling cloud.
DEFAULT_LOCAL_SCAN_INTERVAL = 900  # secondes

# --- Identifiants et secrets d'installation (config_flow / options_flow) ---
# username/password/country_code : identifiants du compte de l'app (login voie 1a).
# sign_key/device_id/ch_key : matériel d'INSTALLATION capturé une fois (voir README),
# stable, indispensable à la signature et au chiffrement. SECRETS : jamais journalisés.
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_COUNTRY_CODE = "country_code"  # indicatif pays, ex. "33" (France)
CONF_REGION = "region"  # datacenter : "eu" | "us" | "cn" | "in"
CONF_SIGN_KEY = "sign_key"
CONF_DEVICE_ID = "device_id"
CONF_CH_KEY = "ch_key"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLE_LOCAL = "enable_local"
CONF_MQTT_MODE = "mqtt_mode"  # "off" | "discovery" | "zigbee2mqtt"
CONF_MQTT_SOURCE = "mqtt_source"  # "cloud" | "local"
CONF_MQTT_BASE_TOPIC = "mqtt_base_topic"

# Défauts conservateurs : le quota et la sécurité du compte priment.
DEFAULT_SCAN_INTERVAL = 90  # secondes
DEFAULT_MQTT_MODE = "off"
DEFAULT_MQTT_SOURCE = "cloud"
DEFAULT_MQTT_BASE_TOPIC = "danfoss_ally_cloud"
