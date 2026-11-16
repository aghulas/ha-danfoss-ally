"""Tests du gestionnaire de tunnel local (relevé threadé, doublure sans réseau)."""

import base64

import pytest

from custom_components.danfoss_ally_cloud.api import GatewayKey
from custom_components.danfoss_ally_cloud.api.local import tunnel
from custom_components.danfoss_ally_cloud.api.local.manager import Head, LocalTunnelManager


def _reponse_prechauffage(valeur_0025: int) -> bytes:
    charge = (
        (0x0012).to_bytes(2, "little")
        + bytes([0x00, 0x29])
        + (2100).to_bytes(2, "little", signed=True)
        + (0x0025).to_bytes(2, "little")
        + bytes([0x00, 0x30, valeur_0025])
    )
    return tunnel.entete(tunnel.CLUSTER_THERMOSTAT) + bytes([0x00, 0x40, 0x01]) + charge


class _ReadFakeLink:
    def __init__(self, node_id: str, mode_0025: int) -> None:
        self.node_id = node_id
        self._resp = base64.b64encode(_reponse_prechauffage(mode_0025)).decode()
        self.ferme = False

    def envoyer(self, dev_id, node_id, trame):
        pass

    def recevoir(self):
        return (self.node_id, {"199": self._resp})

    def fermer(self):
        self.ferme = True


def _gw():
    return {"gw1": GatewayKey(dev_id="gw1", nom="A-0", local_key="cle-synth", ip="10.0.0.1")}


def test_relever_prechauffage():
    mgr = LocalTunnelManager(_gw(), ouvrir=lambda g: _ReadFakeLink("node1", 0x03))
    res = mgr.relever_prechauffage([Head("dev1", "node1", "gw1")])
    assert res == {"dev1": True}


def test_relever_ignore_passerelle_inconnue():
    mgr = LocalTunnelManager(_gw(), ouvrir=lambda g: _ReadFakeLink("node1", 0x03))
    res = mgr.relever_prechauffage([Head("devX", "nodeX", "gw-inconnue")])
    assert res == {}


def test_relever_passerelle_injoignable_rend_none():
    def boom(g):
        raise RuntimeError("injoignable")

    mgr = LocalTunnelManager(_gw(), ouvrir=boom)
    res = mgr.relever_prechauffage([Head("dev1", "node1", "gw1")])
    assert res == {"dev1": None}


def test_gateway_ids():
    assert LocalTunnelManager(_gw()).gateway_ids == {"gw1"}


def test_relever_tete_en_erreur_isolee(monkeypatch):
    """Une tête qui lève pendant la lecture devient None, sans casser le relevé."""

    def boom(*a, **k):
        raise RuntimeError("tête capricieuse")

    monkeypatch.setattr(tunnel, "lire_prechauffage", boom)
    mgr = LocalTunnelManager(_gw(), ouvrir=lambda g: _ReadFakeLink("node1", 0x03))
    res = mgr.relever_prechauffage([Head("dev1", "node1", "gw1")])
    assert res == {"dev1": None}


class _RWFakeLink:
    """Répond à la lecture 0x0025 et à l'écriture d'attribut selon la commande envoyée."""

    def __init__(self, node_id: str, mode_0025: int) -> None:
        self.node_id = node_id
        self._mode = mode_0025
        self.ferme = False
        self._cmd = None

    def envoyer(self, dev_id, node_id, trame):
        self._cmd = trame[10]  # 0x00 = lire attributs, 0x02 = écrire attributs

    def recevoir(self):
        if self._cmd == 0x02:
            resp = tunnel.entete(tunnel.CLUSTER_THERMOSTAT) + bytes([0x00, 0x40, 0x04, 0x00])
        else:
            resp = _reponse_prechauffage(self._mode)
        return (self.node_id, {"199": base64.b64encode(resp).decode()})

    def fermer(self):
        self.ferme = True


def test_ecrire_prechauffage_ok():
    link = _RWFakeLink("node1", 0x01)  # programme seul -> on ajoute le pré-chauffage
    mgr = LocalTunnelManager(_gw(), ouvrir=lambda g: link)
    assert mgr.ecrire_prechauffage(Head("dev1", "node1", "gw1"), True) is True
    assert link.ferme is True


def test_ecrire_passerelle_inconnue():
    mgr = LocalTunnelManager(_gw(), ouvrir=lambda g: None)
    with pytest.raises(tunnel.LocalIndisponible):
        mgr.ecrire_prechauffage(Head("devX", "nodeX", "gw-inconnue"), True)


def test_ecrire_mode_illisible(monkeypatch):
    monkeypatch.setattr(tunnel, "lire_mode_programmation", lambda *a, **k: None)
    link = _RWFakeLink("node1", 0x01)
    mgr = LocalTunnelManager(_gw(), ouvrir=lambda g: link)
    with pytest.raises(tunnel.LocalErreur):
        mgr.ecrire_prechauffage(Head("dev1", "node1", "gw1"), True)
    assert link.ferme is True  # fermé même en cas d'échec (finally)
