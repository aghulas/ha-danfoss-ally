"""Tests du décodage DP (données synthétiques uniquement — aucune donnée ni clé réelle)."""

from custom_components.danfoss_ally_cloud.api import decode


def _tete(dps, online=True, **kw):
    base = {
        "devId": "dev-synth-1",
        "name": "Salon",
        "category": "wk",
        "productId": "03wvrwpv",
        "nodeId": "node-synth",
        "meshId": "gw-synth",
        "moduleMap": {"zigbee": {"isOnline": online}},
        "dps": dps,
    }
    base.update(kw)
    return base


def test_decode_tete_complete():
    dps = {
        "1": True,
        "2": "at_home",
        "3": "Heat",
        "24": 215,  # 21.5 °C
        "16": 210,  # consigne 21.0 °C
        "34": 95,  # batterie 95 %
        "170": 40,  # ouverture vanne 40 %
        "162": True,  # demande de chaleur
        "25": "close",  # fenêtre fermée
        "30": False,  # verrou enfant
        "116": True,  # détection fenêtre activée
        "18": 280,  # borne haute 28.0
        "27": 60,  # borne basse 6.0
        "45": 0,  # pas de défaut
    }
    d = decode.decoder(_tete(dps))
    assert d.est_tete and d.categorie == "tete"
    assert d.en_ligne is True
    assert d.temperature == 21.5
    assert d.consigne == 21.0
    assert d.consignes["consigne"] == 21.0
    assert d.batterie == 95
    assert d.ouverture_vanne == 40
    assert d.demande_chaleur is True
    assert d.fenetre_ouverte is False
    assert d.verrouillage is False
    assert d.detection_fenetre is True
    assert d.borne_haute == 28.0
    assert d.borne_basse == 6.0
    assert d.mode == "at_home"
    assert d.etat == "Heat"
    assert d.defauts == []


def test_decode_consignes_par_mode():
    dps = {"118": 210, "119": 170, "114": 190, "120": 160, "121": 150}
    d = decode.decoder(_tete(dps))
    assert d.consignes == {
        "confort": 21.0,
        "reduit": 17.0,
        "manuel": 19.0,
        "pause": 16.0,
        "vacances": 15.0,
    }


def test_decode_hors_ligne():
    d = decode.decoder(_tete({"24": 200}, online=False))
    assert d.en_ligne is False
    assert d.temperature == 20.0


def test_decode_fenetre_ouverte():
    d = decode.decoder(_tete({"25": "open"}))
    assert d.fenetre_ouverte is True


def test_decode_defaut_e14_pile_faible():
    # bit 13 = E14 « pile faible » (8192) — confirmé en réel le 06/11 (cf. decode.DEFAUTS_BITS).
    d = decode.decoder(_tete({"45": 8192}))
    assert len(d.defauts) == 1
    assert d.defauts[0]["code"] == "E14"
    assert d.defauts[0]["bit"] == 13


def test_decoder_defaut_bits_multiples():
    # E6 (bit 5) + E14 (bit 13) = 32 + 8192 = 8224
    erreurs = decode.decoder_defaut(8224)
    codes = {e["code"] for e in erreurs}
    assert codes == {"E6", "E14"}


def test_decoder_defaut_accepte_code_texte():
    erreurs = decode.decoder_defaut("E10")
    assert erreurs[0]["code"] == "E10"


def test_categorie_mapping():
    assert decode.categorie("wk") == "tete"
    assert decode.categorie("kg") == "relais"
    assert decode.categorie("wg2") == "passerelle"
    assert decode.categorie("inconnu") == "autre"


def test_dp_inconnu_reste_dans_dps():
    d = decode.decoder(_tete({"999": "mystere", "24": 200}))
    assert d.dps["999"] == "mystere"


def test_decode_operation_mode_dp172():
    # R6 : DP 172 bit 0 = programme, bit 1 = pré-chauffage ; 0 = manuel.
    assert decode.decoder_operation(1) == (True, False)
    assert decode.decoder_operation(3) == (True, True)
    assert decode.decoder_operation(0) == (False, False)
    assert decode.decoder_operation("2") == (False, True)
    assert decode.decoder_operation(None) == (None, None)


def test_decode_schedule_active_et_montage():
    d = decode.decoder(_tete({"172": 1, "149": True}))
    assert d.schedule_active is True
    assert d.preheat is False
    assert d.mounting is True


def test_inconsistent_mode_vs_programme():
    assert decode.decoder(_tete({"2": "at_home", "172": 0})).inconsistent is True
    assert decode.decoder(_tete({"2": "at_home", "172": 1})).inconsistent is False
    assert decode.decoder(_tete({"2": "at_home"})).inconsistent is False  # DP 172 absent


def test_etat_tete_forme_contrat():
    d = decode.decoder(_tete({"2": "at_home", "172": 1, "149": False}))
    assert decode.etat_tete(d, room_id="13000000") == {
        "device_id": "dev-synth-1",
        "name": "Salon",
        "room_id": "13000000",
        "online": True,
        "mode_displayed": "at_home",
        "schedule_active": True,
        "preheat": False,
        "mounting": False,
        "inconsistent": False,
    }
