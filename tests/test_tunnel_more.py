"""Tests complémentaires du tunnel local : branches restantes + LocalLink (faux tinytuya)."""

import base64
import sys

import pytest

from custom_components.danfoss_ally_cloud.api.keys import GatewayKey
from custom_components.danfoss_ally_cloud.api.local import tunnel

# --- trames : branches fabricant et programme -------------------------------------------------


def test_trame_lire_attributs_fabricant():
    t = tunnel.trame_lire_attributs([0x0012], fabricant=True, seq=0x40)
    z = t[8:]
    assert z[0] & 0x04  # bit fabricant
    assert int.from_bytes(z[1:3], "little") == tunnel.FABRICANT


def test_trame_ecrire_attributs_fabricant():
    t = tunnel.trame_ecrire_attributs([(0x0025, 0x30, 3)], fabricant=True)
    z = t[8:]
    assert z[0] & 0x04 and int.from_bytes(z[1:3], "little") == tunnel.FABRICANT


def test_trame_lire_programme():
    t = tunnel.trame_lire_programme("jeudi")
    assert t[8:] == bytes([0x01, 0x40, 0x02, tunnel.BIT_JOUR["jeudi"], 0x01])


def test_trame_ecrire_programme():
    t = tunnel.trame_ecrire_programme(
        "lundi", [{"h": "00:00", "c": 17.0}, {"h": "06:30", "c": 21.0}]
    )
    z = t[8:]
    assert z[:3] == bytes([0x01, 0x40, 0x01])
    assert z[3] == 2 and z[4] == tunnel.BIT_JOUR["lundi"]  # 2 transitions, bit du jour


# --- minutes / verifier_transitions : chemins d'erreur ----------------------------------------


def test_minutes_valide():
    assert tunnel.minutes("06:30") == 390
    assert tunnel.minutes("24:00") == 1440


@pytest.mark.parametrize("h", ["bananes", "6h30", "25:00", "00:70"])
def test_minutes_invalide(h):
    with pytest.raises(tunnel.LocalErreur):
        tunnel.minutes(h)


def test_verifier_transitions_trop_nombreuses():
    tr = [{"h": f"{i:02d}:00", "c": 20.0} for i in range(7)]
    with pytest.raises(tunnel.LocalErreur):
        tunnel.verifier_transitions(tr)


def test_verifier_transitions_desordre():
    with pytest.raises(tunnel.LocalErreur):
        tunnel.verifier_transitions([{"h": "00:00", "c": 18.0}, {"h": "00:00", "c": 21.0}])


# --- décodeurs : branches restantes -----------------------------------------------------------


def test_decoder_trame_fabricant():
    # fc avec bit fabricant (0x04) : z = [fc, fab_lo, fab_hi, seq, cmd, ...charge]
    z = bytes([0x04]) + tunnel.FABRICANT.to_bytes(2, "little") + bytes([0x40, 0x01, 0xAA])
    brut = tunnel.entete(tunnel.CLUSTER_THERMOSTAT) + z
    f = tunnel.decoder_trame(brut)
    assert f["fabricant"] == tunnel.FABRICANT
    assert f["commande"] == 0x01
    assert f["charge"] == b"\xaa"


def test_decoder_attributs_statut_non_nul_et_coupure():
    # 0x0012 statut!=0 -> None ; puis attribut tronqué -> arrêt.
    charge = (0x0012).to_bytes(2, "little") + bytes([0x02])  # statut 0x02
    charge += (0x0015).to_bytes(2, "little") + bytes([0x00, 0x29, 0x10])  # type 0x29 = 2 o, tronqué
    out = tunnel.decoder_attributs(charge)
    assert out[0x0012] is None
    assert 0x0015 not in out  # coupure sur longueur insuffisante


def test_decoder_programme_coupure():
    # n=2 annoncé mais une seule transition complète -> break.
    charge = bytes([2, tunnel.BIT_JOUR["mardi"], 0x01])
    charge += (0).to_bytes(2, "little") + (2100).to_bytes(2, "little", signed=True)
    charge += (360).to_bytes(2, "little")  # 2e transition incomplète
    _, tr = tunnel.decoder_programme(charge)
    assert len(tr) == 1


def test_nommer_autre_attribut():
    # 0x0030 (source_consigne) : branche else, valeur brute.
    out = tunnel.nommer({0x0030: 2}, tunnel.ATTRIBUTS_STD)
    assert out["source_consigne"] == 2


def test_plages_vide():
    assert tunnel.plages(None) == []
    assert tunnel.plages([]) == []


# --- demander / lire_jour / lire_programme / écritures (doublures) ----------------------------


class _FakeLienJour:
    """Répond au jour demandé en lisant le bit dans la trame envoyée (offset 11)."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self._bit = None

    def envoyer(self, dev_id, node_id, trame):
        self._bit = trame[11]

    def recevoir(self):
        corps = (
            bytes([1, self._bit, 0x01])
            + (0).to_bytes(2, "little")
            + (2100).to_bytes(2, "little", signed=True)
        )
        z = bytes([0x01, 0x40, 0x00]) + corps  # specifique, cmd 0x00
        resp = tunnel.entete(tunnel.CLUSTER_THERMOSTAT) + z
        return (self.node_id, {"199": base64.b64encode(resp).decode()})


def test_lire_jour():
    lien = _FakeLienJour("node-1")
    tr = tunnel.lire_jour(lien, "dev-1", "node-1", "mardi", duree=1, essais=1)
    assert tr == [{"h": "00:00", "c": 21.0}]


def test_lire_programme_sept_jours():
    lien = _FakeLienJour("node-1")
    prog = tunnel.lire_programme(lien, "dev-1", "node-1")
    assert set(prog) == set(tunnel.JOURS)
    assert prog["dimanche"] == [{"h": "00:00", "c": 21.0}]


def test_lire_mode_programmation():
    reponse = tunnel.entete(tunnel.CLUSTER_THERMOSTAT) + bytes([0x00, 0x40, 0x01])
    reponse += (
        (0x0012).to_bytes(2, "little")
        + bytes([0x00, 0x29])
        + (2100).to_bytes(2, "little", signed=True)
    )
    reponse += (0x0025).to_bytes(2, "little") + bytes([0x00, 0x30, 0x03])

    class _L:
        def envoyer(self, *a):
            pass

        def recevoir(self):
            return ("node-1", {"199": base64.b64encode(reponse).decode()})

    assert tunnel.lire_mode_programmation(_L(), "dev-1", "node-1", duree=1, essais=1) == 3


def test_demander_base64_invalide_rend_none():
    class _L:
        def envoyer(self, *a):
            pass

        def recevoir(self):
            return ("node-1", {"199": "!!!pas du base64!!!"})

    out = tunnel.demander(_L(), "dev-1", "node-1", b"x", lambda f: 1, duree=1, essais=1)
    assert out is None


def test_lire_attributs_rejette_trame_specifique():
    # Réponse "specifique" (programme) là où on attend des attributs -> accepte renvoie None.
    corps = (
        bytes([1, tunnel.BIT_JOUR["lundi"], 0x01])
        + (0).to_bytes(2, "little")
        + (2100).to_bytes(2, "little", signed=True)
    )
    resp = tunnel.entete(tunnel.CLUSTER_THERMOSTAT) + bytes([0x01, 0x40, 0x00]) + corps

    class _L:
        def envoyer(self, *a):
            pass

        def recevoir(self):
            return ("node-1", {"199": base64.b64encode(resp).decode()})

    assert tunnel.lire_prechauffage(_L(), "dev-1", "node-1", duree=1, essais=1) is None


def test_ecrire_prechauffage():
    reponse = tunnel.entete(tunnel.CLUSTER_THERMOSTAT) + bytes([0x00, 0x40, 0x04, 0x00])

    class _L:
        def __init__(self):
            self.envois = []

        def envoyer(self, dev, node, trame):
            self.envois.append(trame)

        def recevoir(self):
            return ("node-1", {"199": base64.b64encode(reponse).decode()})

    lien = _L()
    assert tunnel.ecrire_prechauffage(lien, "dev-1", "node-1", True, 0x01) == 0
    assert lien.envois


# --- LocalLink (faux tinytuya injecté dans sys.modules) ---------------------------------------


class _FakeDevice:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.values: dict = {}

    def set_socketTimeout(self, t):
        self.timeout = t

    def set_value(self, dp, val, nowait=False):
        self.values[dp] = val

    def heartbeat(self, nowait=False):
        pass

    def receive(self):
        return {"cid": "node-1", "dps": {"199": "charge"}}

    def close(self):
        self.closed = True


class _FakeTinytuya:
    Device = _FakeDevice


@pytest.fixture
def faux_tinytuya(monkeypatch):
    monkeypatch.setitem(sys.modules, "tinytuya", _FakeTinytuya)
    return _FakeTinytuya


def test_locallink_sans_ip_leve():
    with pytest.raises(tunnel.LocalIndisponible):
        tunnel.LocalLink(GatewayKey("gw-1", "GW", "lk", ip=None))


def test_locallink_cycle(faux_tinytuya):
    link = tunnel.LocalLink(GatewayKey("gw-1", "GW", "lk", ip="10.0.0.9"))
    link.envoyer("dev-1", "node-1", b"\x01\x02")
    recu = link.recevoir()
    assert recu == ("node-1", {"199": "charge"})
    link.fermer()
