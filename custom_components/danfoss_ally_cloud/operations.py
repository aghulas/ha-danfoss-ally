"""Opérations partagées entre les actions (services) et les commandes WebSocket.

Une seule implémentation par opération (contrat §5.3) : lecture des pièces, lecture/écriture du
programme, retour au programme, consigne de pièce (R3). Les écritures créent un `WriteJob` suivi par
`jobs/subscribe` et vérifié de façon différée (jamais bloquante). Les erreurs portent un code stable
du contrat (§5.4) ; les wrappers services/WebSocket les traduisent.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from .api import ScheduleValidationError, UnknownTargetError, encode_consigne
from .api import schedule as sch
from .api.client import CloudError
from .api.const import SETPOINT_MAX, SETPOINT_MIN
from .const import DATA_COORDINATOR, DATA_JOBS
from .writejob import (
    HEAD_APPLIED,
    HEAD_MISMATCH,
    HEAD_UNREACHABLE,
    HEAD_UNVERIFIED,
    JobManager,
    WriteJob,
)

if TYPE_CHECKING:
    from .coordinator import DanfossCoordinator

_LOGGER = logging.getLogger(__name__)

VERIFY_DELAY = 300  # vérification différée de 5 min (R7) ; ne bloque jamais l'appel

# DP publiés pour la consigne de pièce (contrat §4.2) : confort = 118 ; réduit = 109 ET 119.
_SETPOINT_DPS = {"comfort": ("118",), "setback": ("109", "119")}


class OperationError(Exception):
    """Erreur portant un code stable du contrat (§5.4), traduite par les wrappers."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        errors: list[dict] | None = None,
        day: str | None = None,
    ) -> None:
        self.code = code
        self.errors = errors
        self.day = day
        super().__init__(message or code)


async def ensure_admin(hass: HomeAssistant, user_id: str | None) -> None:
    """Refuse un utilisateur non administrateur (contrat §5.2). None = appel interne, autorisé."""
    if user_id is None:
        return
    user = await hass.auth.async_get_user(user_id)
    if user is None or not user.is_admin:
        raise OperationError("not_admin", "écriture réservée aux administrateurs")


def rooms_payload(store: dict) -> dict:
    return {"rooms": store[DATA_COORDINATOR].rooms}


def validate_payload(days: dict) -> dict:
    errors = sch.validate_days(days)
    return {
        "valid": not errors,
        "errors": errors,
        "transitions": sch.transitions_per_day(days),
    }


async def get_schedule(store: dict, target: dict, refresh: bool = False) -> dict:
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    try:
        return await coordinator.async_get_schedule(target, refresh)
    except UnknownTargetError as err:
        raise OperationError("unknown_target", str(err)) from err
    except CloudError as err:
        raise OperationError("cloud_refused", str(err)) from err


def _head_ids(coordinator: DanfossCoordinator, target: dict) -> list[str]:
    if target.get("type") == "room":
        room = coordinator.rooms_by_id.get(str(target.get("id")))
        return [h["device_id"] for h in room["heads"]] if room else []
    return [str(target.get("id"))]


def _check_not_grouped(coordinator: DanfossCoordinator, target: dict) -> None:
    """Une tête groupée visée directement est refusée : viser sa pièce (contrat §5.4)."""
    if target.get("type") != "device":
        return
    dev_id = str(target.get("id"))
    for room in coordinator.rooms:
        if any(h["device_id"] == dev_id for h in room["heads"]):
            raise OperationError("grouped_device", "tête groupée : viser sa pièce")


async def set_schedule(hass: HomeAssistant, store: dict, target: dict, days: dict) -> dict:
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    jobs: JobManager = store[DATA_JOBS]
    _check_not_grouped(coordinator, target)
    errors = sch.validate_days(days)
    if errors:
        raise OperationError(errors[0]["code"], errors[0]["message"], errors, errors[0].get("day"))
    await _run_write(coordinator.client.async_set_schedule_days, target, days)
    coordinator.invalidate_schedule(target)
    job = jobs.create("set_schedule", target, _head_ids(coordinator, target))
    _defer_verification(hass, store, job)
    return job.to_dict()


async def restore_schedule(hass: HomeAssistant, store: dict, target: dict) -> dict:
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    jobs: JobManager = store[DATA_JOBS]
    _check_not_grouped(coordinator, target)
    await _run_write(coordinator.client.async_restore_schedule, target)
    coordinator.invalidate_schedule(target)
    job = jobs.create("restore", target, _head_ids(coordinator, target))
    _defer_verification(hass, store, job)
    return job.to_dict()


async def set_setpoint(hass: HomeAssistant, store: dict, group_id: str, kind: str, celsius) -> dict:
    """Consigne confort/réduit d'une pièce (R3), via `async_set_room_setpoint` (PR #10).

    #10 publie le DP de consigne sur le groupe PUIS réécrit un jour du programme (sinon les têtes
    gardent l'ancienne valeur dans leurs transitions). On réutilise ce chemin unique plutôt que d'en
    créer un second. `kind` : « comfort » ou « setback ».
    """
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    jobs: JobManager = store[DATA_JOBS]
    if kind not in _SETPOINT_DPS:
        raise OperationError("cloud_refused", f"consigne inconnue : {kind}")
    valeur = encode_consigne(celsius, SETPOINT_MIN, SETPOINT_MAX)
    dps = {dp: valeur for dp in _SETPOINT_DPS[kind]}
    target = {"type": "room", "id": str(group_id)}
    heads = _head_ids(coordinator, target)
    if not heads:
        raise OperationError("unknown_target", f"pièce {group_id} sans tête")
    try:
        # async_set_room_setpoint : résout le groupe, publie la consigne, reprog un jour.
        await coordinator.client.async_set_room_setpoint(heads[0], dps)
    except CloudError as err:
        raise OperationError("cloud_refused", str(err)) from err
    coordinator.invalidate_schedule(target)
    job = jobs.create("set_setpoint", target, heads)
    _defer_verification(hass, store, job)
    return job.to_dict()


async def _run_write(func, *args) -> None:
    try:
        await func(*args)
    except ScheduleValidationError as err:
        first = err.errors[0]
        raise OperationError(first["code"], first["message"], err.errors, first.get("day")) from err
    except UnknownTargetError as err:
        raise OperationError("unknown_target", str(err)) from err
    except CloudError as err:
        raise OperationError("cloud_refused", str(err)) from err


def _defer_verification(hass: HomeAssistant, store: dict, job: WriteJob) -> None:
    """Programme la vérification 5 min plus tard (R7). Ne bloque jamais l'appel."""

    async def _run(_now) -> None:
        try:
            await verify_job(store, job)
        except Exception as err:  # noqa: BLE001 - la vérification ne doit jamais remonter
            _LOGGER.debug("vérification du lot %s : %s", job.job_id, err)

    async_call_later(hass, VERIFY_DELAY, _run)


async def verify_job(store: dict, job: WriteJob) -> None:
    """Vérifie un lot : DP 172 pour le mode (R6) ; programme = `unverified`.

    La relecture locale du programme (par le tunnel) est un suivi distinct, éprouvé à la
    validation réelle des écritures : on ne prétend jamais `applied` sans l'avoir constaté.
    """
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    jobs: JobManager = store[DATA_JOBS]
    await coordinator.async_request_refresh()
    devices = coordinator.data
    for head in job.heads:
        dev = devices.get(head.device_id)
        if dev is None or not dev.en_ligne:
            jobs.set_head(job, head.device_id, HEAD_UNREACHABLE)
            continue
        if job.kind in ("restore", "set_setpoint"):
            ok = dev.schedule_active is True
            jobs.set_head(job, head.device_id, HEAD_APPLIED if ok else HEAD_MISMATCH)
        else:  # set_schedule : relecture du programme non effectuée en cloud seul
            jobs.set_head(
                job, head.device_id, HEAD_UNVERIFIED, "programme non relu (tunnel local requis)"
            )
