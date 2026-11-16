"""Sûreté d'écriture : validation des valeurs et garde-fou modèles (voie 1a).

Différent du MCP : pas de jeton préparer→confirmer ici. La sûreté passe par la VALIDATION des
valeurs avant envoi et par des entités indisponibles plutôt que mensongères (voir CLAUDE.md).
"""

from __future__ import annotations

from .client import CloudWriteError
from .const import WRITE_VERIFIED_PRODUCTS
from .decode import DanfossDevice


def ecriture_autorisee(dev: DanfossDevice) -> bool:
    """Vrai si le mécanisme d'écriture est câblé pour ce produit (garde-fou modèles)."""
    return bool(dev.product_id) and dev.product_id in WRITE_VERIFIED_PRODUCTS


def encode_consigne(celsius, mini: float, maxi: float, step: float = 0.5) -> int:
    """Consigne °C -> valeur DP (dixièmes), arrondie au pas et bornée. Lève CloudWriteError."""
    try:
        c = float(celsius)
    except (TypeError, ValueError) as err:
        raise CloudWriteError(f"consigne non numérique : {celsius!r}") from err
    c = round(c / step) * step
    if not mini <= c <= maxi:
        raise CloudWriteError(f"consigne hors plage : {c} °C (attendu {mini}–{maxi} °C)")
    return int(round(c * 10))
