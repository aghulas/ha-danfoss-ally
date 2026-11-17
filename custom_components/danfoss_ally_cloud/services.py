"""Actions (services) du domaine danfoss_ally_cloud (contrat §5.2).

Même implémentation que les commandes WebSocket (voir `operations.py`). Les écritures refusent un
utilisateur non administrateur et renvoient un `WriteJob`. Les erreurs du contrat (§5.4) sont
remontées en `ServiceValidationError` traduites (clé = code stable).
"""

from __future__ import annotations

from typing import NoReturn

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from . import operations as ops
from .const import DATA_COORDINATOR, DATA_JOBS, DOMAIN

_RANGE = vol.Schema({vol.Required("start"): cv.string, vol.Required("end"): cv.string})
_DAYS = vol.Schema({cv.string: [_RANGE]})
_TARGET = vol.Schema(
    {vol.Required("type"): vol.In(["room", "device"]), vol.Required("id"): cv.string}
)

_GET_ROOMS = vol.Schema({vol.Optional("config_entry_id"): cv.string})
_GET_SCHEDULE = vol.Schema(
    {
        vol.Required("target"): _TARGET,
        vol.Optional("refresh", default=False): cv.boolean,
        vol.Optional("config_entry_id"): cv.string,
    }
)
_SET_SCHEDULE = vol.Schema(
    {
        vol.Required("target"): _TARGET,
        vol.Required("days"): _DAYS,
        vol.Optional("config_entry_id"): cv.string,
    }
)
_COPY_SCHEDULE = vol.Schema(
    {
        vol.Required("source"): _TARGET,
        vol.Required("targets"): [_TARGET],
        vol.Optional("days"): [cv.string],
        vol.Optional("config_entry_id"): cv.string,
    }
)
_RESTORE = vol.Schema({vol.Required("target"): _TARGET, vol.Optional("config_entry_id"): cv.string})
_GET_JOB = vol.Schema(
    {vol.Required("job_id"): cv.string, vol.Optional("config_entry_id"): cv.string}
)


def _store(hass: HomeAssistant, call: ServiceCall) -> dict:
    """Store de l'entrée visée (config_entry_id, ou l'unique entrée configurée)."""
    entries = {
        k: v
        for k, v in hass.data.get(DOMAIN, {}).items()
        if isinstance(v, dict) and DATA_COORDINATOR in v
    }
    entry_id = call.data.get("config_entry_id")
    if entry_id is not None:
        store = entries.get(entry_id)
        if store is None:
            raise ServiceValidationError(f"entrée inconnue : {entry_id}")
        return store
    if len(entries) != 1:
        raise ServiceValidationError("plusieurs comptes configurés : préciser config_entry_id")
    return next(iter(entries.values()))


def _raise(err: ops.OperationError) -> NoReturn:
    raise ServiceValidationError(
        str(err), translation_domain=DOMAIN, translation_key=err.code
    ) from err


def async_register_services(hass: HomeAssistant) -> None:
    """Enregistre les actions une fois pour le domaine (idempotent)."""
    if hass.services.has_service(DOMAIN, "get_rooms"):
        return

    async def get_rooms(call: ServiceCall) -> dict:
        return ops.rooms_payload(_store(hass, call))

    async def get_schedule(call: ServiceCall) -> dict:
        try:
            return await ops.get_schedule(
                _store(hass, call), call.data["target"], call.data["refresh"]
            )
        except ops.OperationError as err:
            _raise(err)

    async def set_schedule(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.set_schedule(hass, store, call.data["target"], call.data["days"])
        except ops.OperationError as err:
            _raise(err)

    async def copy_schedule(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            src = await ops.get_schedule(store, call.data["source"])
            only = call.data.get("days")
            days = {d: r for d, r in src["days"].items() if only is None or d in only}
            jobs = [await ops.set_schedule(hass, store, t, days) for t in call.data["targets"]]
            return {"jobs": jobs}
        except ops.OperationError as err:
            _raise(err)

    async def restore_schedule(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.restore_schedule(hass, store, call.data["target"])
        except ops.OperationError as err:
            _raise(err)

    async def get_write_job(call: ServiceCall) -> dict:
        job = _store(hass, call)[DATA_JOBS].get(call.data["job_id"])
        if job is None:
            raise ServiceValidationError(f"lot inconnu : {call.data['job_id']}")
        return job.to_dict()

    reg = hass.services.async_register
    reg(DOMAIN, "get_rooms", get_rooms, _GET_ROOMS, SupportsResponse.ONLY)
    reg(DOMAIN, "get_schedule", get_schedule, _GET_SCHEDULE, SupportsResponse.ONLY)
    reg(DOMAIN, "set_schedule", set_schedule, _SET_SCHEDULE, SupportsResponse.OPTIONAL)
    reg(DOMAIN, "copy_schedule", copy_schedule, _COPY_SCHEDULE, SupportsResponse.OPTIONAL)
    reg(DOMAIN, "restore_schedule", restore_schedule, _RESTORE, SupportsResponse.OPTIONAL)
    reg(DOMAIN, "get_write_job", get_write_job, _GET_JOB, SupportsResponse.ONLY)
