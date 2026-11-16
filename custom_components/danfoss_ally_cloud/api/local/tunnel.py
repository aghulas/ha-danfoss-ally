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

# Attributs lus : (id, nom). 0x0025 = mode programmation (bit 1 = pré-chauffage).
ATTRIBUTS_STD = [
    (0x0012, "consigne_en_cours"),
    (0x0015, "borne_basse"),
    (0x0016, "borne_haute"),
    (0x0025, "mode_programmation"),
    (0x0030, "source_consigne"),
]
_CENTIEMES = {"consigne_en_cours", "borne_basse", "borne_haute"}
_BOOLEENS: set[str] = set()
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
        elif nom == "mode_programmation":
            out[nom] = v
            out["pre_chauffage"] = bool(
                v & 0x02
            )  # 3 = programme + pré-chauffage, 1 = programme seul
        else:
            out[nom] = v
    return out


def plages(transitions: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Plages de confort d'une journée : segments dont la consigne dépasse celle de 00:00."""
    if not transitions:
        return []
    base, out = transitions[0]["c"], []
    for i, t in enumerate(transitions):
        if t["c"] > base:
            fin = transitions[i + 1]["h"] if i + 1 < len(transitions) else "24:00"
            out.append({"debut": t["h"], "fin": fin, "consigne": t["c"]})
    return out


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
