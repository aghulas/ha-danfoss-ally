"""Actions (services) of the danfoss_ally_cloud domain (contract §5.2).

Same implementation as the WebSocket commands (see `operations.py`). Writes refuse a non-admin user
and return a `WriteJob`. Contract errors (§5.4) are raised as translated `ServiceValidationError`
(key = stable code).
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
_SET_DESCALING = vol.Schema(
    {
        vol.Required("target"): _TARGET,
        vol.Required("day"): cv.string,
        vol.Required("time"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)
_SET_OVERRIDE = vol.Schema(
    {
        vol.Required("target"): _TARGET,
        vol.Required("temperature"): vol.Coerce(float),
        vol.Optional("config_entry_id"): cv.string,
    }
)
_SET_WINDOW = vol.Schema(
    {
        vol.Required("target"): _TARGET,
        vol.Required("enabled"): cv.boolean,
        vol.Optional("config_entry_id"): cv.string,
    }
)
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
_CREATE_ROOM = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("devices"): [cv.string],
        vol.Optional("config_entry_id"): cv.string,
    }
)
_RENAME_ROOM = vol.Schema(
    {
        vol.Required("target"): _TARGET,
        vol.Required("name"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)
_SET_RELAY_ROOM = vol.Schema(
    {
        vol.Required("relay"): cv.string,
        vol.Required("target"): _TARGET,
        vol.Required("linked"): cv.boolean,
        vol.Optional("config_entry_id"): cv.string,
    }
)


def _store(hass: HomeAssistant, call: ServiceCall) -> dict:
    """Store of the targeted entry (config_entry_id, or the single configured entry)."""
    entries = {
        k: v
        for k, v in hass.data.get(DOMAIN, {}).items()
        if isinstance(v, dict) and DATA_COORDINATOR in v
    }
    entry_id = call.data.get("config_entry_id")
    if entry_id is not None:
        store = entries.get(entry_id)
        if store is None:
            raise ServiceValidationError(f"unknown entry: {entry_id}")
        return store
    if len(entries) != 1:
        raise ServiceValidationError("several accounts configured: specify config_entry_id")
    return next(iter(entries.values()))


def _raise(err: ops.OperationError) -> NoReturn:
    raise ServiceValidationError(
        str(err), translation_domain=DOMAIN, translation_key=err.code
    ) from err


def async_register_services(hass: HomeAssistant) -> None:
    """Register the actions once for the domain (idempotent)."""
    if hass.services.has_service(DOMAIN, "get_rooms"):
        return

    async def get_rooms(call: ServiceCall) -> dict:
        return ops.rooms_payload(_store(hass, call))

    async def get_room(call: ServiceCall) -> dict:
        try:
            return await ops.get_room(_store(hass, call), call.data["target"])
        except ops.OperationError as err:
            _raise(err)

    async def get_holiday(call: ServiceCall) -> dict:
        return ops.holidays_payload(_store(hass, call))

    async def get_relays(call: ServiceCall) -> dict:
        return ops.relays_payload(_store(hass, call))

    async def get_overview(call: ServiceCall) -> dict:
        return ops.overview_payload(_store(hass, call))

    async def get_local_survey(call: ServiceCall) -> dict:
        try:
            return await ops.local_survey(hass, _store(hass, call))
        except ops.OperationError as err:
            _raise(err)

    async def set_descaling(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.set_descaling(
                hass, store, call.data["target"], call.data["day"], call.data["time"]
            )
        except ops.OperationError as err:
            _raise(err)

    async def set_override(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.set_override(
                hass, store, call.data["target"], call.data["temperature"]
            )
        except ops.OperationError as err:
            _raise(err)

    async def clear_override(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.clear_override(hass, store, call.data["target"])
        except ops.OperationError as err:
            _raise(err)

    async def set_window_detection(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.set_window_detection(
                hass, store, call.data["target"], call.data["enabled"]
            )
        except ops.OperationError as err:
            _raise(err)

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
            raise ServiceValidationError(f"unknown job: {call.data['job_id']}")
        return job.to_dict()

    async def create_room(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.create_room(hass, store, call.data["name"], call.data["devices"])
        except ops.OperationError as err:
            _raise(err)

    async def rename_room(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.rename_room(hass, store, call.data["target"], call.data["name"])
        except ops.OperationError as err:
            _raise(err)

    async def delete_room(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.delete_room(hass, store, call.data["target"])
        except ops.OperationError as err:
            _raise(err)

    async def set_relay_room(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.set_relay_room(
                hass, store, call.data["relay"], call.data["target"], call.data["linked"]
            )
        except ops.OperationError as err:
            _raise(err)

    reg = hass.services.async_register
    reg(DOMAIN, "get_rooms", get_rooms, _GET_ROOMS, SupportsResponse.ONLY)
    reg(DOMAIN, "get_room", get_room, _RESTORE, SupportsResponse.ONLY)
    reg(DOMAIN, "get_holiday", get_holiday, _GET_ROOMS, SupportsResponse.ONLY)
    reg(DOMAIN, "get_relays", get_relays, _GET_ROOMS, SupportsResponse.ONLY)
    reg(DOMAIN, "get_overview", get_overview, _GET_ROOMS, SupportsResponse.ONLY)
    reg(DOMAIN, "get_local_survey", get_local_survey, _GET_ROOMS, SupportsResponse.ONLY)
    reg(DOMAIN, "set_descaling", set_descaling, _SET_DESCALING, SupportsResponse.OPTIONAL)
    reg(DOMAIN, "set_override", set_override, _SET_OVERRIDE, SupportsResponse.OPTIONAL)
    reg(DOMAIN, "clear_override", clear_override, _RESTORE, SupportsResponse.OPTIONAL)
    reg(
        DOMAIN, "set_window_detection", set_window_detection, _SET_WINDOW, SupportsResponse.OPTIONAL
    )
    reg(DOMAIN, "get_schedule", get_schedule, _GET_SCHEDULE, SupportsResponse.ONLY)
    reg(DOMAIN, "set_schedule", set_schedule, _SET_SCHEDULE, SupportsResponse.OPTIONAL)
    reg(DOMAIN, "copy_schedule", copy_schedule, _COPY_SCHEDULE, SupportsResponse.OPTIONAL)
    reg(DOMAIN, "restore_schedule", restore_schedule, _RESTORE, SupportsResponse.OPTIONAL)
    reg(DOMAIN, "get_write_job", get_write_job, _GET_JOB, SupportsResponse.ONLY)
    reg(DOMAIN, "create_room", create_room, _CREATE_ROOM, SupportsResponse.OPTIONAL)
    reg(DOMAIN, "rename_room", rename_room, _RENAME_ROOM, SupportsResponse.OPTIONAL)
    reg(DOMAIN, "delete_room", delete_room, _RESTORE, SupportsResponse.OPTIONAL)
    reg(DOMAIN, "set_relay_room", set_relay_room, _SET_RELAY_ROOM, SupportsResponse.OPTIONAL)
