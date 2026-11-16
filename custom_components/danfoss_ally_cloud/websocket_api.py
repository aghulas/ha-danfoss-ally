"""Commandes WebSocket pour l'interface embarquée (contrat §5.3).

Même implémentation que les actions (voir `operations.py`) : une seule fonction par opération.
Lecture pour tous ; écriture réservée aux administrateurs. L'interface n'appelle QUE ces commandes.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.loader import async_get_integration

from . import operations as ops
from .const import DATA_COORDINATOR, DATA_JOBS, DATA_LOCAL, DOMAIN


def _store(hass: HomeAssistant, msg: dict) -> dict | None:
    entries = {
        k: v
        for k, v in hass.data.get(DOMAIN, {}).items()
        if isinstance(v, dict) and DATA_COORDINATOR in v
    }
    entry_id = msg.get("entry_id")
    if entry_id is not None:
        return entries.get(entry_id)
    return next(iter(entries.values())) if len(entries) == 1 else None


def _send_op_error(connection, msg_id: int, err: ops.OperationError) -> None:
    connection.send_error(msg_id, err.code, str(err))


def async_register(hass: HomeAssistant) -> None:
    """Enregistre les commandes WebSocket une fois."""
    reg = websocket_api.async_register_command
    reg(hass, ws_info)
    reg(hass, ws_rooms)
    reg(hass, ws_schedule_get)
    reg(hass, ws_schedule_validate)
    reg(hass, ws_schedule_set)
    reg(hass, ws_schedule_restore)
    reg(hass, ws_jobs_subscribe)


@websocket_api.websocket_command(
    {vol.Required("type"): "danfoss_ally_cloud/info", vol.Optional("entry_id"): str}
)
@websocket_api.async_response
async def ws_info(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    integration = await async_get_integration(hass, DOMAIN)
    connection.send_result(
        msg["id"],
        {
            "version": str(integration.version),
            "local_enabled": bool(store and store.get(DATA_LOCAL) is not None),
            "is_admin": bool(connection.user.is_admin),
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "danfoss_ally_cloud/rooms", vol.Optional("entry_id"): str}
)
@callback
def ws_rooms(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "aucun compte configuré")
        return
    connection.send_result(msg["id"], ops.rooms_payload(store))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/schedule/get",
        vol.Required("target"): dict,
        vol.Optional("refresh", default=False): bool,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_schedule_get(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "aucun compte configuré")
        return
    try:
        schedule = await ops.get_schedule(store, msg["target"], msg["refresh"])
    except ops.OperationError as err:
        _send_op_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], schedule)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/schedule/validate",
        vol.Required("days"): dict,
    }
)
@callback
def ws_schedule_validate(hass: HomeAssistant, connection, msg: dict) -> None:
    connection.send_result(msg["id"], ops.validate_payload(msg["days"]))


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/schedule/set",
        vol.Required("target"): dict,
        vol.Required("days"): dict,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_schedule_set(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "aucun compte configuré")
        return
    try:
        job = await ops.set_schedule(hass, store, msg["target"], msg["days"])
    except ops.OperationError as err:
        _send_op_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], job)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/schedule/restore",
        vol.Required("target"): dict,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_schedule_restore(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "aucun compte configuré")
        return
    try:
        job = await ops.restore_schedule(hass, store, msg["target"])
    except ops.OperationError as err:
        _send_op_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], job)


@websocket_api.websocket_command(
    {vol.Required("type"): "danfoss_ally_cloud/jobs/subscribe", vol.Optional("entry_id"): str}
)
@callback
def ws_jobs_subscribe(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "aucun compte configuré")
        return
    jobs = store[DATA_JOBS]

    @callback
    def _forward(job: Any) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], job.to_dict()))

    connection.subscriptions[msg["id"]] = jobs.subscribe(_forward)
    connection.send_result(msg["id"])
