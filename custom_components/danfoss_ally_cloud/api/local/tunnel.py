"""Tunnel Zigbee local via les passerelles Tuya (DP 198 -> réponse DP 199).

Pour les opérations que le cloud rate : lecture du programme hebdomadaire directement dans la tête,
lecture/écriture des vrais attributs ZCL (dont l'état de pré-chauffage, attribut 0x0025). Protocole
LAN Tuya 3.5 (tinytuya). Repris de ~/dev/danfoss-ally-mcp/local.py.

Les fonctions de trame sont PURES (testables sans réseau). ``LocalLink`` isole tinytuya (doublure
possible dans les tests). Appels bloquants : la couche HA les exécute dans l'executor.

En-tête du tunnel : ``40 01 | cluster (2 o, LE) | 04 01 01 00 | trame ZCL``. La passerelle relaie la
trame du DP 198 à la tête et pousse la réponse dans le DP 199 (1 à 9 s). La séquence ZCL étant
renumérotée, une réponse se reconnaît à son contenu.
"""

from __future__ import annotations

import base64
import contextlib
import threading
import time
from collections.abc import Callable
from typing import Any

from ..keys import GatewayKey

CLUSTER_THERMOSTAT = 0x0201
FABRICANT = 0x1246
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
BIT_JOUR = {
    "dimanche": 0x01,
    "lundi": 0x02,
    "mardi": 0x04,
    "mercredi": 0x08,
    "jeudi": 0x10,
    "vendredi": 0x20,
    "samedi": 0x40,
}
MAX_TRANSITIONS = 6
# Jours du dégommage (attribut Danfoss 0x4010, enum8) : dimanche = 0, … samedi = 6, 7 = indéfini.
JOURS_DEGOMMAGE = [
    "dimanche",
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "indéfini",
]

# Attributs lus : (id, nom). 0x0025 = mode programmation (bit 1 = pré-chauffage).
ATTRIBUTS_STD = [
    (0x0012, "consigne_en_cours"),
    (0x0015, "borne_basse"),
    (0x0016, "borne_haute"),
    (0x0025, "mode_programmation"),
    (0x0030, "source_consigne"),
]
# Attributs Danfoss (code fabricant 0x1246), répartis en deux relevés comme le connecteur MCP.
ATTRIBUTS_DANFOSS_A = [
    (0x4010, "degommage_jour"),
    (0x4011, "degommage_heure"),
    (0x4014, "orientation"),
    (0x4016, "radiateur_couvert"),
    (0x4020, "vitesse_regulation"),
    (0x4030, "chaleur_disponible"),
    (0x4031, "demande_chaleur"),
    (0x4032, "equilibrage"),
]
ATTRIBUTS_DANFOSS_B = [
    (0x404B, "decalage_consigne"),
    (0x404D, "adaptation_etat"),
    (0x404E, "adaptation_reglage"),
    (0x404F, "prechauffage_en_cours"),
    (0x4051, "detection_fenetre"),
    (0x4000, "etat_fenetre"),
]
# Réglages inscriptibles par leur DP de pièce (noms officiels du schéma produit 03wvrwpv, contrat
# §4.2). Le pré-chauffage réel, lui, est le bit 1 de l'attribut 0x0025 (voir ecrire_prechauffage) :
# écrire le DP 1 ne touche que le cache de la passerelle (constat réel du 15/11/2026).
REGLAGES_DP: dict[str, tuple[str, type]] = {
    "detection_fenetre": ("116", bool),  # window_toggle
    "verrouillage_enfant": ("30", bool),  # child_lock
}
# Dérogation de consigne « maintenant » : DP 171 OccupiedSetpoint. ATTENTION à l'échelle, voir
# valeur_consigne : le MCP (validé en réel) l'écrit en centièmes de °C, alors que le schéma produit
# annonce une échelle 10^0 — incohérence signalée, on suit le constat réel (centièmes).
DP_CONSIGNE = "171"

_CENTIEMES = {"consigne_en_cours", "borne_basse", "borne_haute"}
_BOOLEENS = {
    "radiateur_couvert",
    "chaleur_disponible",
    "demande_chaleur",
    "equilibrage",
    "prechauffage_en_cours",
    "detection_fenetre",
    "orientation",
}
_LONGUEUR = {
    0x10: 1,
    0x18: 1,
    0x19: 2,
    0x20: 1,
    0x21: 2,
    0x22: 3,
    0x23: 4,
    0x28: 1,
    0x29: 2,
    0x2B: 4,
    0x30: 1,
    0x31: 2,
}
_SIGNES = {0x28, 0x29, 0x2B}


class LocalIndisponible(Exception):
    """Accès local impossible (clés absentes, tinytuya manquant, passerelle injoignable)."""


class LocalErreur(Exception):
    """Demande locale invalide (programme mal formé, type ZCL non géré…)."""


# --- trames (fonctions pures) -----------------------------------------------------------------


def entete(cluster: int) -> bytes:
    return bytes.fromhex("4001") + cluster.to_bytes(2, "little") + bytes.fromhex("04010100")


def trame_lire_attributs(attributs: list[int], fabricant: bool, seq: int = 0x40) -> bytes:
    if fabricant:
        debut = bytes([0x04]) + FABRICANT.to_bytes(2, "little") + bytes([seq, 0x00])
    else:
        debut = bytes([0x00, seq, 0x00])
    return entete(CLUSTER_THERMOSTAT) + debut + b"".join(a.to_bytes(2, "little") for a in attributs)


def trame_lire_programme(jour: str, seq: int = 0x40) -> bytes:
    return entete(CLUSTER_THERMOSTAT) + bytes([0x01, seq, 0x02, BIT_JOUR[jour], 0x01])


def trame_ecrire_attributs(
    enregistrements: list[tuple[int, int, int]], fabricant: bool, seq: int = 0x40
) -> bytes:
    """Écriture d'attributs ZCL (cmd 0x02). enregistrements = [(attribut, type ZCL, valeur)]."""
    if fabricant:
        debut = bytes([0x04]) + FABRICANT.to_bytes(2, "little") + bytes([seq, 0x02])
    else:
        debut = bytes([0x00, seq, 0x02])
    corps = b""
    for a, typ, v in enregistrements:
        if typ not in _LONGUEUR:
            raise LocalErreur(f"type ZCL non géré : 0x{typ:02x}")
        corps += (
            a.to_bytes(2, "little")
            + bytes([typ])
            + int(v).to_bytes(_LONGUEUR[typ], "little", signed=typ in _SIGNES)
        )
    return entete(CLUSTER_THERMOSTAT) + debut + corps


def minutes(h: str) -> int:
    try:
        hh, mm = (int(x) for x in h.split(":"))
    except (ValueError, AttributeError) as e:
        raise LocalErreur(f"heure invalide : {h!r} (attendu HH:MM)") from e
    if not (0 <= hh <= 24 and 0 <= mm < 60 and hh * 60 + mm <= 1440):
        raise LocalErreur(f"heure invalide : {h!r}")
    return hh * 60 + mm


def verifier_transitions(transitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Journée valide : 1 à 6 transitions, 1re à 00:00, heures croissantes, consignes 5–35/0,5."""
    if not transitions or len(transitions) > MAX_TRANSITIONS:
        raise LocalErreur(f"une journée compte 1 à {MAX_TRANSITIONS} transitions")
    out: list[dict[str, Any]] = []
    avant = -1
    for t in transitions:
        m, c = minutes(t["h"]), float(t["c"])
        if m <= avant or m >= 1440:
            raise LocalErreur("transitions à donner dans l'ordre, sans doublon, avant 24:00")
        if not 5 <= c <= 35 or round(c * 2) != c * 2:
            raise LocalErreur(f"consigne hors plage : {c} (5 à 35 °C par 0,5)")
        out.append({"h": f"{m // 60:02d}:{m % 60:02d}", "c": c})
        avant = m
    if out[0]["h"] != "00:00":
        raise LocalErreur("la première transition d'une journée doit être à 00:00")
    return out


def trame_ecrire_programme(jour: str, transitions: list[dict[str, Any]], seq: int = 0x40) -> bytes:
    tr = verifier_transitions(transitions)
    corps = bytes([len(tr), BIT_JOUR[jour], 0x01])
    for t in tr:
        corps += minutes(t["h"]).to_bytes(2, "little") + int(round(t["c"] * 100)).to_bytes(
            2, "little", signed=True
        )
    return entete(CLUSTER_THERMOSTAT) + bytes([0x01, seq, 0x01]) + corps


def decoder_trame(brut: bytes) -> dict[str, Any] | None:
    """Trame DP 199 → {cluster, fabricant, commande, specifique, charge} ; None si non reconnue."""
    if len(brut) < 11 or brut[:2] != b"\x40\x01":
        return None
    z = brut[8:]
    fc, i, fab = z[0], 1, None
    if fc & 0x04:
        if len(z) < 5:
            return None
        fab, i = int.from_bytes(z[1:3], "little"), 3
    return {
        "cluster": int.from_bytes(brut[2:4], "little"),
        "fabricant": fab,
        "commande": z[i + 1],
        "specifique": bool(fc & 0x01),
        "charge": z[i + 2 :],
    }


def decoder_attributs(charge: bytes) -> dict[int, int | None]:
    out: dict[int, int | None] = {}
    i = 0
    while i + 3 <= len(charge):
        a, statut = int.from_bytes(charge[i : i + 2], "little"), charge[i + 2]
        i += 3
        if statut != 0:
            out[a] = None
            continue
        n = _LONGUEUR.get(charge[i])
        if n is None or i + 1 + n > len(charge):
            break
        out[a] = int.from_bytes(charge[i + 1 : i + 1 + n], "little", signed=charge[i] in _SIGNES)
        i += 1 + n
    return out


def decoder_programme(charge: bytes) -> tuple[int, list[dict[str, Any]]]:
    """Réponse GetWeeklySchedule → (bit du jour, transitions [{h, c}])."""
    n, jour = charge[0], charge[1]
    tr = []
    for k in range(n):
        o = 3 + 4 * k
        if o + 4 > len(charge):
            break
        m = int.from_bytes(charge[o : o + 2], "little")
        c = int.from_bytes(charge[o + 2 : o + 4], "little", signed=True) / 100
        tr.append({"h": f"{m // 60:02d}:{m % 60:02d}", "c": c})
    return jour, tr


def nommer(valeurs: dict[int, int | None], table: list[tuple[int, str]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for a, nom in table:
        v = valeurs.get(a)
        if v is None:
            continue
        if nom in _CENTIEMES:
            out[nom] = v / 100
        elif nom in _BOOLEENS:
            out[nom] = bool(v)
        elif nom == "degommage_jour":
            out[nom] = JOURS_DEGOMMAGE[v] if v < len(JOURS_DEGOMMAGE) else v
        elif nom == "degommage_heure":
            out[nom] = f"{v // 60:02d}:{v % 60:02d}"
        elif nom == "mode_programmation":
            out[nom] = v
            out["pre_chauffage"] = bool(
                v & 0x02
            )  # 3 = programme + pré-chauffage, 1 = programme seul
        elif nom == "adaptation_etat":
            out[nom] = v
            out["adaptation_faite"] = bool(v & 0x02)
        else:
            out[nom] = v
    return out


def plages(transitions: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Plages de confort d'une journée : segments dont la consigne dépasse la plus basse du jour.

    Deux segments de confort consécutifs à la même consigne sont fusionnés. La référence est la
    consigne la plus basse de la journée (le réduit), et non celle de 00:00 : sinon une journée qui
    commence en confort (plage à 00:00) ne montrerait aucune plage.
    """
    if not transitions:
        return []
    base: float = min(t["c"] for t in transitions)
    out: list[dict[str, Any]] = []
    for i, t in enumerate(transitions):
        if t["c"] > base:
            fin = transitions[i + 1]["h"] if i + 1 < len(transitions) else "24:00"
            if out and out[-1]["fin"] == t["h"] and out[-1]["consigne"] == t["c"]:
                out[-1]["fin"] = fin
            else:
                out.append({"debut": t["h"], "fin": fin, "consigne": t["c"]})
    return out


def degommage_valeurs(jour: str, heure: str) -> list[tuple[int, int, int]]:
    """Dégommage hebdomadaire de la vanne : attributs Danfoss 0x4010 (jour, enum8) et 0x4011 (heure
    en minutes, uint16). À écrire par ``ecrire_attributs(..., fabricant=True)``."""
    j = (jour or "").lower()
    if j not in JOURS_DEGOMMAGE[:7]:
        raise LocalErreur(f"jour de dégommage inconnu : {jour}")
    return [(0x4010, 0x30, JOURS_DEGOMMAGE.index(j)), (0x4011, 0x21, minutes(heure) % 1440)]


def valeur_consigne(celsius: float) -> int:
    """Dérogation de consigne (DP 171) → entier à publier. Valide 5–35 °C par 0,5.

    Échelle : centièmes de °C (21 °C → 2100), d'après le constat réel du connecteur MCP du
    15/11/2026. Le schéma produit officiel (DP 171 ``OccupiedSetpoint``) annonce une échelle 10^0 :
    cette incohérence est connue et tranchée en faveur du constat réel (voir DP_CONSIGNE).
    """
    c = float(celsius)
    if not 5 <= c <= 35 or round(c * 2) != c * 2:
        raise LocalErreur(f"consigne hors plage : {celsius} (5 à 35 °C par 0,5)")
    return int(round(c * 100))


def transitions_depuis_fenetres(
    fenetres: list[dict[str, str]], confort: float, reduit: float
) -> list[dict[str, Any]]:
    """Fenêtres de confort ``[{debut, fin}]`` → transitions d'une journée (réduit en dehors)."""
    tr: list[dict[str, Any]] = [{"h": "00:00", "c": float(reduit)}]
    fin_prec = 0
    for f in sorted(fenetres, key=lambda x: minutes(x["debut"])):
        d, e = minutes(f["debut"]), minutes(f["fin"])
        if d < fin_prec or e <= d:
            raise LocalErreur(
                "fenêtres de confort mal formées (chevauchement ou fin avant le début)"
            )
        if d == 0:
            tr[0]["c"] = float(confort)
        else:
            tr.append({"h": f"{d // 60:02d}:{d % 60:02d}", "c": float(confort)})
        if e < 1440:
            tr.append({"h": f"{e // 60:02d}:{e % 60:02d}", "c": float(reduit)})
        fin_prec = e
    return verifier_transitions(tr)


# --- liaison avec une passerelle (tinytuya) ---------------------------------------------------


class LocalLink:
    """Connexion persistante à une passerelle (tinytuya). Doublure possible dans les tests."""

    def __init__(self, gateway: GatewayKey) -> None:
        if not gateway.ip:
            raise LocalIndisponible(
                f"IP LAN inconnue pour la passerelle {gateway.nom or gateway.dev_id}"
            )
        try:
            import tinytuya
        except ImportError as e:
            raise LocalIndisponible("tinytuya non installé") from e
        self._tt = tinytuya
        self._p = tinytuya.Device(
            gateway.dev_id, gateway.ip, gateway.local_key, version=3.5, persist=True
        )
        self._p.set_socketTimeout(3)
        self._subs: dict[str, Any] = {}
        self._battement = time.time()

    def _sub(self, dev_id: str, node_id: str) -> Any:
        if dev_id not in self._subs:
            self._subs[dev_id] = self._tt.Device(dev_id, cid=node_id, parent=self._p)
        return self._subs[dev_id]

    def envoyer(self, dev_id: str, node_id: str, trame: bytes) -> None:
        self._sub(dev_id, node_id).set_value("198", base64.b64encode(trame).decode(), nowait=True)

    def envoyer_dp(self, dev_id: str, node_id: str, dp: str, valeur: Any) -> None:
        """Publie une valeur sur un DP de la tête (hors tunnel) : dérogation de consigne (171),
        réglages de pièce (116, 30). Fire-and-forget : la passerelle accuse par rafraîchissement."""
        self._sub(dev_id, node_id).set_value(dp, valeur, nowait=True)

    def recevoir(self) -> tuple[str | None, dict[str, Any]] | None:
        if time.time() - self._battement > 20:
            with contextlib.suppress(Exception):
                self._p.heartbeat(nowait=True)
            self._battement = time.time()
        try:
            m = self._p.receive()
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(m, dict):
            return None
        d = m.get("dps") or (m.get("data") or {}).get("dps")
        if not d:
            return None
        return (m.get("cid") or (m.get("data") or {}).get("cid"), d)

    def fermer(self) -> None:
        with contextlib.suppress(Exception):
            self._p.close()


def demander(
    lien: Any,
    dev_id: str,
    node_id: str,
    trame: bytes,
    accepte: Callable[[dict[str, Any]], Any],
    duree: float = 12,
    essais: int = 2,
) -> Any:
    """Envoie une trame par le tunnel et attend la réponse que `accepte` reconnaît (None sinon)."""
    for _ in range(essais):
        lien.envoyer(dev_id, node_id, trame)
        t0 = time.time()
        while time.time() - t0 < duree:
            r = lien.recevoir()
            if not r or r[0] != node_id or "199" not in r[1]:
                continue
            try:
                f = decoder_trame(base64.b64decode(r[1]["199"]))
            except (ValueError, TypeError):
                f = None
            if f and f["cluster"] == CLUSTER_THERMOSTAT:
                v = accepte(f)
                if v is not None:
                    return v
    return None


def lire_attributs(
    lien: Any, dev_id: str, node_id: str, table: list[tuple[int, str]], fabricant: bool, **kw: Any
) -> dict[str, Any] | None:
    ids = [a for a, _ in table]

    def accepte(f: dict[str, Any]) -> Any:
        if f["specifique"] or f["commande"] != 0x01 or bool(f["fabricant"]) != fabricant:
            return None
        v = decoder_attributs(f["charge"])
        return v if ids[0] in v else None

    v = demander(lien, dev_id, node_id, trame_lire_attributs(ids, fabricant), accepte, **kw)
    return None if v is None else nommer(v, table)


def lire_prechauffage(lien: Any, dev_id: str, node_id: str, **kw: Any) -> bool | None:
    """Pré-chauffage réel d'une tête (attribut standard 0x0025, bit 1). None si pas de réponse."""
    a = lire_attributs(lien, dev_id, node_id, ATTRIBUTS_STD, False, **kw)
    return None if a is None else a.get("pre_chauffage")


def lire_jour(
    lien: Any, dev_id: str, node_id: str, jour: str, **kw: Any
) -> list[dict[str, Any]] | None:
    def accepte(f: dict[str, Any]) -> Any:
        if not f["specifique"] or f["commande"] != 0x00 or f["fabricant"] or len(f["charge"]) < 3:
            return None
        bit, tr = decoder_programme(f["charge"])
        return tr if bit == BIT_JOUR[jour] else None

    return demander(lien, dev_id, node_id, trame_lire_programme(jour), accepte, **kw)


def lire_programme(lien: Any, dev_id: str, node_id: str) -> dict[str, list[dict[str, Any]]]:
    """Programme hebdomadaire des 7 jours d'une tête (par le tunnel)."""
    prog: dict[str, list[dict[str, Any]]] = {}
    for j in JOURS:
        tr = lire_jour(lien, dev_id, node_id, j)
        if tr is not None:
            prog[j] = tr
    return prog


def lire_mode_programmation(lien: Any, dev_id: str, node_id: str, **kw: Any) -> int | None:
    """Valeur brute 0x0025 (bit 0 programme, bit 1 pré-chauffage). None sans réponse."""
    a = lire_attributs(lien, dev_id, node_id, ATTRIBUTS_STD, False, **kw)
    return None if a is None else a.get("mode_programmation")


def nouveau_mode_prechauffage(mode_actuel: int, actif: bool) -> int:
    """Nouvelle valeur 0x0025 : (dés)active le bit pré-chauffage (0x02), bit programme préservé."""
    return (mode_actuel | 0x02) if actif else (mode_actuel & ~0x02)


def ecrire_attributs(
    lien: Any,
    dev_id: str,
    node_id: str,
    enregistrements: list[tuple[int, int, int]],
    fabricant: bool,
) -> int | None:
    """Écrit des attributs par le tunnel. Renvoie le 1er statut (0 = accepté), None sans réponse."""

    def accepte(f: dict[str, Any]) -> Any:
        if f["specifique"] or f["commande"] != 0x04 or bool(f["fabricant"]) != fabricant:
            return None
        return f["charge"][0] if f["charge"] else None

    trame = trame_ecrire_attributs(enregistrements, fabricant)
    return demander(lien, dev_id, node_id, trame, accepte, duree=10, essais=1)


def ecrire_prechauffage(
    lien: Any, dev_id: str, node_id: str, actif: bool, mode_actuel: int
) -> int | None:
    """Active/désactive le pré-chauffage réel (0x0025 bit 1), bit programme préservé.

    L'attribut 0x0025 « Programming Operation Mode » du cluster thermostat est un bitmap8 : il doit
    s'écrire avec le type ZCL 0x18 (et non 0x30 enum8, que la tête rejette). Type validé par le
    connecteur MCP de référence (constat réel du 15/11/2026).
    """
    nouveau = nouveau_mode_prechauffage(mode_actuel, actif)
    return ecrire_attributs(lien, dev_id, node_id, [(0x0025, 0x18, nouveau)], fabricant=False)


def ecrire_jour(
    lien: Any, dev_id: str, node_id: str, jour: str, transitions: list[dict[str, Any]]
) -> int | None:
    """SetWeeklySchedule (0x01) pour UN jour par le tunnel. Renvoie le statut de la tête (0 =
    accepté) dans la réponse par défaut ZCL (0x0B), None sans réponse. R2 : la tête propage ensuite
    toute la semaine. R1 est validée en amont (``verifier_transitions``, aussi dans la trame)."""

    def accepte(f: dict[str, Any]) -> Any:
        c = f["charge"]
        return c[1] if f["commande"] == 0x0B and len(c) >= 2 and c[0] == 0x01 else None

    trame = trame_ecrire_programme(jour, transitions)
    return demander(lien, dev_id, node_id, trame, accepte, duree=10, essais=1)


def ecrire_degommage(lien: Any, dev_id: str, node_id: str, jour: str, heure: str) -> int | None:
    """Règle le dégommage de la vanne (0x4010/0x4011, fabricant). Statut 0 = accepté."""
    return ecrire_attributs(lien, dev_id, node_id, degommage_valeurs(jour, heure), fabricant=True)


def ecrire_consigne(lien: Any, dev_id: str, node_id: str, celsius: float) -> int:
    """Dérogation de consigne « maintenant » par le DP 171 (centièmes). Fire-and-forget : renvoie la
    valeur publiée (vérification par relecture ultérieure). Hors programme : dérogation jusqu'au
    prochain changement d'horaire de la tête (pas une consigne durable, cf. contrat R3/R5)."""
    val = valeur_consigne(celsius)
    lien.envoyer_dp(dev_id, node_id, DP_CONSIGNE, val)
    return val


def ecrire_reglage_dp(lien: Any, dev_id: str, node_id: str, reglage: str, valeur: Any) -> Any:
    """Écrit un réglage de pièce par son DP (``detection_fenetre`` → 116, ``verrouillage_enfant`` →
    30). Fire-and-forget : renvoie la valeur publiée (type coercé selon REGLAGES_DP)."""
    if reglage not in REGLAGES_DP:
        raise LocalErreur(f"réglage DP inconnu : {reglage} (connus : {', '.join(REGLAGES_DP)})")
    dp, typ = REGLAGES_DP[reglage]
    val = typ(valeur)
    lien.envoyer_dp(dev_id, node_id, dp, val)
    return val


def lire_detection_fenetre(lien: Any, dev_id: str, node_id: str, **kw: Any) -> bool | None:
    """Lit l'attribut Danfoss 0x4051 (détection de fenêtre ouverte, bool). None sans réponse."""
    a = lire_attributs(lien, dev_id, node_id, [(0x4051, "detection_fenetre")], True, **kw)
    return None if a is None else a.get("detection_fenetre")


def lire_tete(lien: Any, dev_id: str, node_id: str, programme: bool = True) -> dict[str, Any]:
    """Relevé complet d'une tête par le tunnel : attributs standard + Danfoss (A et B) et, si
    ``programme``, les transitions des 7 jours. ``injoignable`` si rien ne répond. Best-effort : un
    relevé d'attributs qui échoue est noté dans ``manques`` sans interrompre les autres."""
    e: dict[str, Any] = {"attributs": {}, "programme": {}, "manques": []}
    t0, echecs = time.time(), 0
    for nom, table, fab in (
        ("standard", ATTRIBUTS_STD, False),
        ("danfoss_a", ATTRIBUTS_DANFOSS_A, True),
        ("danfoss_b", ATTRIBUTS_DANFOSS_B, True),
    ):
        a = lire_attributs(lien, dev_id, node_id, table, fab)
        if a is None:
            e["manques"].append(nom)
            echecs += 1
            if echecs >= 2 and not e["attributs"]:
                break
        else:
            e["attributs"].update(a)
    if not e["attributs"]:
        e["injoignable"] = True
    elif programme:
        for j in JOURS:
            tr = lire_jour(lien, dev_id, node_id, j)
            if tr is None:
                e["manques"].append(j)
            else:
                e["programme"][j] = tr
    e["duree_s"] = round(time.time() - t0)
    return e


def releve(
    gateways: dict[str, GatewayKey],
    heads: list[Any],
    ouvrir: Callable[[GatewayKey], Any] = LocalLink,
    progres: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Relevé robuste de plusieurs têtes, une passerelle par fil (lecture seule, ~8 s par tête).

    ``heads`` : objets exposant ``dev_id``, ``node_id`` et ``gateway_id`` (p. ex. ``manager.Head``).
    Résultat indexé par ``dev_id``. Best-effort : une passerelle injoignable marque ses têtes
    ``injoignable``, et chaque tête est isolée des autres (aucune exception propagée)."""
    res: dict[str, dict[str, Any]] = {}
    garde = threading.Lock()
    par_gw: dict[str, list[Any]] = {}
    for h in heads:
        if h.gateway_id in gateways:
            par_gw.setdefault(h.gateway_id, []).append(h)

    def fil(gw_id: str, miennes: list[Any]) -> None:
        try:
            lien = ouvrir(gateways[gw_id])
        except Exception as ex:  # noqa: BLE001 - passerelle injoignable
            with garde:
                for h in miennes:
                    res[h.dev_id] = {
                        "attributs": {},
                        "programme": {},
                        "injoignable": True,
                        "erreur": str(ex)[:80],
                    }
            return
        try:
            for h in miennes:
                try:
                    e = lire_tete(lien, h.dev_id, h.node_id)
                except Exception as ex:  # noqa: BLE001 - on isole chaque tête
                    e = {
                        "attributs": {},
                        "programme": {},
                        "injoignable": True,
                        "erreur": str(ex)[:80],
                    }
                with garde:
                    res[h.dev_id] = e
                if progres:
                    progres(h.dev_id, e)
        finally:
            lien.fermer()

    fils = [threading.Thread(target=fil, args=(g, m), daemon=True) for g, m in par_gw.items()]
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=60)
    return res


# --- synthèse et comparaison (fonctions pures) ------------------------------------------------


def resumer_tete(e: dict[str, Any]) -> dict[str, Any]:
    """Résumé d'un relevé de tête : plages de confort par jour, confort/réduit et attributs."""
    if not e.get("attributs"):
        return {"injoignable": True}
    p = e.get("programme") or {}
    cs = [t["c"] for j in JOURS for t in p.get(j, [])]
    return {
        "plages": {
            j: [f"{x['debut']}–{x['fin']}" for x in plages(p.get(j))] for j in JOURS if j in p
        },
        "confort": max(cs) if cs else None,
        "reduit": min(cs) if cs else None,
        **e["attributs"],
        **({"manques": e["manques"]} if e.get("manques") else {}),
    }


# Réglages suivis d'un relevé à l'autre (écarts remontés par ``comparer``).
REGLAGES_SUIVIS = (
    "borne_haute",
    "borne_basse",
    "mode_programmation",
    "degommage_jour",
    "degommage_heure",
    "vitesse_regulation",
    "detection_fenetre",
    "adaptation_faite",
    "radiateur_couvert",
    "equilibrage",
)


def comparer(
    reference: dict[str, dict[str, Any]], nouveau: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Écarts d'un relevé par rapport à une référence : programmes, réglages suivis, injoignables.

    ``reference`` et ``nouveau`` sont indexés de la même façon (``dev_id`` ou nom)."""
    ra = {n: e for n, e in reference.items() if e.get("attributs")}
    rb = {n: e for n, e in nouveau.items() if e.get("attributs")}
    prog = []
    for n in sorted(rb):
        if n in ra:
            for j in JOURS:
                x, y = ra[n]["programme"].get(j), rb[n]["programme"].get(j)
                if x != y and y is not None:
                    prog.append({"tete": n, "jour": j, "avant": x, "apres": y})
    regl = [
        {
            "tete": n,
            "reglage": k,
            "avant": ra[n]["attributs"].get(k),
            "apres": rb[n]["attributs"].get(k),
        }
        for n in sorted(rb)
        if n in ra
        for k in REGLAGES_SUIVIS
        if ra[n]["attributs"].get(k) != rb[n]["attributs"].get(k)
    ]

    def chauffe(e: dict[str, Any], j: str) -> bool:
        return bool(plages(e["programme"].get(j)))

    return {
        "relevees": len(rb),
        "tentees": len(nouveau),
        "injoignables": sorted(n for n, e in nouveau.items() if not e.get("attributs")),
        "nouvelles_injoignables": sorted(n for n in ra if n in nouveau and n not in rb),
        "programmes_modifies": prog,
        "reglages_modifies": regl,
        "chauffent_mercredi": sorted(n for n, e in rb.items() if chauffe(e, "mercredi")),
        "chauffent_week_end": sorted(
            n for n, e in rb.items() if chauffe(e, "samedi") or chauffe(e, "dimanche")
        ),
    }
