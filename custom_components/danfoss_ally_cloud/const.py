"""Constantes de l'intégration Danfoss Ally (Cloud)."""

from __future__ import annotations

DOMAIN = "danfoss_ally_cloud"

# Plateformes exposées. v0.2 : climate (consigne) + capteurs + switch (verrou enfant,
# détection fenêtre). number viendra avec d'autres réglages numériques (borne haute…).
PLATFORMS = ["climate", "sensor", "binary_sensor", "switch"]

# Clés de hass.data[DOMAIN][entry_id].
DATA_COORDINATOR = "coordinator"
DATA_LOCAL = "local_coordinator"  # repli local (tunnel), None si enable_local désactivé

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

# Codes DP (noms officiels : voir danfoss-app-capture/dp_schema_officiel.md).
# Source de vérité, à ne pas deviner. Rappels des pièges connus :
#   DP 16  = temp_set (consigne EFFECTIVE, dixièmes de °C) — lue comme consigne en v0.1
#   DP 171 = OccupiedSetpoint (échelle à CONFIRMER en réel : 171 non fiable tant que non vérifié)
#   DP 18  = upper_temp (BORNE HAUTE, pas la consigne)
#   DP 114 = consigne du mode manuel
#   DP 1   = pré-chauffage (côté cloud : ne change que le cache passerelle)
#   DP 30  = verrouillage enfant
#   DP 116 = détection de fenêtre
#   DP 162 = demande de chaleur (miroir cloud DP 138)
DP_SETPOINT = 171
DP_UPPER_TEMP = 18
DP_MANUAL_SETPOINT = 114
DP_PREHEAT = 1
DP_CHILD_LOCK = 30
DP_WINDOW_DETECT = 116
DP_HEAT_DEMAND = 162

# Le vrai levier du pré-chauffage est l'attribut Zigbee standard, accessible
# UNIQUEMENT par le tunnel local (voir api/local/tunnel.py).
ZB_ATTR_PROGRAMMING_MODE = 0x0025  # bit0 programme, bit1 pré-chauffage

# Modèles sur lesquels une écriture a été vérifiée en réel (à étendre install
# par install : c'est l'un des buts de la diffusion publique).
WRITE_VERIFIED_MODELS = ("radiator thermostat", "icon2 rt")

# Produits (productId Tuya) sur lesquels le MÉCANISME d'écriture voie 1a est câblé
# (tuya.m.custom.wkf.settings.change). ⚠ Porté des captures du MCP ; la confirmation
# EN RÉEL (effet observé sur la tête) reste à faire, install par install.
WRITE_VERIFIED_PRODUCTS = ("03wvrwpv",)  # tête thermostatique Danfoss Ally

# Consigne (écriture) : DP 16 temp_set, dixièmes de °C. Bornes et pas du schéma produit.
DP_TEMP_SET = 16
SETPOINT_MIN = 5.0
SETPOINT_MAX = 35.0
SETPOINT_STEP = 0.5
