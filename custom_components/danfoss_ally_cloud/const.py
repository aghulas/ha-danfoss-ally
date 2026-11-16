"""Constantes de l'intégration Danfoss Ally (Cloud)."""

from __future__ import annotations

DOMAIN = "danfoss_ally_cloud"

# Plateformes exposées. On démarre avec climate + capteurs ; switch/number
# s'activent au fur et à mesure que les écritures sont validées.
PLATFORMS = ["climate", "sensor", "binary_sensor", "number", "switch"]

# --- Options de configuration (config_flow / options_flow) ---
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_REGION = "region"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_ENABLE_LOCAL = "enable_local"
CONF_MQTT_MODE = "mqtt_mode"        # "off" | "discovery" | "zigbee2mqtt"
CONF_MQTT_SOURCE = "mqtt_source"    # "cloud" | "local"
CONF_MQTT_BASE_TOPIC = "mqtt_base_topic"

# Défauts conservateurs : le quota et la sécurité du compte priment.
DEFAULT_SCAN_INTERVAL = 90  # secondes
DEFAULT_MQTT_MODE = "off"
DEFAULT_MQTT_SOURCE = "cloud"
DEFAULT_MQTT_BASE_TOPIC = "danfoss_ally_cloud"

# Codes DP (noms officiels : voir danfoss-app-capture/dp_schema_officiel.md).
# Source de vérité, à ne pas deviner. Rappels des pièges connus :
#   DP 171 = OccupiedSetpoint (consigne en cours, centièmes)
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
