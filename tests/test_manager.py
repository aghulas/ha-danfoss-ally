"""Tests du gestionnaire de tunnel local (relevé threadé, doublure sans réseau)."""

import base64

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
