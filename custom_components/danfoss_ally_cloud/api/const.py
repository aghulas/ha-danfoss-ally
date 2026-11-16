"""Constantes appareil / protocole de la bibliothèque (indépendantes de Home Assistant).

Source de vérité des codes DP : danfoss-app-capture/dp_schema_officiel.md (produit 03wvrwpv).
Ces constantes appartiennent à la couche réutilisable (future bibliothèque pydanfoss-cloud) ;
l'intégration HA les ré-exporte depuis son propre const.py.
"""

from __future__ import annotations

# Codes DP (noms officiels : voir dp_schema_officiel.md). Pièges connus :
#   DP 16  = temp_set (consigne EFFECTIVE, dixièmes de °C) — lue/écrite comme consigne
#   DP 171 = OccupiedSetpoint (échelle à CONFIRMER en réel)
#   DP 18  = upper_temp (BORNE HAUTE, pas la consigne)
#   DP 114 = consigne du mode manuel ; DP 1 = pré-chauffage (cloud = cache passerelle)
#   DP 30  = verrouillage enfant ; DP 116 = détection de fenêtre ; DP 162 = demande de chaleur
DP_TEMP_SET = 16
DP_SETPOINT = 171
DP_UPPER_TEMP = 18
DP_MANUAL_SETPOINT = 114  # manual_mode_fast
DP_AT_HOME_SETPOINT = 118  # at_home_setting (période « confort » du programme)
DP_LEAVING_HOME_SETPOINT = 119  # leaving_home_setting (période « réduit »)
DP_PAUSE_SETPOINT = 120  # pause_setting
DP_HOLIDAY_SETPOINT = 121  # holiday_setting (vacances)
DP_PREHEAT = 1
DP_CHILD_LOCK = 30
DP_WINDOW_DETECT = 116
DP_HEAT_DEMAND = 162

# Écriture de consigne : mode courant (DP 2) -> DP du réglage à écrire.
# Prouvé en réel : écrire le DP16 temp_set NE TIENT PAS sur une tête sur programme (l'horaire le
# réécrit). Le levier durable est la consigne du RÉGLAGE DU MODE ACTIF (temp_set suit ensuite).
MODE_SETPOINT_DP = {
    "at_home": DP_AT_HOME_SETPOINT,
    "leaving_home": DP_LEAVING_HOME_SETPOINT,
    "pause": DP_PAUSE_SETPOINT,
    "holiday": DP_HOLIDAY_SETPOINT,
    "holiday_sat": DP_HOLIDAY_SETPOINT,
    "manual": DP_MANUAL_SETPOINT,
}

# --- Écriture de consigne DURABLE, voie 1a « vraie » : au niveau PIÈCE (groupe) -----------------
# Corrige PR #8 (mergé) : écrire le DP du MODE sur la TÊTE (settings.change) NE TIENT PAS non plus
# (vérifié en réel le 16/11/2026, 0.1.0). La méthode que l'app emploie réellement (captures
# 15-16/11, _CONSIGNES_PIECE du connecteur MCP, rejouées et relues dans les têtes) :
#   1. publier la consigne sur le GROUPE de la pièce via s.m.dev.group.dp.publish {dps, groupId} ;
#   2. PUIS réécrire le programme de la pièce (un jour suffit, le cloud renvoie toute la semaine aux
#      têtes avec les consignes du moment), sinon les têtes gardent l'ancienne valeur dans leurs
#      transitions programmées.
# Échelle : dixièmes de °C, pas de 0,5 — identique à encode_consigne (round(°C*2)*5, 50..350).
#   confort = DP 118 (at_home_setting)
#   réduit  = DP 109 ET DP 119 (les deux) — leaving_home_setting + jumeau capté par l'app
DP_CONSIGNE_CONFORT = 118
DP_CONSIGNE_REDUIT = (109, 119)

# Mode courant (DP 2) -> DP(s) de consigne de PIÈCE à publier au groupe. Seuls confort/réduit sont
# prouvés par capture ; les autres modes n'ont pas de méthode groupe voie-1a vérifiée.
MODE_GROUP_SETPOINT_DP: dict[str, tuple[int, ...]] = {
    "at_home": (DP_CONSIGNE_CONFORT,),
    "leaving_home": DP_CONSIGNE_REDUIT,
}

# Types de ressource « week timer » Tuya : 2 = pièce (groupe), 1 = tête isolée.
RES_TYPE_GROUP = 2
RES_TYPE_DEVICE = 1

# Le vrai levier du pré-chauffage est l'attribut Zigbee standard (tunnel local uniquement).
ZB_ATTR_PROGRAMMING_MODE = 0x0025  # bit 0 programme, bit 1 pré-chauffage

# Consigne (écriture) : bornes et pas du schéma produit (dixièmes de °C).
SETPOINT_MIN = 5.0
SETPOINT_MAX = 35.0
SETPOINT_STEP = 0.5

# Modèles / produits sur lesquels l'écriture est câblée (à étendre install par install).
WRITE_VERIFIED_MODELS = ("radiator thermostat", "icon2 rt")
WRITE_VERIFIED_PRODUCTS = ("03wvrwpv",)  # tête thermostatique Danfoss Ally
