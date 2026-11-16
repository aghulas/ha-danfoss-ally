"""Tests de la pile de signature/chiffrement vendue (clés synthétiques uniquement).

Ne valide PAS le protocole réel (fait en réel ailleurs) : vérifie l'intégrité des fonctions pures
(aller-retour AES-GCM, forme du canonical, présence de la signature)."""

from custom_components.danfoss_ally_cloud.api._tuya import postdata, sign

_SIGN_KEY = "com.danfoss.ally_11:22:33:44_" + "a" * 32 + "_" + "b" * 32
_ECODE = "0123456789abcdef"
_REQ = "req-synth-0001"


def test_aes_gcm_aller_retour():
    corps = '{"hello":"monde","n":42}'
    chiffre = postdata.encrypt_post_data(corps, _REQ, _ECODE, _SIGN_KEY)
    clair = postdata.decrypt_post_data(chiffre, _REQ, _ECODE, _SIGN_KEY)
    assert clair.decode("utf-8") == corps


def test_swap_sign_string_involution():
    md5hex = "00112233445566778899aabbccddeeff"
    assert postdata.swap_sign_string(postdata.swap_sign_string(md5hex)) == md5hex


def test_canonical_trie_et_filtre():
    params = {"a": "m.test", "v": "1.0", "nonsigne": "x", "et": "3"}
    c = sign.canonical_string(params)
    # trié alpha, « nonsigne » hors liste blanche donc absent
    assert c == "a=m.test||et=3||v=1.0"


def test_build_request_body_signe():
    params = {
        "a": "m.test",
        "v": "1.0",
        "et": "3",
        "requestId": _REQ,
        "deviceId": "dev",
        "sid": "sid-synth",
        "chKey": "deadbeef",
    }
    out = postdata.build_request_body(params, '{"x":1}', _SIGN_KEY, _ECODE)
    assert "sign" in out and len(out["sign"]) == 64
    assert "postData" in out  # corps chiffré présent
