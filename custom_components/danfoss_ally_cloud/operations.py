"""Opérations partagées entre les actions (services) et les commandes WebSocket.

Une seule implémentation par opération (contrat §5.3) : pièces (avec états de têtes), lecture /
écriture du programme, retour au programme. S'appuie sur le modèle de pièces de la PR #12
(`coordinator.rooms` = RoomState, `coordinator.group_of`) et sur l'édition de programme de la
couche `api/` (validation R1). Les écritures créent un `WriteJob` suivi par `jobs/subscribe` et
vérifié de façon différée (jamais bloquante). Erreurs = codes stables du contrat (§5.4).

La consigne durable de pièce n'est PAS ici : elle est portée par le thermostat de pièce (PR #12,
`climate.async_set_temperature` → `async_set_group_setpoint`).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from .api import ScheduleValidationError, UnknownTargetError, etat_tete
from .api import schedule as sch
from .api.client import CloudError
from .const import DATA_COORDINATOR, DATA_JOBS, DATA_SCHEDULES
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

VERIFY_DELAY = 300  # vérification différée de 5 min (R7) ; ne bloque jamais
SCHEDULE_TTL = 3600  # cache du programme par cible (lecture à la demande)


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


def _heads_of_room(coordinator: DanfossCoordinator, group_id: str) -> list[dict]:
    return [
        etat_tete(dev, group_id)
        for dev in coordinator.data.values()
        if dev.est_tete and coordinator.group_of(dev.id) == group_id
    ]


def rooms_payload(store: dict) -> dict:
    """Pièces (contrat §3.4) : RoomState de #12 + états des têtes membres (HeadState §3.3)."""
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    rooms = [
        {
            "id": gid,
            "name": rs.nom,
            "product_id": rs.pid,
            "comfort": rs.consignes.get("confort"),
            "setback": rs.consignes.get("reduit"),
            "heads": _heads_of_room(coordinator, gid),
        }
        for gid, rs in coordinator.rooms.items()
    ]
    return {"rooms": rooms}


def validate_payload(days: dict) -> dict:
    errors = sch.validate_days(days)
    return {
        "valid": not errors,
        "errors": errors,
        "transitions": sch.transitions_per_day(days),
    }


def _key(target: dict) -> str:
    return f"{target.get('type')}:{target.get('id')}"


async def get_schedule(store: dict, target: dict, refresh: bool = False) -> dict:
    """Programme d'une cible : cache (≤ 1 h) ou cloud si `refresh` / cache périmé."""
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    cache: dict = store[DATA_SCHEDULES]
    key = _key(target)
    cached = cache.get(key)
    if not refresh and cached is not None and (time.monotonic() - cached[1]) < SCHEDULE_TTL:
        return cached[0]
    try:
        schedule = await coordinator.client.async_get_schedule(target)
    except UnknownTargetError as err:
        raise OperationError("unknown_target", str(err)) from err
    except CloudError as err:
        raise OperationError("cloud_refused", str(err)) from err
    cache[key] = (schedule, time.monotonic())
    return schedule


def _invalidate(store: dict, target: dict) -> None:
    store[DATA_SCHEDULES].pop(_key(target), None)


def _head_ids(store: dict, target: dict) -> list[str]:
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    if target.get("type") == "room":
        gid = str(target.get("id"))
        return [
            dev.id
            for dev in coordinator.data.values()
            if dev.est_tete and coordinator.group_of(dev.id) == gid
        ]
    return [str(target.get("id"))]


def _check_not_grouped(store: dict, target: dict) -> None:
    """Une tête groupée visée directement est refusée : viser sa pièce (contrat §5.4)."""
    coordinator: DanfossCoordinator = store[DATA_COORDINATOR]
    if target.get("type") == "device" and coordinator.group_of(str(target.get("id"))) is not None:
        raise OperationError("grouped_device", "tête groupée : viser sa pièce")


async def set_schedule(hass: HomeAssistant, store: dict, target: dict, days: dict) -> dict:
    jobs: JobManager = store[DATA_JOBS]
    _check_not_grouped(store, target)
    errors = sch.validate_days(days)
    if errors:
        raise OperationError(errors[0]["code"], errors[0]["message"], errors, errors[0].get("day"))
    await _run_write(store[DATA_COORDINATOR].client.async_set_schedule_days, target, days)
    _invalidate(store, target)
    job = jobs.create("set_schedule", target, _head_ids(store, target))
    _defer_verification(hass, store, job)
    return job.to_dict()


async def restore_schedule(hass: HomeAssistant, store: dict, target: dict) -> dict:
    jobs: JobManager = store[DATA_JOBS]
    _check_not_grouped(store, target)
    await _run_write(store[DATA_COORDINATOR].client.async_restore_schedule, target)
    _invalidate(store, target)
    job = jobs.create("restore", target, _head_ids(store, target))
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
        if job.kind == "restore":
            ok = dev.schedule_active is True
            jobs.set_head(job, head.device_id, HEAD_APPLIED if ok else HEAD_MISMATCH)
        else:  # set_schedule : relecture du programme non effectuée en cloud seul
            jobs.set_head(
                job, head.device_id, HEAD_UNVERIFIED, "programme non relu (tunnel local requis)"
            )
