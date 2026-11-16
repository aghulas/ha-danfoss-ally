"""Programme hebdomadaire des têtes/pièces Danfoss (voie 1a) : décodage et aide au ré-envoi.

Fonctions pures, sans dépendance Home Assistant ni réseau (couche réutilisable). Le programme se
lit par ``tuya.m.custom.wkf.week.timer.list`` sous la forme ``{"data": [{loops, loopData}]}`` :

- ``loops`` : masque 7 bits, bit 0 (à gauche) = DIMANCHE (``"0100000"`` = lundi).
- ``loopData`` : fenêtres de la journée, ``{startTime, endTime, mode}`` où startTime/endTime sont
  des MINUTES depuis minuit et ``mode`` vaut ``at_home`` (confort) ou ``leaving_home`` (réduit).

L'écriture (``week.timer.create``) attend au contraire des ``periods`` ``[{startTime, endTime}]`` en
texte ``"HH:MM"``, et ne porte que les fenêtres de CONFORT (le réduit est la ligne de base hors
fenêtres). Ces aides convertissent l'un vers l'autre pour RÉ-ENVOYER un jour à l'identique, ce qui
suffit à faire reprendre aux têtes la nouvelle consigne sans toucher à l'horaire.
"""

from __future__ import annotations

from typing import Any

JOURS = ("dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi")


def hhmm(minutes: int) -> str:
    """Minutes depuis minuit -> « HH:MM »."""
    m = int(minutes)
    return f"{m // 60:02d}:{m % 60:02d}"


def jour_du_loop(loops: str) -> str:
    """Masque ``loops`` d'un jour unique -> nom du jour (bit 0 = dimanche)."""
    pos = (loops or "").find("1")
    return JOURS[pos] if 0 <= pos < len(JOURS) else (loops or "")


def confort_periods(loop_data: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Fenêtres de CONFORT d'un jour -> ``periods`` ``[{startTime, endTime}]`` en « HH:MM ».

    Ne retient que les fenêtres de confort (``mode`` ``at_home`` ou absent) : ce sont les seules que
    ``week.timer.create`` porte. Les entrées « réduit » explicites sont ignorées (c'est la ligne de
    base). Les horaires sont convertis minutes -> « HH:MM ».
    """
    out: list[dict[str, str]] = []
    for fenetre in loop_data or []:
        if fenetre.get("mode") not in (None, "at_home"):
            continue
        out.append(
            {
                "startTime": hhmm(fenetre["startTime"]),
                "endTime": hhmm(fenetre["endTime"]),
            }
        )
    return out


def premier_jour_confort(data: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Première entrée de ``data`` ayant au moins une fenêtre de confort (sinon ``None``).

    Ré-envoyer ce seul jour à l'identique suffit : le cloud renvoie alors toute la semaine aux têtes
    avec les consignes du moment (constaté le 16/11/2026).
    """
    for entry in data or []:
        if confort_periods(entry.get("loopData")):
            return entry
    return None
