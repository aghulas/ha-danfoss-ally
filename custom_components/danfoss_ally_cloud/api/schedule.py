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

from dataclasses import dataclass, field
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


# ================================================================================================
# Couche « contrat » (docs/contrat-interface.md §3.2) : jours en anglais mon..sun, plages
# {start, end} en « HH:MM », validation R1 et modèle Schedule. S'appuie sur les aides ci-dessus.
# ================================================================================================

DAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_TRANSITIONS_PER_DAY = 6

# Masque Tuya 7 jours, bit 0 (à gauche) = dimanche (contrat §4.1), clés de jour en anglais.
_DAY_ORDER_SUN_FIRST: tuple[str, ...] = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
_LOOP: dict[str, str] = {
    d: "".join("1" if i == p else "0" for i in range(7)) for p, d in enumerate(_DAY_ORDER_SUN_FIRST)
}

# Codes d'erreur stables (le message est traduit côté Home Assistant — contrat §5.4).
ERR_INVALID_TIME = "invalid_time"
ERR_EMPTY_OR_REVERSED = "empty_or_reversed"
ERR_OVERLAP = "overlap"
ERR_TOO_MANY = "too_many_transitions"


def day_to_loop(day: str) -> str:
    """Nom de jour anglais (``mon``…``sun``) -> masque ``loops`` d'un jour (dimanche en premier)."""
    try:
        return _LOOP[day]
    except KeyError as err:
        raise ValueError(f"jour inconnu : {day!r}") from err


def loop_to_days(loops: str) -> list[str]:
    """Masque ``loops`` -> liste des jours anglais qu'il porte (un ou plusieurs bits à 1)."""
    return [
        _DAY_ORDER_SUN_FIRST[i]
        for i, c in enumerate(loops or "")
        if c == "1" and i < len(_DAY_ORDER_SUN_FIRST)
    ]


def _to_minutes(hhmm_str: str) -> int:
    h, _, m = hhmm_str.partition(":")
    return int(h) * 60 + int(m)


def valid_hhmm(value: object) -> bool:
    """Vrai si ``value`` est une chaîne ``HH:MM`` 00:00–23:59."""
    if not isinstance(value, str):
        return False
    h, sep, m = value.partition(":")
    return (
        sep == ":"
        and len(h) == 2
        and len(m) == 2
        and h.isdigit()
        and m.isdigit()
        and 0 <= int(h) <= 23
        and 0 <= int(m) <= 59
    )


def decode_week_timer(data: object) -> dict[str, list[dict[str, str]]]:
    """Réponse brute ``[{loops, loopData}]`` -> ``{jour_en: [{start, end}]}`` (les sept jours).

    Les plages sont les fenêtres de confort (``mode`` ``at_home``) ; le reste du jour est en réduit.
    """
    out: dict[str, list[dict[str, str]]] = {d: [] for d in DAYS}
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        ranges = [
            {"start": p["startTime"], "end": p["endTime"]}
            for p in confort_periods(entry.get("loopData"))
        ]
        for day in loop_to_days(entry.get("loops", "")):
            out[day] = ranges
    return out


def count_transitions(ranges: list[dict[str, str]]) -> tuple[int, bool]:
    """Transitions qu'un jour demande à la tête, HORS celle de 00:00 : (nombre, minuit_implicite).

    Chaque plage compte son début (sauf 00:00) et sa fin (sauf si une autre plage commence à cette
    heure : plages qui se touchent). ``minuit_implicite`` : aucune plage à 00:00, la tête ajoute une
    transition « réduit » à 00:00 s'il lui reste de la place (abandonnée à 6).
    """
    ranges = ranges or []
    starts = {r["start"] for r in ranges}
    n = 0
    for r in ranges:
        if r["start"] != "00:00":
            n += 1
        if r["end"] not in starts:
            n += 1
    return n, bool(ranges) and "00:00" not in starts


def transitions_per_day(days: dict[str, list[dict[str, str]]]) -> dict[str, int]:
    """Décompte de transitions (R1, hors minuit) par jour fourni — pour l'affichage « n / 6 »."""
    out: dict[str, int] = {}
    for day, ranges in days.items():
        if all(valid_hhmm(r.get("start")) and valid_hhmm(r.get("end")) for r in ranges):
            out[day], _ = count_transitions(ranges)
    return out


def validate_day(day: str, ranges: list[dict[str, str]]) -> list[dict[str, str]]:
    """Erreurs (contrat §5.4) d'un jour. Vide = valide. S'arrête à la première étape en échec."""
    errors: list[dict[str, str]] = []
    for r in ranges:
        for value in (r.get("start"), r.get("end")):
            if not valid_hhmm(value):
                errors.append(
                    {"code": ERR_INVALID_TIME, "message": f"heure invalide : {value!r}", "day": day}
                )
    if errors:
        return errors
    for r in ranges:
        if _to_minutes(r["start"]) >= _to_minutes(r["end"]):
            errors.append(
                {
                    "code": ERR_EMPTY_OR_REVERSED,
                    "message": f"plage vide ou inversée : {r['start']}–{r['end']}",
                    "day": day,
                }
            )
    if errors:
        return errors
    ordered = sorted(ranges, key=lambda r: _to_minutes(r["start"]))
    for a, b in zip(ordered, ordered[1:], strict=False):
        if _to_minutes(b["start"]) < _to_minutes(a["end"]):
            errors.append(
                {
                    "code": ERR_OVERLAP,
                    "message": (
                        f"plages qui se chevauchent : {a['start']}–{a['end']} "
                        f"et {b['start']}–{b['end']}"
                    ),
                    "day": day,
                }
            )
    if errors:
        return errors
    n, _ = count_transitions(ordered)
    if n > MAX_TRANSITIONS_PER_DAY:
        errors.append(
            {
                "code": ERR_TOO_MANY,
                "message": (
                    f"trop de plages : {n} transitions, la tête en garde "
                    f"{MAX_TRANSITIONS_PER_DAY} au plus (3 plages séparées)"
                ),
                "day": day,
            }
        )
    return errors


def validate_days(days: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    """Erreurs de tous les jours fournis (contrat §5.4). Vide = valide."""
    errors: list[dict[str, str]] = []
    for day, ranges in days.items():
        errors.extend(validate_day(day, ranges))
    return errors


def to_periods(ranges: list[dict[str, str]]) -> list[dict[str, str]]:
    """Plages {start, end} -> ``periods`` ``[{startTime, endTime}]`` triées (write_week_day)."""
    ordered = sorted(ranges, key=lambda r: _to_minutes(r["start"]))
    return [{"startTime": r["start"], "endTime": r["end"]} for r in ordered]


@dataclass
class Schedule:
    """Programme hebdomadaire d'une cible (contrat §3.2)."""

    target: dict[str, str]
    name: str | None = None
    comfort: float | None = None
    setback: float | None = None
    days: dict[str, list[dict[str, str]]] = field(default_factory=lambda: {d: [] for d in DAYS})
    source: str = "cloud"
    read_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "name": self.name,
            "comfort": self.comfort,
            "setback": self.setback,
            "days": {d: self.days.get(d, []) for d in DAYS},
            "max_transitions_per_day": MAX_TRANSITIONS_PER_DAY,
            "source": self.source,
            "read_at": self.read_at,
        }
