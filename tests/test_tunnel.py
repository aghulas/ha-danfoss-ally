"""Tests du tunnel local (fonctions pures + doublure de lien, données synthétiques)."""

import base64

import pytest

from custom_components.danfoss_ally_cloud.api.local import tunnel


def _reponse_attribut(attr: int, typ: int, valeur: bytes) -> bytes:
    """Trame de réponse DP 199 « read attributes response » (non fabricant, cmd 0x01)."""
    charge = attr.to_bytes(2, "little") + bytes([0x00, typ]) + valeur
    z = bytes([0x00, 0x40, 0x01]) + charge  # fc=0, seq, cmd=0x01
    return tunnel.entete(tunnel.CLUSTER_THERMOSTAT) + z


def _reponse_multi(records: list[tuple[int, int, bytes]]) -> bytes:
    """Réponse read-attributes multi-attributs (records = [(attr, type, valeur)])."""
    charge = b"".join(a.to_bytes(2, "little") + bytes([0x00, t]) + v for a, t, v in records)
    return tunnel.entete(tunnel.CLUSTER_THERMOSTAT) + bytes([0x00, 0x40, 0x01]) + charge


# Réponse réaliste : 1er attribut demandé (0x0012, sentinelle) + 0x0025 pré-chauffage.
def _reponse_prechauffage(valeur_0025: int) -> bytes:
    return _reponse_multi(
        [
            (0x0012, 0x29, (2100).to_bytes(2, "little", signed=True)),
            (0x0025, 0x30, bytes([valeur_0025])),
        ]
    )


class _FakeLien:
    def __init__(self, node_id: str, reponse: bytes) -> None:
        self.node_id = node_id
        self._resp = base64.b64encode(reponse).decode()
        self.envois: list[bytes] = []

    def envoyer(self, dev_id, node_id, trame):
        self.envois.append(trame)

    def recevoir(self):
        return (self.node_id, {"199": self._resp})


def test_entete():
    assert tunnel.entete(0x0201) == bytes.fromhex("4001") + b"\x01\x02" + bytes.fromhex("04010100")


def test_decoder_trame_reponse_attribut():
    brut = _reponse_attribut(0x0025, 0x30, bytes([0x03]))
    f = tunnel.decoder_trame(brut)
    assert f is not None
    assert f["cluster"] == tunnel.CLUSTER_THERMOSTAT
    assert f["commande"] == 0x01
    assert f["fabricant"] is None
    assert f["specifique"] is False


def test_decoder_trame_rejette_non_trame():
    assert tunnel.decoder_trame(b"\x00\x01\x02") is None


def test_decoder_attributs_et_nommer_prechauffage():
    # 0x0025 = 3 -> programme + pré-chauffage (bit 1).
    f = tunnel.decoder_trame(_reponse_attribut(0x0025, 0x30, bytes([0x03])))
    vals = tunnel.decoder_attributs(f["charge"])
    assert vals[0x0025] == 3
    nomme = tunnel.nommer(vals, tunnel.ATTRIBUTS_STD)
    assert nomme["mode_programmation"] == 3
    assert nomme["pre_chauffage"] is True


def test_nommer_sans_prechauffage():
    f = tunnel.decoder_trame(_reponse_attribut(0x0025, 0x30, bytes([0x01])))
    nomme = tunnel.nommer(tunnel.decoder_attributs(f["charge"]), tunnel.ATTRIBUTS_STD)
    assert nomme["pre_chauffage"] is False


def test_lire_prechauffage_via_doublure():
    lien = _FakeLien("node-xyz", _reponse_prechauffage(0x03))
    assert tunnel.lire_prechauffage(lien, "dev-1", "node-xyz", duree=1) is True
    assert lien.envois  # une trame a bien été envoyée


def test_lire_prechauffage_mauvais_noeud_rend_none():
    lien = _FakeLien("autre-node", _reponse_prechauffage(0x03))
    assert tunnel.lire_prechauffage(lien, "dev-1", "node-xyz", duree=1, essais=1) is None


def test_decoder_programme():
    charge = (
        bytes([1, tunnel.BIT_JOUR["mercredi"], 0x01])
        + (0).to_bytes(2, "little")
        + (2100).to_bytes(2, "little", signed=True)
    )
    bit, tr = tunnel.decoder_programme(charge)
    assert bit == tunnel.BIT_JOUR["mercredi"]
    assert tr == [{"h": "00:00", "c": 21.0}]


def test_verifier_transitions_valide():
    tr = tunnel.verifier_transitions([{"h": "00:00", "c": 17.0}, {"h": "06:30", "c": 21.0}])
    assert tr[1]["h"] == "06:30"


def test_verifier_transitions_refus_premiere_pas_minuit():
    with pytest.raises(tunnel.LocalErreur):
        tunnel.verifier_transitions([{"h": "06:00", "c": 21.0}])


def test_verifier_transitions_refus_consigne_hors_plage():
    with pytest.raises(tunnel.LocalErreur):
        tunnel.verifier_transitions([{"h": "00:00", "c": 40.0}])


def test_trame_ecrire_attributs_type_inconnu():
    with pytest.raises(tunnel.LocalErreur):
        tunnel.trame_ecrire_attributs([(0x0025, 0xFF, 1)], fabricant=False)


def test_plages_confort():
    tr = [{"h": "00:00", "c": 17.0}, {"h": "06:00", "c": 21.0}, {"h": "22:00", "c": 17.0}]
    assert tunnel.plages(tr) == [{"debut": "06:00", "fin": "22:00", "consigne": 21.0}]


def test_nouveau_mode_prechauffage():
    assert tunnel.nouveau_mode_prechauffage(0x01, True) == 0x03  # programme -> + pré-chauffage
    assert tunnel.nouveau_mode_prechauffage(0x03, False) == 0x01  # retire le pré-chauffage
    assert tunnel.nouveau_mode_prechauffage(0x03, True) == 0x03  # déjà actif
    assert tunnel.nouveau_mode_prechauffage(0x01, False) == 0x01  # déjà inactif


def test_ecrire_attributs_via_doublure():
    # Réponse « write attributes response » (cmd 0x04, statut 0 = accepté).
    reponse = tunnel.entete(tunnel.CLUSTER_THERMOSTAT) + bytes([0x00, 0x40, 0x04, 0x00])
    lien = _FakeLien("node-xyz", reponse)
    statut = tunnel.ecrire_attributs(
        lien, "dev-1", "node-xyz", [(0x0025, 0x30, 3)], fabricant=False
    )
    assert statut == 0
