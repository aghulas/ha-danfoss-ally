"""Décodage des `dps` Tuya (voie 1a) d'une tête Danfoss Ally en un modèle normalisé.

Entrée : un appareil brut de ``tuya.m.my.group.device.list`` (devId, name, category, productId,
nodeId, meshId, moduleMap, dps). Les `dps` sont indexés par NUMÉRO de DP (chaîne), selon le schéma
officiel du produit ``03wvrwpv`` (voir danfoss-app-capture/dp_schema_officiel.md, source de vérité).

⚠ À vérifier en réel (v0.1) : l'échelle exacte de certains DP peut dépendre du firmware.
Consignes et températures suivent l'échelle 10^-1 (dixièmes de °C). Tout DP inconnu reste dans dps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- Table des défauts (DP 45 `fault` / DP 184 `sw_error_code`) : champ de bits « SW error code »
# Danfoss (attribut Zigbee 0x4000, cluster diagnostic 0x0B05). Identique à ZHA et Zigbee2MQTT.
DEFAUTS_BITS = {
    0: ("E1", "capteur de la carte supérieure en défaut", "tête défectueuse : à remplacer"),
    1: ("E2", "capteur de la carte latérale en défaut", "tête défectueuse : à remplacer"),
    2: ("E3", "mémoire interne en défaut", "tête défectueuse : à remplacer"),
    3: ("E4", "erreur matérielle inconnue", "tête défectueuse : à remplacer"),
    5: ("E6", "moteur bloqué", "redémarrer la tête (piles), puis la remonter sur la vanne"),
    7: ("E8", "communication interne invalide", "redémarrer ; disparaît seule en ~10 min"),
    9: ("E10", "horloge invalide", "heure à resynchroniser par la passerelle"),
    11: ("E12", "erreur de communication radio", "vérifier la passerelle et la portée Zigbee"),
    12: ("E13", "codeur bloqué", "redémarrer la tête"),
    13: ("E14", "pile faible", "changer les piles prochainement"),
    14: ("E15", "pile très faible (critique)", "changer les piles maintenant"),
}


def decoder_defaut(v: Any) -> list[dict[str, Any]]:
    """Code `fault` (champ de bits, entier ou chaîne décimale, ou « E14 ») → liste d'erreurs."""
    if isinstance(v, str) and v.strip().upper().startswith("E") and v.strip()[1:].isdigit():
        n = int(v.strip()[1:]) - 1
        valeur = 1 << n if 0 <= n < 16 else 0
    else:
        try:
            valeur = int(v)
        except (TypeError, ValueError):
            return [{"code": str(v), "libelle": "code non reconnu"}]
    erreurs = []
    for bit in range(16):
        if valeur >> bit & 1:
            if bit in DEFAUTS_BITS:
                code, libelle, action = DEFAUTS_BITS[bit]
                erreurs.append({"code": code, "bit": bit, "libelle": libelle, "action": action})
            else:
                erreurs.append(
                    {"code": f"bit {bit}", "bit": bit, "libelle": f"bit {bit} non documenté"}
                )
    return erreurs


# Consignes par mode (DP -> clé lisible), échelle dixièmes de °C.
_CONSIGNES = {
    "16": "consigne",  # temp_set : consigne effective en cours
    "118": "confort",  # at_home_setting
    "119": "reduit",  # leaving_home_setting
    "114": "manuel",  # manual_mode_fast
    "120": "pause",  # pause_setting
    "121": "vacances",  # holiday_setting
}


def _num(v: Any, diviseur: float = 1) -> float | None:
    if v is None or v == "":
        return None
    try:
        return round(float(v) / diviseur, 2)
    except (TypeError, ValueError):
        return None


def _bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "on", "yes", "open", "active"):
            return True
        if s in ("false", "0", "off", "no", "close", "closed", "inactive"):
            return False
    return None


def categorie(category: str | None) -> str:
    """Catégorie Tuya brute -> catégorie lisible."""
    c = (category or "").lower()
    if c == "wk":
        return "tete"
    if c == "kg":
        return "relais"
    if c in ("wsdcg", "mcs", "ms", "pir"):
        return "capteur"
    if c in ("wg2", "zigbee", "gateway"):
        return "passerelle"
    return "autre"


@dataclass
class DanfossDevice:
    """Modèle normalisé d'un appareil Danfoss Ally (lecture)."""

    id: str
    nom: str
    categorie: str
    product_id: str | None = None
    node_id: str | None = None  # cid Zigbee (lien avec le pont local)
    mesh_id: str | None = None  # passerelle
    en_ligne: bool = False
    temperature: float | None = None  # °C (DP 24)
    consigne: float | None = None  # °C effective (DP 16)
    consignes: dict[str, float] = field(default_factory=dict)
    mode: str | None = None  # DP 2
    etat: str | None = None  # DP 3 work_state
    batterie: float | None = None  # % (DP 34)
    ouverture_vanne: float | None = None  # % (DP 170 pi_heating_demand)
    demande_chaleur: bool | None = None  # DP 162 heat_supply_request
    fenetre_ouverte: bool | None = None  # DP 25 window_state
    detection_fenetre: bool | None = None  # DP 116 window_toggle
    verrouillage: bool | None = None  # DP 30 child_lock
    borne_haute: float | None = None  # °C (DP 18)
    borne_basse: float | None = None  # °C (DP 27)
    defauts: list[dict[str, Any]] = field(default_factory=list)
    dps: dict[str, Any] = field(default_factory=dict)

    @property
    def est_tete(self) -> bool:
        return self.categorie == "tete"


def _online(appareil: dict[str, Any]) -> bool:
    zb = (appareil.get("moduleMap") or {}).get("zigbee") or {}
    if "isOnline" in zb:
        return bool(zb.get("isOnline"))
    return bool(appareil.get("isOnline", appareil.get("online", False)))


def decoder(appareil: dict[str, Any]) -> DanfossDevice:
    """Appareil brut (``tuya.m.my.group.device.list``) -> DanfossDevice normalisé."""
    dps: dict[str, Any] = {str(k): v for k, v in (appareil.get("dps") or {}).items()}
    d = DanfossDevice(
        id=appareil.get("devId"),
        nom=(appareil.get("name") or "").strip(),
        categorie=categorie(appareil.get("category")),
        product_id=appareil.get("productId"),
        node_id=appareil.get("nodeId"),
        mesh_id=appareil.get("meshId"),
        en_ligne=_online(appareil),
        dps=dps,
    )
    d.temperature = _num(dps.get("24"), 10)
    d.consigne = _num(dps.get("16"), 10)
    for dp, cle in _CONSIGNES.items():
        x = _num(dps.get(dp), 10)
        if x is not None:
            d.consignes[cle] = x
    d.mode = dps.get("2")
    d.etat = dps.get("3")
    d.batterie = _num(dps.get("34"))
    d.ouverture_vanne = _num(dps.get("170"))
    d.demande_chaleur = _bool(dps.get("162"))
    d.verrouillage = _bool(dps.get("30"))
    d.detection_fenetre = _bool(dps.get("116"))
    d.borne_haute = _num(dps.get("18"), 10)
    d.borne_basse = _num(dps.get("27"), 10)
    ws = dps.get("25")
    if ws is not None and ws != "":
        d.fenetre_ouverte = _bool(ws)
    for dp in ("45", "184"):
        v = dps.get(dp)
        if v not in (None, "", 0, "0", [], "none"):
            d.defauts.extend(decoder_defaut(v))
    return d
