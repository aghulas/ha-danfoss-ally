"""Pièces (groupes Tuya) : modèle et agrégation de l'état des têtes membres.

Fonctions et dataclasses pures, sans dépendance Home Assistant ni réseau (couche réutilisable).
Danfoss pilote une pièce multi-têtes par son GROUPE : programme et consignes y sont communs. On
expose donc un thermostat par PIÈCE dont l'état agrège celui des têtes membres.

Agrégation retenue :
- température : moyenne des têtes **en ligne** (les hors-ligne figeraient une valeur mensongère) ;
- consignes (active, confort/réduit) et mode : ceux d'une tête de référence en ligne — les têtes
  d'un même groupe sont synchronisées, donc n'importe quel membre en ligne fait foi ;
- chauffe : vrai si **au moins une** tête ouvre sa vanne ;
- en ligne : vrai si au moins une tête du groupe est en ligne.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .decode import DanfossDevice


@dataclass(frozen=True)
class Piece:
    """Une pièce = un groupe Tuya (resType 2) et la liste de ses têtes membres."""

    group_id: str
    nom: str
    pid: str | None
    home_gid: str
    membres: tuple[str, ...]


@dataclass
class RoomState:
    """État agrégé d'une pièce pour le thermostat de pièce (lecture)."""

    group_id: str
    nom: str
    pid: str | None
    nb_tetes: int
    en_ligne: bool = False
    temperature: float | None = None
    consigne: float | None = None  # consigne active (°C)
    consignes: dict[str, float] = field(default_factory=dict)
    mode: str | None = None
    chauffe: bool | None = None
    borne_basse: float | None = None
    borne_haute: float | None = None


def aggregate_room(piece: Piece, membres: list[DanfossDevice]) -> RoomState:
    """Construit l'état agrégé d'une pièce à partir de ses têtes membres présentes."""
    online = [m for m in membres if m.en_ligne]
    temps = [m.temperature for m in online if m.temperature is not None]
    temperature = round(sum(temps) / len(temps), 1) if temps else None
    ref = online[0] if online else (membres[0] if membres else None)
    return RoomState(
        group_id=piece.group_id,
        nom=piece.nom,
        pid=piece.pid,
        nb_tetes=len(piece.membres),
        en_ligne=bool(online),
        temperature=temperature,
        consigne=ref.consigne if ref else None,
        consignes=dict(ref.consignes) if ref else {},
        mode=ref.mode if ref else None,
        chauffe=(any((m.ouverture_vanne or 0) > 0 for m in online) if online else None),
        borne_basse=ref.borne_basse if ref else None,
        borne_haute=ref.borne_haute if ref else None,
    )
