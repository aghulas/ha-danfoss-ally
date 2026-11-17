"""Tests de parité du tunnel local avec le connecteur MCP (données synthétiques uniquement).

Couvre les primitives portées depuis ``~/dev/danfoss-ally-mcp/local.py`` : écriture du programme
(SetWeeklySchedule), dérogation de consigne (DP 171), dégommage (0x4010/0x4011), détection de
fenêtre (0x4051), relevé de parc multi-passerelles, et les synthèses pures associées. Aucune clé ni
aucun appareil réel : trames et relevés fabriqués.
"""

import base64

import pytest

from custom_components.danfoss_ally_cloud.api.keys import GatewayKey
from custom_components.danfoss_ally_cloud.api.local import tunnel

# --- outils de doublure -----------------------------------------------------------------------


def _b64(trame: bytes) -> str:
    return base64.b64encode(trame).decode()


def _reponse_defaut(cmd_repondue: int, statut: int) -> bytes:
    """Réponse par défaut ZCL (0x0B) : [cmd répondue, statut]."""
    return tunnel.entete(tunnel.CLUSTER_THERMOSTAT) + bytes(
        [0x00, 0x40, 0x0B, cmd_repondue, statut]
    )


def _reponse_ecriture(fabricant: bool, statut: int = 0x00) -> bytes:
    """Réponse « write attributes response » (cmd 0x04)."""
    if fabricant:
        z = bytes([0x04]) + tunnel.FABRICANT.to_bytes(2, "little") + bytes([0x40, 0x04, statut])
    else:
        z = bytes([0x00, 0x40, 0x04, statut])
    return tunnel.entete(tunnel.CLUSTER_THERMOSTAT) + z


def _reponse_attribut_fab(records: list[tuple[int, int, bytes]]) -> bytes:
    """Réponse read-attributes à code fabricant (cmd 0x01)."""
    charge = b"".join(a.to_bytes(2, "little") + bytes([0x00, t]) + v for a, t, v in records)
    z = bytes([0x04]) + tunnel.FABRICANT.to_bytes(2, "little") + bytes([0x40, 0x01]) + charge
    return tunnel.entete(tunnel.CLUSTER_THERMOSTAT) + z


class _FakeLien:
    """Répond toujours la même trame, enregistre les trames (DP 198) et les DP (hors tunnel)."""

    def __init__(self, node_id: str, reponse: bytes) -> None:
        self.node_id = node_id
        self._resp = _b64(reponse)
        self.envois: list[bytes] = []
        self.dps: list[tuple[str, object]] = []

    def envoyer(self, dev_id, node_id, trame):
        self.envois.append(trame)

    def envoyer_dp(self, dev_id, node_id, dp, valeur):
        self.dps.append((dp, valeur))

    def recevoir(self):
        return (self.node_id, {"199": self._resp})


# --- 1. écriture du programme (SetWeeklySchedule) ---------------------------------------------


def test_ecrire_jour_accepte():
    lien = _FakeLien("node-1", _reponse_defaut(0x01, 0x00))
    statut = tunnel.ecrire_jour(
        lien, "dev-1", "node-1", "lundi", [{"h": "00:00", "c": 17.0}, {"h": "06:30", "c": 21.0}]
    )
    assert statut == 0
    assert lien.envois  # une trame SetWeeklySchedule a été envoyée
    z = lien.envois[-1][8:]
    assert z[:3] == bytes([0x01, 0x40, 0x01]) and z[3] == 2  # cmd 0x01, 2 transitions


def test_ecrire_jour_statut_erreur():
    lien = _FakeLien("node-1", _reponse_defaut(0x01, 0x85))
    assert tunnel.ecrire_jour(lien, "dev-1", "node-1", "mardi", [{"h": "00:00", "c": 19.0}]) == 0x85


def test_ecrire_jour_une_seule_transition_a_minuit():
    # R1 : une journée à une seule transition, à 00:00, est valide.
    lien = _FakeLien("node-1", _reponse_defaut(0x01, 0x00))
    assert tunnel.ecrire_jour(lien, "dev-1", "node-1", "samedi", [{"h": "00:00", "c": 16.0}]) == 0


def test_ecrire_jour_six_transitions_valide():
    # R1 : jusqu'à six transitions par jour, la première à 00:00.
    tr = [{"h": "00:00", "c": 17.0}]
    tr += [{"h": f"{6 + i:02d}:00", "c": 21.0 if i % 2 == 0 else 17.0} for i in range(5)]
    assert len(tr) == 6
    lien = _FakeLien("node-1", _reponse_defaut(0x01, 0x00))
    assert tunnel.ecrire_jour(lien, "dev-1", "node-1", "jeudi", tr) == 0


def test_ecrire_jour_sept_transitions_refus():
    tr = [{"h": f"{i:02d}:00", "c": 20.0} for i in range(7)]
    lien = _FakeLien("node-1", _reponse_defaut(0x01, 0x00))
    with pytest.raises(tunnel.LocalErreur):
        tunnel.ecrire_jour(lien, "dev-1", "node-1", "jeudi", tr)


def test_ecrire_jour_premiere_pas_minuit_refus():
    lien = _FakeLien("node-1", _reponse_defaut(0x01, 0x00))
    with pytest.raises(tunnel.LocalErreur):
        tunnel.ecrire_jour(lien, "dev-1", "node-1", "jeudi", [{"h": "06:00", "c": 21.0}])


# --- 2. dérogation de consigne (DP 171) -------------------------------------------------------


def test_valeur_consigne_centiemes():
    assert tunnel.valeur_consigne(21.0) == 2100
    assert tunnel.valeur_consigne(16.5) == 1650


@pytest.mark.parametrize("c", [4.5, 35.5, 20.3])
def test_valeur_consigne_hors_plage(c):
    with pytest.raises(tunnel.LocalErreur):
        tunnel.valeur_consigne(c)


def test_ecrire_consigne_publie_dp171():
    lien = _FakeLien("node-1", b"")
    val = tunnel.ecrire_consigne(lien, "dev-1", "node-1", 19.5)
    assert val == 1950
    assert lien.dps == [("171", 1950)]


# --- 3. dégommage (0x4010 / 0x4011) -----------------------------------------------------------


def test_degommage_valeurs_encodage():
    enreg = tunnel.degommage_valeurs("mercredi", "12:30")
    assert enreg == [(0x4010, 0x30, 3), (0x4011, 0x21, 750)]  # mercredi = index 3 ; 12:30 = 750 min


def test_degommage_valeurs_jour_inconnu():
    with pytest.raises(tunnel.LocalErreur):
        tunnel.degommage_valeurs("lunedì", "12:00")


def test_ecrire_degommage_fabricant():
    lien = _FakeLien("node-1", _reponse_ecriture(fabricant=True))
    assert tunnel.ecrire_degommage(lien, "dev-1", "node-1", "vendredi", "09:00") == 0
    z = lien.envois[-1][8:]
    assert z[0] & 0x04  # trame à code fabricant
    assert int.from_bytes(z[1:3], "little") == tunnel.FABRICANT


# --- 4. détection de fenêtre (0x4051) + réglages DP -------------------------------------------


def test_lire_detection_fenetre():
    lien = _FakeLien("node-1", _reponse_attribut_fab([(0x4051, 0x10, bytes([0x01]))]))
    assert tunnel.lire_detection_fenetre(lien, "dev-1", "node-1", duree=1, essais=1) is True


def test_lire_detection_fenetre_fermee():
    lien = _FakeLien("node-1", _reponse_attribut_fab([(0x4051, 0x10, bytes([0x00]))]))
    assert tunnel.lire_detection_fenetre(lien, "dev-1", "node-1", duree=1, essais=1) is False


def test_ecrire_reglage_dp_fenetre():
    lien = _FakeLien("node-1", b"")
    assert tunnel.ecrire_reglage_dp(lien, "dev-1", "node-1", "detection_fenetre", True) is True
    assert lien.dps == [("116", True)]


def test_ecrire_reglage_dp_verrou():
    lien = _FakeLien("node-1", b"")
    tunnel.ecrire_reglage_dp(lien, "dev-1", "node-1", "verrouillage_enfant", 1)
    assert lien.dps == [("30", True)]  # coercé en bool par REGLAGES_DP


def test_ecrire_reglage_dp_inconnu():
    lien = _FakeLien("node-1", b"")
    with pytest.raises(tunnel.LocalErreur):
        tunnel.ecrire_reglage_dp(lien, "dev-1", "node-1", "mode_vacances", True)


# --- nommer : attributs Danfoss ---------------------------------------------------------------


def test_nommer_degommage_et_booleens():
    vals = {0x4010: 3, 0x4011: 750, 0x4051: 1, 0x4014: 0}
    out = tunnel.nommer(vals, tunnel.ATTRIBUTS_DANFOSS_A + tunnel.ATTRIBUTS_DANFOSS_B)
    assert out["degommage_jour"] == "mercredi"
    assert out["degommage_heure"] == "12:30"
    assert out["detection_fenetre"] is True
    assert out["orientation"] is False


def test_nommer_adaptation_etat():
    out = tunnel.nommer({0x404D: 0x03}, tunnel.ATTRIBUTS_DANFOSS_B)
    assert out["adaptation_etat"] == 3
    assert out["adaptation_faite"] is True


# --- transitions depuis fenêtres + plages -----------------------------------------------------


def test_transitions_depuis_fenetres():
    tr = tunnel.transitions_depuis_fenetres(
        [{"debut": "08:00", "fin": "12:00"}, {"debut": "14:00", "fin": "18:00"}], 21.0, 17.0
    )
    assert tr[0] == {"h": "00:00", "c": 17.0}
    assert {"h": "08:00", "c": 21.0} in tr and {"h": "14:00", "c": 21.0} in tr


def test_transitions_depuis_fenetres_debut_minuit():
    tr = tunnel.transitions_depuis_fenetres([{"debut": "00:00", "fin": "06:00"}], 21.0, 17.0)
    assert tr[0] == {"h": "00:00", "c": 21.0}
    assert tr[1] == {"h": "06:00", "c": 17.0}


def test_transitions_depuis_fenetres_chevauchement():
    with pytest.raises(tunnel.LocalErreur):
        tunnel.transitions_depuis_fenetres(
            [{"debut": "08:00", "fin": "12:00"}, {"debut": "11:00", "fin": "13:00"}], 21.0, 17.0
        )


def test_plages_journee_commence_en_confort():
    # Correction MCP : une plage à 00:00 doit apparaître (référence = consigne la plus basse).
    tr = [{"h": "00:00", "c": 21.0}, {"h": "22:00", "c": 17.0}]
    assert tunnel.plages(tr) == [{"debut": "00:00", "fin": "22:00", "consigne": 21.0}]


def test_plages_fusion_segments_consecutifs():
    tr = [
        {"h": "00:00", "c": 17.0},
        {"h": "06:00", "c": 21.0},
        {"h": "12:00", "c": 21.0},
        {"h": "18:00", "c": 17.0},
    ]
    assert tunnel.plages(tr) == [{"debut": "06:00", "fin": "18:00", "consigne": 21.0}]


# --- 5. relevé de parc + lire_tete + synthèses ------------------------------------------------


class _FakeTete:
    """Répond à chaque relevé (standard / danfoss A / danfoss B) et à chaque jour de programme."""

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self._reponse: bytes | None = None

    def envoyer(self, dev_id, node_id, trame):
        z = trame[8:]
        if z[0] == 0x01 and z[2] == 0x02:  # lecture programme (specifique, cmd 0x02)
            bit = z[3]
            corps = (
                bytes([1, bit, 0x01])
                + (0).to_bytes(2, "little")
                + (2100).to_bytes(2, "little", signed=True)
            )
            self._reponse = (
                tunnel.entete(tunnel.CLUSTER_THERMOSTAT) + bytes([0x01, 0x40, 0x00]) + corps
            )
        elif z[0] == 0x00:  # lecture attributs standard (non fabricant, cmd read 0x00)
            self._reponse = _reponse_attribut_fab_std(
                [
                    (0x0012, 0x29, (2100).to_bytes(2, "little", signed=True)),
                    (0x0025, 0x30, bytes([0x03])),
                ]
            )
        elif z[0] == 0x04:  # lecture attributs Danfoss (fabricant)
            premier = int.from_bytes(trame[13:15], "little")
            if premier == 0x4010:
                self._reponse = _reponse_attribut_fab(
                    [(0x4010, 0x30, bytes([3])), (0x4011, 0x21, (750).to_bytes(2, "little"))]
                )
            else:  # danfoss B : 0x404B (1er demandé, sentinelle) + 0x4051 détection de fenêtre
                self._reponse = _reponse_attribut_fab(
                    [
                        (0x404B, 0x29, (0).to_bytes(2, "little", signed=True)),
                        (0x4051, 0x10, bytes([0x01])),
                    ]
                )

    def recevoir(self):
        return (self.node_id, {"199": _b64(self._reponse)}) if self._reponse else None

    def fermer(self):
        pass


def _reponse_attribut_fab_std(records: list[tuple[int, int, bytes]]) -> bytes:
    """Réponse read-attributes NON fabricant (cmd 0x01)."""
    charge = b"".join(a.to_bytes(2, "little") + bytes([0x00, t]) + v for a, t, v in records)
    return tunnel.entete(tunnel.CLUSTER_THERMOSTAT) + bytes([0x00, 0x40, 0x01]) + charge


def test_lire_tete_complet():
    e = tunnel.lire_tete(_FakeTete("node-1"), "dev-1", "node-1")
    assert not e.get("injoignable")
    assert e["attributs"]["mode_programmation"] == 3
    assert e["attributs"]["pre_chauffage"] is True
    assert e["attributs"]["degommage_jour"] == "mercredi"
    assert e["attributs"]["detection_fenetre"] is True
    assert set(e["programme"]) == set(tunnel.JOURS)
    assert e["programme"]["lundi"] == [{"h": "00:00", "c": 21.0}]


class _TeteMuette:
    """Ne répond jamais : tête injoignable."""

    def envoyer(self, *a):
        pass

    def recevoir(self):
        return None

    def fermer(self):
        pass


def test_lire_tete_injoignable():
    e = tunnel.lire_tete(_TeteMuette(), "dev-1", "node-1", programme=True)
    assert e.get("injoignable") is True
    assert e["attributs"] == {}


class _Head:
    def __init__(self, dev_id, node_id, gateway_id):
        self.dev_id = dev_id
        self.node_id = node_id
        self.gateway_id = gateway_id


def test_releve_multi_passerelles():
    gws = {
        "gw-A": GatewayKey("gw-A", "A", "k", ip="10.0.0.1"),
        "gw-B": GatewayKey("gw-B", "B", "k", ip="10.0.0.2"),
    }
    heads = [
        _Head("tete-1", "node-1", "gw-A"),
        _Head("tete-2", "node-2", "gw-A"),
        _Head("tete-3", "node-3", "gw-B"),
    ]
    res = tunnel.releve(gws, heads, ouvrir=lambda gw: _LienParc())
    assert set(res) == {"tete-1", "tete-2", "tete-3"}
    assert all(not e.get("injoignable") for e in res.values())


class _LienParc:
    """Lien de passerelle qui répond à n'importe quelle tête (sur le node demandé dans la trame)."""

    def __init__(self) -> None:
        self._tete = _FakeTete("")

    def envoyer(self, dev_id, node_id, trame):
        self._tete.node_id = node_id
        self._tete.envoyer(dev_id, node_id, trame)

    def recevoir(self):
        return self._tete.recevoir()

    def fermer(self):
        pass


def test_releve_passerelle_injoignable():
    gws = {"gw-A": GatewayKey("gw-A", "A", "k", ip="10.0.0.1")}
    heads = [_Head("tete-1", "node-1", "gw-A")]

    def ouvrir(gw):
        raise tunnel.LocalIndisponible("passerelle KO")

    res = tunnel.releve(gws, heads, ouvrir=ouvrir)
    assert res["tete-1"]["injoignable"] is True
    assert "erreur" in res["tete-1"]


def test_releve_ignore_passerelle_inconnue():
    gws = {"gw-A": GatewayKey("gw-A", "A", "k", ip="10.0.0.1")}
    heads = [_Head("tete-x", "node-x", "gw-ABSENTE")]
    assert tunnel.releve(gws, heads, ouvrir=lambda gw: _LienParc()) == {}


# --- synthèses pures --------------------------------------------------------------------------


def _releve_tete(programme, attributs=None):
    return {"attributs": attributs or {"borne_haute": 24.0}, "programme": programme, "manques": []}


def test_resumer_tete():
    prog = {
        "lundi": [{"h": "00:00", "c": 17.0}, {"h": "08:00", "c": 21.0}, {"h": "18:00", "c": 17.0}]
    }
    out = tunnel.resumer_tete(_releve_tete(prog))
    assert out["confort"] == 21.0
    assert out["reduit"] == 17.0
    assert out["plages"]["lundi"] == ["08:00–18:00"]


def test_resumer_tete_injoignable():
    assert tunnel.resumer_tete({"attributs": {}}) == {"injoignable": True}


def test_comparer_programme_et_reglages():
    ref = {
        "tete-1": _releve_tete(
            {"lundi": [{"h": "00:00", "c": 17.0}]}, {"borne_haute": 24.0, "detection_fenetre": True}
        ),
        "tete-2": _releve_tete({}, {"borne_haute": 24.0}),
    }
    nouv = {
        "tete-1": _releve_tete(
            {"lundi": [{"h": "00:00", "c": 19.0}]},
            {"borne_haute": 24.0, "detection_fenetre": False},
        ),
        "tete-2": {"attributs": {}},  # devenue injoignable
    }
    d = tunnel.comparer(ref, nouv)
    assert d["programmes_modifies"] == [
        {
            "tete": "tete-1",
            "jour": "lundi",
            "avant": [{"h": "00:00", "c": 17.0}],
            "apres": [{"h": "00:00", "c": 19.0}],
        }
    ]
    assert {"tete": "tete-1", "reglage": "detection_fenetre", "avant": True, "apres": False} in (
        d["reglages_modifies"]
    )
    assert d["nouvelles_injoignables"] == ["tete-2"]
    assert d["injoignables"] == ["tete-2"]
