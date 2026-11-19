"""WebSocket commands for the embedded frontend (contract §5.3).

Same implementation as the actions (see `operations.py`): one function per operation. Read for all;
write reserved for administrators. The frontend calls ONLY these commands.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.loader import async_get_integration

from . import operations as ops
from .const import DATA_COORDINATOR, DATA_JOBS, DATA_LOCAL, DOMAIN


def _command(schema: dict[Any, Any]) -> Callable[[Any], Any]:
    """`websocket_command` with a voluptuous schema. Runtime-accepted by every supported HA
    (2026.x included); HA 2026 types the schema keys as probatio markers, hence Any here."""
    return websocket_api.websocket_command(schema)


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
    """Register the WebSocket commands once."""
    reg = websocket_api.async_register_command
    reg(hass, ws_info)
    reg(hass, ws_rooms)
    reg(hass, ws_room_get)
    reg(hass, ws_holiday)
    reg(hass, ws_relays)
    reg(hass, ws_overview)
    reg(hass, ws_local_survey)
    reg(hass, ws_set_descaling)
    reg(hass, ws_set_override)
    reg(hass, ws_clear_override)
    reg(hass, ws_set_window_detection)
    reg(hass, ws_schedule_get)
    reg(hass, ws_schedule_validate)
    reg(hass, ws_schedule_set)
    reg(hass, ws_schedule_restore)
    reg(hass, ws_jobs_subscribe)
    reg(hass, ws_room_create)
    reg(hass, ws_room_rename)
    reg(hass, ws_room_delete)
    reg(hass, ws_room_attach)
    reg(hass, ws_room_detach)
    reg(hass, ws_relay_set_room)
    reg(hass, ws_vacation_set)
    reg(hass, ws_vacation_set_at_home)
    reg(hass, ws_vacation_cancel)
    reg(hass, ws_vacation_end)


@_command({vol.Required("type"): "danfoss_ally_cloud/info", vol.Optional("entry_id"): str})
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


@_command({vol.Required("type"): "danfoss_ally_cloud/rooms", vol.Optional("entry_id"): str})
@callback
def ws_rooms(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "no account configured")
        return
    connection.send_result(msg["id"], ops.rooms_payload(store))


@_command({vol.Required("type"): "danfoss_ally_cloud/holiday", vol.Optional("entry_id"): str})
@callback
def ws_holiday(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "no account configured")
        return
    connection.send_result(msg["id"], ops.holidays_payload(store))


@_command({vol.Required("type"): "danfoss_ally_cloud/relays", vol.Optional("entry_id"): str})
@callback
def ws_relays(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "no account configured")
        return
    connection.send_result(msg["id"], ops.relays_payload(store))


@_command({vol.Required("type"): "danfoss_ally_cloud/overview", vol.Optional("entry_id"): str})
@callback
def ws_overview(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "no account configured")
        return
    connection.send_result(msg["id"], ops.overview_payload(store))


@_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/room/get",
        vol.Required("target"): dict,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_room_get(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "no account configured")
        return
    try:
        result = await ops.get_room(store, msg["target"])
    except ops.OperationError as err:
        _send_op_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


@_command({vol.Required("type"): "danfoss_ally_cloud/local_survey", vol.Optional("entry_id"): str})
@websocket_api.async_response
async def ws_local_survey(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "no account configured")
        return
    try:
        result = await ops.local_survey(hass, store)
    except ops.OperationError as err:
        _send_op_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/set_descaling",
        vol.Required("target"): dict,
        vol.Required("day"): str,
        vol.Required("time"): str,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_set_descaling(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "no account configured")
        return
    try:
        result = await ops.set_descaling(hass, store, msg["target"], msg["day"], msg["time"])
    except ops.OperationError as err:
        _send_op_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/set_override",
        vol.Required("target"): dict,
        vol.Required("temperature"): vol.Coerce(float),
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_set_override(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "no account configured")
        return
    try:
        result = await ops.set_override(hass, store, msg["target"], msg["temperature"])
    except ops.OperationError as err:
        _send_op_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/clear_override",
        vol.Required("target"): dict,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_clear_override(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "no account configured")
        return
    try:
        result = await ops.clear_override(hass, store, msg["target"])
    except ops.OperationError as err:
        _send_op_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/set_window_detection",
        vol.Required("target"): dict,
        vol.Required("enabled"): bool,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_set_window_detection(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "no account configured")
        return
    try:
        result = await ops.set_window_detection(hass, store, msg["target"], msg["enabled"])
    except ops.OperationError as err:
        _send_op_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


@_command(
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
        connection.send_error(msg["id"], "unknown_target", "no account configured")
        return
    try:
        schedule = await ops.get_schedule(store, msg["target"], msg["refresh"])
    except ops.OperationError as err:
        _send_op_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], schedule)


@_command(
    {vol.Required("type"): "danfoss_ally_cloud/schedule/validate", vol.Required("days"): dict}
)
@callback
def ws_schedule_validate(hass: HomeAssistant, connection, msg: dict) -> None:
    connection.send_result(msg["id"], ops.validate_payload(msg["days"]))


@websocket_api.require_admin
@_command(
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
        connection.send_error(msg["id"], "unknown_target", "no account configured")
        return
    try:
        job = await ops.set_schedule(hass, store, msg["target"], msg["days"])
    except ops.OperationError as err:
        _send_op_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], job)


@websocket_api.require_admin
@_command(
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
        connection.send_error(msg["id"], "unknown_target", "no account configured")
        return
    try:
        job = await ops.restore_schedule(hass, store, msg["target"])
    except ops.OperationError as err:
        _send_op_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], job)


def _ws_store_or_error(hass: HomeAssistant, connection, msg: dict) -> dict | None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "no account configured")
        return None
    return store


async def _ws_room_write(hass, connection, msg, func, *args) -> None:
    store = _ws_store_or_error(hass, connection, msg)
    if store is None:
        return
    try:
        result = await func(hass, store, *args)
    except ops.OperationError as err:
        _send_op_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/room/create",
        vol.Required("name"): str,
        vol.Required("devices"): [str],
        vol.Optional("home"): str,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_room_create(hass: HomeAssistant, connection, msg: dict) -> None:
    await _ws_room_write(
        hass, connection, msg, ops.create_room, msg["name"], msg["devices"], msg.get("home")
    )


@websocket_api.require_admin
@_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/room/rename",
        vol.Required("target"): dict,
        vol.Required("name"): str,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_room_rename(hass: HomeAssistant, connection, msg: dict) -> None:
    await _ws_room_write(hass, connection, msg, ops.rename_room, msg["target"], msg["name"])


@websocket_api.require_admin
@_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/room/delete",
        vol.Required("target"): dict,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_room_delete(hass: HomeAssistant, connection, msg: dict) -> None:
    await _ws_room_write(hass, connection, msg, ops.delete_room, msg["target"])


@websocket_api.require_admin
@_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/room/attach",
        vol.Required("target"): dict,
        vol.Required("devices"): [str],
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_room_attach(hass: HomeAssistant, connection, msg: dict) -> None:
    await _ws_room_write(hass, connection, msg, ops.attach_heads, msg["target"], msg["devices"])


@websocket_api.require_admin
@_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/room/detach",
        vol.Required("target"): dict,
        vol.Required("devices"): [str],
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_room_detach(hass: HomeAssistant, connection, msg: dict) -> None:
    await _ws_room_write(hass, connection, msg, ops.detach_heads, msg["target"], msg["devices"])


@websocket_api.require_admin
@_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/relay/set_room",
        vol.Required("relay"): str,
        vol.Required("target"): dict,
        vol.Required("linked"): bool,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_relay_set_room(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _ws_store_or_error(hass, connection, msg)
    if store is None:
        return
    try:
        result = await ops.set_relay_room(hass, store, msg["relay"], msg["target"], msg["linked"])
    except ops.OperationError as err:
        _send_op_error(connection, msg["id"], err)
        return
    connection.send_result(msg["id"], result)


# --- Vacation (holiday) writes (GATED). Admin-only; the opt-in gate is enforced in operations. ---


@websocket_api.require_admin
@_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/vacation/set",
        vol.Required("home"): str,
        vol.Required("start_date"): str,
        vol.Required("start_time"): str,
        vol.Required("end_date"): str,
        vol.Required("end_time"): str,
        vol.Required("temperature"): vol.Coerce(float),
        vol.Optional("rooms"): [dict],
        vol.Optional("time_zone", default="Europe/Paris"): str,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_vacation_set(hass: HomeAssistant, connection, msg: dict) -> None:
    await _ws_room_write(
        hass,
        connection,
        msg,
        ops.set_vacation,
        msg["home"],
        msg["start_date"],
        msg["start_time"],
        msg["end_date"],
        msg["end_time"],
        msg["temperature"],
        msg.get("rooms"),
        msg["time_zone"],
    )


@websocket_api.require_admin
@_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/vacation/set_at_home",
        vol.Required("home"): str,
        vol.Required("start_date"): str,
        vol.Required("end_date"): str,
        vol.Optional("rooms"): [dict],
        vol.Optional("time_zone", default="Europe/Paris"): str,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_vacation_set_at_home(hass: HomeAssistant, connection, msg: dict) -> None:
    await _ws_room_write(
        hass,
        connection,
        msg,
        ops.set_vacation_at_home,
        msg["home"],
        msg["start_date"],
        msg["end_date"],
        msg.get("rooms"),
        msg["time_zone"],
    )


@websocket_api.require_admin
@_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/vacation/cancel",
        vol.Required("home"): str,
        vol.Optional("time_zone", default="Europe/Paris"): str,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_vacation_cancel(hass: HomeAssistant, connection, msg: dict) -> None:
    await _ws_room_write(hass, connection, msg, ops.cancel_vacation, msg["home"], msg["time_zone"])


@websocket_api.require_admin
@_command(
    {
        vol.Required("type"): "danfoss_ally_cloud/vacation/end",
        vol.Required("home"): str,
        vol.Required("temperature"): vol.Coerce(float),
        vol.Optional("rooms"): [dict],
        vol.Optional("time_zone", default="Europe/Paris"): str,
        vol.Optional("entry_id"): str,
    }
)
@websocket_api.async_response
async def ws_vacation_end(hass: HomeAssistant, connection, msg: dict) -> None:
    await _ws_room_write(
        hass,
        connection,
        msg,
        ops.end_vacation,
        msg["home"],
        msg["temperature"],
        msg.get("rooms"),
        msg["time_zone"],
    )


@_command(
    {vol.Required("type"): "danfoss_ally_cloud/jobs/subscribe", vol.Optional("entry_id"): str}
)
@callback
def ws_jobs_subscribe(hass: HomeAssistant, connection, msg: dict) -> None:
    store = _store(hass, msg)
    if store is None:
        connection.send_error(msg["id"], "unknown_target", "no account configured")
        return
    jobs = store[DATA_JOBS]

    @callback
    def _forward(job: Any) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], job.to_dict()))

    connection.subscriptions[msg["id"]] = jobs.subscribe(_forward)
    connection.send_result(msg["id"])
