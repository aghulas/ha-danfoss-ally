"""Actions (services) of the danfoss_ally_cloud domain (contract §5.2).

Same implementation as the WebSocket commands (see `operations.py`). Writes refuse a non-admin user
and return a `WriteJob`. Contract errors (§5.4) are raised as translated `ServiceValidationError`
(key = stable code).
"""

from __future__ import annotations

from typing import Any, NoReturn

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
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
        vol.Optional("home"): cv.string,
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
_ATTACH = vol.Schema(
    {
        vol.Required("target"): _TARGET,
        vol.Required("devices"): [cv.string],
        vol.Optional("config_entry_id"): cv.string,
    }
)
# Head unbind ("disconnect"): DESTRUCTIVE. Triple-gated (opt-in option + verified product +
# explicit confirm, admin by the handler). ``wipe_data`` = resetFactory (True loses the identity).
_DISCONNECT_HEAD = vol.Schema(
    {
        vol.Required("target"): _TARGET,
        vol.Optional("wipe_data", default=False): cv.boolean,
        # Required (no default): a destructive action must carry confirm explicitly, aligned with
        # services.yaml. The `confirmation_required` op guard stays as a net for confirm=false.
        vol.Required("confirm"): cv.boolean,
        vol.Optional("config_entry_id"): cv.string,
    }
)
# Vacation (holiday) writes (GATED). A vacation is set per HOME (gid), optionally scoped to a list
# of room targets (default: every room of the home).
_SET_VACATION = vol.Schema(
    {
        vol.Required("home"): cv.string,
        vol.Required("start_date"): cv.string,
        vol.Required("start_time"): cv.string,
        vol.Required("end_date"): cv.string,
        vol.Required("end_time"): cv.string,
        vol.Required("temperature"): vol.Coerce(float),
        vol.Optional("rooms"): [_TARGET],
        vol.Optional("time_zone", default="Europe/Paris"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)
_SET_VACATION_ATHOME = vol.Schema(
    {
        vol.Required("home"): cv.string,
        vol.Required("start_date"): cv.string,
        vol.Required("end_date"): cv.string,
        vol.Optional("rooms"): [_TARGET],
        vol.Optional("time_zone", default="Europe/Paris"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)
_CANCEL_VACATION = vol.Schema(
    {
        vol.Required("home"): cv.string,
        vol.Optional("time_zone", default="Europe/Paris"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)
_END_VACATION = vol.Schema(
    {
        vol.Required("home"): cv.string,
        vol.Required("temperature"): vol.Coerce(float),
        vol.Optional("rooms"): [_TARGET],
        vol.Optional("time_zone", default="Europe/Paris"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)
_COMPANION_SET_ROOM = vol.Schema(
    {
        vol.Required("room_id"): cv.string,
        vol.Required("name"): cv.string,
        vol.Required("head_ids"): [cv.string],
        vol.Optional("sensor_id"): vol.Any(None, cv.string),
        vol.Optional("home_id"): vol.Any(None, cv.string),
        vol.Optional("comfort_setpoint", default=21.0): vol.Coerce(float),
        vol.Optional("setback_setpoint", default=17.0): vol.Coerce(float),
        vol.Optional("config_entry_id"): cv.string,
    }
)
_COMPANION_DELETE_ROOM = vol.Schema(
    {
        vol.Required("room_id"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)
_COMPANION_SYNC_ROOMS = vol.Schema({vol.Optional("config_entry_id"): cv.string})
_COMPANION_SET_COMFORT_SETBACK = vol.Schema(
    {
        vol.Required("room_id"): cv.string,
        vol.Optional("comfort"): vol.Coerce(float),
        vol.Optional("setback"): vol.Coerce(float),
        vol.Optional("pause"): vol.Coerce(float),
        vol.Optional("config_entry_id"): cv.string,
    }
)
_COMPANION_SET_ROOM_SETTINGS = vol.Schema(
    {
        vol.Required("room_id"): cv.string,
        vol.Optional("preheat"): cv.boolean,
        vol.Optional("child_lock"): cv.boolean,
        vol.Optional("window_detection"): cv.boolean,
        vol.Optional("min_setpoint"): vol.Coerce(float),
        vol.Optional("max_setpoint"): vol.Coerce(float),
        vol.Optional("config_entry_id"): cv.string,
    }
)
_COMPANION_SET_ROOM_MODE = vol.Schema(
    {
        vol.Required("room_id"): cv.string,
        vol.Required("mode"): vol.In(["schedule", "manual", "pause"]),
        vol.Optional("setpoint"): vol.Coerce(float),
        vol.Optional("config_entry_id"): cv.string,
    }
)
_COMPANION_SET_HOLIDAY = vol.Schema(
    {
        vol.Required("start"): cv.string,
        vol.Required("end"): cv.string,
        vol.Required("temperature"): vol.Coerce(float),
        vol.Required("room_ids"): [cv.string],
        vol.Optional("name", default="Holiday"): cv.string,
        vol.Optional("holiday_id"): cv.string,
        vol.Optional("prefix"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)
_COMPANION_CANCEL_HOLIDAY = vol.Schema(
    {
        vol.Required("holiday_id"): cv.string,
        vol.Optional("prefix"): cv.string,
        vol.Optional("config_entry_id"): cv.string,
    }
)


def _companion_store(hass: HomeAssistant, call: ServiceCall) -> tuple[str, dict]:
    """Return ``(entry_id, store)`` for the targeted MQTT Companion entry."""
    entries = {
        k: v
        for k, v in hass.data.get(DOMAIN, {}).items()
        if isinstance(v, dict) and "room_manager" in v
    }
    entry_id = call.data.get("config_entry_id")
    if entry_id:
        if entry_id not in entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_found"
            )
        return entry_id, entries[entry_id]
    if len(entries) == 1:
        eid, store = next(iter(entries.items()))
        return eid, store
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="entry_not_found" if not entries else "ambiguous_entry",
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
    # One account = one config entry (several homes live under it). config_entry_id is only needed
    # to disambiguate several CONFIG ENTRIES, not several homes.
    if not entries:
        raise ServiceValidationError("no danfoss_ally_cloud account configured")
    if len(entries) > 1:
        raise ServiceValidationError("several config entries configured: specify config_entry_id")
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
            targets = call.data["targets"]
            for t in targets:  # every target is checked before the first one is written
                await ops.check_schedule_target(hass, store, t)
            jobs = [await ops.set_schedule(hass, store, t, days, checked=True) for t in targets]
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
            return await ops.create_room(
                hass, store, call.data["name"], call.data["devices"], call.data.get("home")
            )
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

    async def attach_heads(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.attach_heads(hass, store, call.data["target"], call.data["devices"])
        except ops.OperationError as err:
            _raise(err)

    async def detach_heads(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.detach_heads(hass, store, call.data["target"], call.data["devices"])
        except ops.OperationError as err:
            _raise(err)

    async def disconnect_head(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            # Most destructive write: require a real administrator in context, refusing even a
            # user-less internal/automation call (allow_internal=False).
            await ops.ensure_admin(hass, call.context.user_id, allow_internal=False)
            return await ops.disconnect_head(
                hass,
                store,
                call.data["target"],
                call.data["wipe_data"],
                call.data["confirm"],
            )
        except ops.OperationError as err:
            _raise(err)

    async def set_vacation(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.set_vacation(
                hass,
                store,
                call.data["home"],
                call.data["start_date"],
                call.data["start_time"],
                call.data["end_date"],
                call.data["end_time"],
                call.data["temperature"],
                call.data.get("rooms"),
                call.data["time_zone"],
            )
        except ops.OperationError as err:
            _raise(err)

    async def set_vacation_at_home(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.set_vacation_at_home(
                hass,
                store,
                call.data["home"],
                call.data["start_date"],
                call.data["end_date"],
                call.data.get("rooms"),
                call.data["time_zone"],
            )
        except ops.OperationError as err:
            _raise(err)

    async def cancel_vacation(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.cancel_vacation(hass, store, call.data["home"], call.data["time_zone"])
        except ops.OperationError as err:
            _raise(err)

    async def end_vacation(call: ServiceCall) -> dict:
        store = _store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
            return await ops.end_vacation(
                hass,
                store,
                call.data["home"],
                call.data["temperature"],
                call.data.get("rooms"),
                call.data["time_zone"],
            )
        except ops.OperationError as err:
            _raise(err)

    def reg(
        domain: str, service: str, handler: Any, schema: Any, response: SupportsResponse
    ) -> None:
        # Schemas stay voluptuous (runtime-accepted by every supported HA, incl. 2026.x); HA
        # 2026 types them as probatio, so they cross into HA as Any at this single point.
        hass.services.async_register(domain, service, handler, schema, response)

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
    reg(DOMAIN, "attach_heads", attach_heads, _ATTACH, SupportsResponse.OPTIONAL)
    reg(DOMAIN, "detach_heads", detach_heads, _ATTACH, SupportsResponse.OPTIONAL)
    reg(DOMAIN, "disconnect_head", disconnect_head, _DISCONNECT_HEAD, SupportsResponse.OPTIONAL)
    reg(DOMAIN, "set_vacation", set_vacation, _SET_VACATION, SupportsResponse.OPTIONAL)
    reg(
        DOMAIN,
        "set_vacation_at_home",
        set_vacation_at_home,
        _SET_VACATION_ATHOME,
        SupportsResponse.OPTIONAL,
    )
    reg(DOMAIN, "cancel_vacation", cancel_vacation, _CANCEL_VACATION, SupportsResponse.OPTIONAL)

    async def companion_set_room(call: ServiceCall) -> dict:
        from .companion_rooms import CompanionRoomConfig

        entry_id, store = _companion_store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
        except ops.OperationError as err:
            _raise(err)
        mgr = store["room_manager"]
        cfg = CompanionRoomConfig(
            room_id=call.data["room_id"],
            name=call.data["name"],
            head_ids=list(call.data["head_ids"]),
            sensor_id=call.data.get("sensor_id") or None,
            home_id=call.data.get("home_id") or None,
            comfort_setpoint=float(call.data.get("comfort_setpoint", 21.0)),
            setback_setpoint=float(call.data.get("setback_setpoint", 17.0)),
        )
        mgr.add_virtual_room(cfg)
        await mgr.async_save(hass, entry_id)
        store["companion"]._notify_listeners()
        await mgr.async_sync_telemetry()
        return {
            "room_id": cfg.room_id,
            "name": cfg.name,
            "head_ids": list(cfg.head_ids),
            "sensor_id": cfg.sensor_id,
        }

    async def companion_delete_room(call: ServiceCall) -> dict:
        entry_id, store = _companion_store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
        except ops.OperationError as err:
            _raise(err)
        mgr = store["room_manager"]
        removed = call.data["room_id"] in mgr.virtual_rooms
        mgr.remove_virtual_room(call.data["room_id"])
        await mgr.async_save(hass, entry_id)
        store["companion"]._notify_listeners()
        return {"room_id": call.data["room_id"], "removed": removed}

    async def companion_sync_rooms(call: ServiceCall) -> dict:
        _entry_id, store = _companion_store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
        except ops.OperationError as err:
            _raise(err)
        mgr = store["room_manager"]
        await mgr.async_sync_telemetry()
        return {"synced": len(mgr.virtual_rooms)}

    reg(DOMAIN, "end_vacation", end_vacation, _END_VACATION, SupportsResponse.OPTIONAL)
    reg(
        DOMAIN,
        "companion_set_room",
        companion_set_room,
        _COMPANION_SET_ROOM,
        SupportsResponse.OPTIONAL,
    )
    reg(
        DOMAIN,
        "companion_delete_room",
        companion_delete_room,
        _COMPANION_DELETE_ROOM,
        SupportsResponse.OPTIONAL,
    )

    async def _coordinator_rpc(
        call: ServiceCall,
        action: str,
        payload: dict[str, Any],
        *,
        room_id: str | None = None,
        prefix_arg: str | None = None,
    ) -> dict[str, Any]:
        from .mqtt_companion import CompanionBridgeError

        _entry_id, store = _companion_store(hass, call)
        try:
            await ops.ensure_admin(hass, call.context.user_id)
        except ops.OperationError as err:
            _raise(err)
        comp = store["companion"]
        if room_id is not None:
            if not comp.is_coordinator_room(room_id):
                raise HomeAssistantError(f"room {room_id} is not managed by a room coordinator")
            prefix = comp.prefix_of_room(room_id)
        elif prefix_arg is not None:
            prefix = prefix_arg
        else:
            room_ids = payload.get("room_ids")
            candidates: list[str] = []
            if isinstance(room_ids, list) and room_ids:
                first_prefix = comp.prefix_of_room(str(room_ids[0]))
                if first_prefix is not None:
                    candidates = [first_prefix]
            if not candidates:
                candidates = sorted(
                    {
                        p
                        for p in comp.prefixes
                        if any(
                            comp.prefix_of_room(gid) == p and comp.is_coordinator_room(gid)
                            for gid in comp.native_rooms
                        )
                        or p in comp.heat_demand_by_prefix
                    }
                )
            if len(candidates) != 1:
                raise HomeAssistantError(
                    "specify prefix when zero or multiple room coordinators exist"
                )
            prefix = candidates[0]
        if prefix is None:
            raise HomeAssistantError("coordinator bridge prefix not found")
        try:
            return await comp.async_bridge_request(prefix, action, payload)
        except CompanionBridgeError as err:
            raise HomeAssistantError(str(err)) from err

    async def companion_set_room_comfort_setback(call: ServiceCall) -> dict[str, Any]:
        payload: dict[str, Any] = {"room_id": call.data["room_id"]}
        for k in ("comfort", "setback", "pause"):
            if k in call.data:
                payload[k] = float(call.data[k])
        return await _coordinator_rpc(
            call, "room/set-comfort-setback", payload, room_id=call.data["room_id"]
        )

    async def companion_set_room_settings(call: ServiceCall) -> dict[str, Any]:
        payload: dict[str, Any] = {"room_id": call.data["room_id"]}
        for k in ("preheat", "child_lock", "window_detection"):
            if k in call.data:
                payload[k] = bool(call.data[k])
        for k in ("min_setpoint", "max_setpoint"):
            if k in call.data:
                payload[k] = float(call.data[k])
        return await _coordinator_rpc(
            call, "room/set-settings", payload, room_id=call.data["room_id"]
        )

    async def companion_set_room_mode(call: ServiceCall) -> dict[str, Any]:
        payload: dict[str, Any] = {"room_id": call.data["room_id"], "mode": call.data["mode"]}
        if "setpoint" in call.data:
            payload["setpoint"] = float(call.data["setpoint"])
        return await _coordinator_rpc(call, "room/set-mode", payload, room_id=call.data["room_id"])

    async def companion_set_holiday(call: ServiceCall) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "start": call.data["start"],
            "end": call.data["end"],
            "temperature": float(call.data["temperature"]),
            "room_ids": list(call.data["room_ids"]),
            "name": call.data.get("name", "Holiday"),
        }
        if "holiday_id" in call.data:
            payload["holiday_id"] = call.data["holiday_id"]
        return await _coordinator_rpc(
            call, "holiday/set", payload, prefix_arg=call.data.get("prefix")
        )

    async def companion_cancel_holiday(call: ServiceCall) -> dict[str, Any]:
        return await _coordinator_rpc(
            call,
            "holiday/cancel",
            {"holiday_id": call.data["holiday_id"]},
            prefix_arg=call.data.get("prefix"),
        )

    reg(
        DOMAIN,
        "companion_sync_rooms",
        companion_sync_rooms,
        _COMPANION_SYNC_ROOMS,
        SupportsResponse.OPTIONAL,
    )
    reg(
        DOMAIN,
        "companion_set_room_comfort_setback",
        companion_set_room_comfort_setback,
        _COMPANION_SET_COMFORT_SETBACK,
        SupportsResponse.OPTIONAL,
    )
    reg(
        DOMAIN,
        "companion_set_room_settings",
        companion_set_room_settings,
        _COMPANION_SET_ROOM_SETTINGS,
        SupportsResponse.OPTIONAL,
    )
    reg(
        DOMAIN,
        "companion_set_room_mode",
        companion_set_room_mode,
        _COMPANION_SET_ROOM_MODE,
        SupportsResponse.OPTIONAL,
    )
    reg(
        DOMAIN,
        "companion_set_holiday",
        companion_set_holiday,
        _COMPANION_SET_HOLIDAY,
        SupportsResponse.OPTIONAL,
    )
    reg(
        DOMAIN,
        "companion_cancel_holiday",
        companion_cancel_holiday,
        _COMPANION_CANCEL_HOLIDAY,
        SupportsResponse.OPTIONAL,
    )
