"""Signature de l'API mobile Tuya (Danfoss Ally) — reversé et validé (voir danfoss-ally-mcp).

    sign = HMAC_SHA256(key, canonical)                         (hex, 64 car.)
    canonical = "||".join("<k>=<v>" for k in sorted(params))   # clés triées
    postData (dans le canonical) = post_data_md5(valeur du fil) # pas le corps en clair

La clé HMAC est composée : "com.danfoss.ally_<deviceId hex-colon>_<appSecret1>_<appSecret2>".
Ce sont des SECRETS : fournis à l'exécution, jamais codés en dur ni journalisés.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac

# Clés retenues dans le canonical signé (liste autoritative du SDK décompilé).
SIGN_WHITELIST = frozenset(
    (
        "a",
        "v",
        "lat",
        "lon",
        "lang",
        "deviceId",
        "appVersion",
        "ttid",
        "isH5",
        "h5Token",
        "os",
        "clientId",
        "postData",
        "time",
        "requestId",
        "et",
        "n4h5",
        "sid",
        "chKey",
        "sp",
    )
)


def canonical_string(params: dict) -> str:
    """Chaîne canonique : `clé=valeur` triées, jointes par `||`, limitée à SIGN_WHITELIST.

    Le champ ``postData`` doit DÉJÀ contenir ``post_data_md5(corps)``, pas le corps brut.
    """
    return "||".join(
        f"{k}={params[k]}"
        for k in sorted(params)
        if k in SIGN_WHITELIST and params[k] is not None and params[k] != ""
    )


def canonical_from_request(params: dict, post_data_wire: str | bytes | None) -> str:
    """Canonical à signer à partir des paramètres d'URL et de la valeur `postData` du fil.

    Règle (et=3 inclus) : ``postData = post_data_md5(<valeur postData du fil>)``. Pour et=3,
    la valeur du fil est le blob chiffré, donc PAS le md5 du corps en clair.
    """
    from .postdata import post_data_md5  # import local : évite tout cycle

    p = dict(params)
    if post_data_wire is not None and post_data_wire != "" and post_data_wire != b"":
        p["postData"] = post_data_md5(post_data_wire)
    else:
        p.pop("postData", None)
    return canonical_string(p)


def sign_canonical(canonical: str, key: str) -> str:
    """HMAC-SHA256(key, canonical) en hexadécimal — le cœur de l'algorithme."""
    return _hmac.new(key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def build_key(
    device_id_colon: str, app_secret1: str, app_secret2: str, package: str = "com.danfoss.ally"
) -> str:
    """Reconstruit la clé HMAC à partir de ses composants (deviceId hex-colon + 2 appSecrets)."""
    return "_".join([package, device_id_colon, app_secret1, app_secret2])
