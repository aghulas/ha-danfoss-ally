"""v2.x Companion Room, Schedule & External Sensor Orchestrator (``docs/companion-contract.md`` §3).

Unifies native Danfoss rooms (published on ``danfoss2mqtt/bridge/rooms``) and Companion-managed
virtual rooms (grouping ``zigbee2mqtt`` heads ``014G2461`` + an optional ``014G2480`` room sensor):

1. **Unified ``RoomState``**: aggregates member heads (via ``api.rooms.aggregate_room``) and
   overrides room temperature with the linked ``014G2480`` room sensor when online.
2. **External Room Sensor & Load Balancing Loop** (``async_sync_telemetry``):
   - Pushes the linked ``014G2480`` temperature to each member head's
     ``external_measured_room_sensor`` (in 0.01 °C) when temperature shifts by >= 0.2 °C or
     >= 30 min have elapsed (and sends ``-8000`` if the sensor goes offline).
   - Computes the room's mean ``pi_heating_demand`` across online member heads and pushes
     ``load_room_mean`` when it shifts by >= 5 %.
3. **Boiler Demand Aggregation** (``rooms_calling_for_heat``): lists all rooms across both
   ``zigbee2mqtt`` and ``danfoss2mqtt`` calling for heat.
4. **Setpoint & Weekly Schedule Fan-Out**: dispatches room setpoints and weekly schedules to all
   member heads on ``<prefix>/<friendly_name>/set``.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .api.rooms import Room, RoomState, aggregate_room
from .const import DOMAIN
from .mqtt_companion import MqttCompanionCoordinator

_ROOMS_STORE_VERSION = 1

EXTERNAL_SENSOR_REFRESH_SECONDS = 1800.0
EXTERNAL_SENSOR_DELTA_C = 0.2
LOAD_MEAN_DELTA_PCT = 5
EXTERNAL_SENSOR_DISABLED_RAW = -8000

_Z2M_DAY_BITS: dict[str, int] = {
    "sunday": 0x01,
    "monday": 0x02,
    "tuesday": 0x04,
    "wednesday": 0x08,
    "thursday": 0x10,
    "friday": 0x20,
    "saturday": 0x40,
}


@dataclass(slots=True)
class CompanionRoomConfig:
    """Configuration of a Companion-managed room (e.g. grouping ``zigbee2mqtt`` heads + sensor)."""

    room_id: str
    name: str
    head_ids: list[str]
    sensor_id: str | None = None
    comfort_setpoint: float = 21.0
    setback_setpoint: float = 17.0
    schedule: dict[str, list[dict[str, str]]] = field(default_factory=dict)


@dataclass(slots=True)
class _TelemetryCache:
    last_ext_temp_c: float | None = None
    last_ext_sent_at: float = 0.0
    last_load_mean: int | None = None


class CompanionRoomManager:
    """Manages unified rooms, external sensor sync, load balancing, and boiler demand."""

    def __init__(self, companion: MqttCompanionCoordinator) -> None:
        self._companion = companion
        self.virtual_rooms: dict[str, CompanionRoomConfig] = {}
        self._telemetry: dict[str, _TelemetryCache] = {}

    def add_virtual_room(self, cfg: CompanionRoomConfig) -> None:
        self.virtual_rooms[cfg.room_id] = cfg
        self._telemetry.setdefault(cfg.room_id, _TelemetryCache())

    def remove_virtual_room(self, room_id: str) -> None:
        self.virtual_rooms.pop(room_id, None)
        self._telemetry.pop(room_id, None)

    async def async_load(self, hass: HomeAssistant, entry_id: str) -> None:
        """Load persisted virtual room configs from HA storage."""
        store: Store[dict[str, Any]] = Store(
            hass, _ROOMS_STORE_VERSION, f"{DOMAIN}_companion_rooms_{entry_id}"
        )
        raw = await store.async_load()
        if not isinstance(raw, dict):
            return
        for item in raw.get("rooms", []):
            if not isinstance(item, dict) or not item.get("room_id"):
                continue
            self.add_virtual_room(
                CompanionRoomConfig(
                    room_id=str(item["room_id"]),
                    name=str(item.get("name") or item["room_id"]),
                    head_ids=[str(h) for h in item.get("head_ids", [])],
                    sensor_id=str(item["sensor_id"]) if item.get("sensor_id") else None,
                    comfort_setpoint=float(item.get("comfort_setpoint", 21.0)),
                    setback_setpoint=float(item.get("setback_setpoint", 17.0)),
                    schedule=dict(item.get("schedule") or {}),
                )
            )

    async def async_save(self, hass: HomeAssistant, entry_id: str) -> None:
        """Persist virtual room configs to HA storage."""
        store: Store[dict[str, Any]] = Store(
            hass, _ROOMS_STORE_VERSION, f"{DOMAIN}_companion_rooms_{entry_id}"
        )
        await store.async_save(
            {"rooms": [asdict(cfg) for cfg in self.virtual_rooms.values()]}
        )

    def room_members(self) -> dict[str, tuple[str, ...]]:
        """Map ``room_id -> tuple of member head_ids`` for all native and virtual rooms."""
        out: dict[str, tuple[str, ...]] = {}
        for gid, raw in self._companion.native_rooms.items():
            member_ids = tuple(str(m) for m in (raw.get("members") or ()))
            if any(m in self._companion.data for m in member_ids):
                out[gid] = member_ids
        for rid, cfg in self.virtual_rooms.items():
            member_ids = tuple(cfg.head_ids)
            if any(m in self._companion.data for m in member_ids):
                out[rid] = member_ids
        return out

    def build_rooms(self) -> dict[str, RoomState]:
        """Compute ``RoomState`` for all native ``danfoss2mqtt`` rooms and virtual rooms."""
        out: dict[str, RoomState] = {}

        # 1) Native rooms from danfoss2mqtt/bridge/rooms
        for gid, raw in self._companion.native_rooms.items():
            member_ids = tuple(str(m) for m in (raw.get("members") or ()))
            members = [
                self._companion.data[m] for m in member_ids if m in self._companion.data
            ]
            if members:
                room = Room(
                    group_id=gid,
                    name=str(raw.get("name") or gid),
                    pid=raw.get("pid"),
                    home_gid=str(raw.get("home_id") or "default"),
                    members=member_ids,
                )
                out[gid] = aggregate_room(room, members)

        # 2) Companion-managed virtual rooms (zigbee2mqtt or mixed heads + 014G2480 sensor)
        for rid, cfg in self.virtual_rooms.items():
            members = [
                self._companion.data[m] for m in cfg.head_ids if m in self._companion.data
            ]
            if not members:
                continue
            room = Room(
                group_id=rid,
                name=cfg.name,
                pid="014G2461",
                home_gid="companion",
                members=tuple(cfg.head_ids),
            )
            state = aggregate_room(room, members)
            if cfg.sensor_id and cfg.sensor_id in self._companion.data:
                sensor = self._companion.data[cfg.sensor_id]
                if sensor.online and sensor.temperature is not None:
                    state.temperature = sensor.temperature
            out[rid] = state

        return out

    def rooms_calling_for_heat(self) -> list[dict[str, Any]]:
        """List all rooms (native + virtual) currently calling for heat."""
        calling: list[dict[str, Any]] = []
        members_map = self.room_members()
        for gid, room_state in self.build_rooms().items():
            members = [
                self._companion.data[m]
                for m in members_map.get(gid, ())
                if m in self._companion.data
            ]
            demands = [
                m.valve_opening for m in members if m.valve_opening is not None
            ]
            if room_state.heating or any(m.heat_request for m in members):
                calling.append(
                    {
                        "room_id": gid,
                        "name": room_state.name,
                        "temperature": room_state.temperature,
                        "setpoint": room_state.setpoint,
                        "max_valve_opening": max(demands) if demands else None,
                    }
                )
        return calling

    async def async_set_room_setpoint(self, room_id: str, temperature_c: float) -> int:
        """Fan out a target setpoint to all member heads of ``room_id``. Returns head count."""
        members_map = self.room_members()
        member_ids = members_map.get(room_id)
        if member_ids is None:
            raise KeyError(f"Unknown room_id: {room_id}")
        sent = 0
        for head_id in member_ids:
            if head_id in self._companion.device_route:
                await self._companion.async_send_device_set(
                    head_id, setpoint=temperature_c
                )
                sent += 1
        return sent

    async def async_set_room_schedule(
        self,
        room_id: str,
        days: dict[str, list[dict[str, str]]],
        *,
        comfort_c: float | None = None,
        setback_c: float | None = None,
    ) -> int:
        """Fan out a weekly schedule (comfort windows per day) to member heads of ``room_id``."""
        cfg = self.virtual_rooms.get(room_id)
        member_ids = self.room_members().get(room_id)
        if member_ids is None:
            raise KeyError(f"Unknown room_id: {room_id}")

        comfort = comfort_c if comfort_c is not None else (cfg.comfort_setpoint if cfg else 21.0)
        setback = setback_c if setback_c is not None else (cfg.setback_setpoint if cfg else 17.0)
        if cfg is not None:
            cfg.schedule.update(days)
            cfg.comfort_setpoint = comfort
            cfg.setback_setpoint = setback

        sent = 0
        for day_name, windows in days.items():
            day_bit = _Z2M_DAY_BITS.get(day_name.strip().lower())
            if day_bit is None:
                raise ValueError(f"Invalid day name: {day_name}")
            transitions = _build_z2m_day_transitions(windows, comfort, setback)
            payload = {
                "weekly_schedule": {
                    "dayofweek": day_bit,
                    "num_of_transitions": len(transitions),
                    "mode": 1,  # heat
                    "transitions": transitions,
                }
            }
            for head_id in member_ids:
                if head_id in self._companion.device_route:
                    await self._companion.async_send_raw_device_set(head_id, payload)
                    sent += 1
        return sent

    async def async_sync_telemetry(self, *, now: float | None = None) -> dict[str, int]:
        """Push external sensor temperatures (014G2480 -> heads) and ``load_room_mean`` for
        virtual rooms. Returns ``{"external_sensor_writes": n1, "load_mean_writes": n2}``."""
        ts = time.monotonic() if now is None else now
        ext_writes = 0
        load_writes = 0

        for rid, cfg in self.virtual_rooms.items():
            cache = self._telemetry.setdefault(rid, _TelemetryCache())
            members = [
                self._companion.data[m]
                for m in cfg.head_ids
                if m in self._companion.data and self._companion.data[m].online
            ]
            if not members:
                continue

            # 1) External room sensor temperature (014G2480 -> member heads)
            if cfg.sensor_id:
                sensor = self._companion.data.get(cfg.sensor_id)
                if sensor is not None and sensor.online and sensor.temperature is not None:
                    temp = sensor.temperature
                    due = (
                        cache.last_ext_temp_c is None
                        or abs(temp - cache.last_ext_temp_c) >= EXTERNAL_SENSOR_DELTA_C
                        or (ts - cache.last_ext_sent_at) >= EXTERNAL_SENSOR_REFRESH_SECONDS
                    )
                    if due:
                        for head in members:
                            await self._companion.async_send_device_set(
                                head.id, external_sensor_temp_c=temp
                            )
                            ext_writes += 1
                        cache.last_ext_temp_c = temp
                        cache.last_ext_sent_at = ts
                elif cache.last_ext_temp_c is not None:
                    # Sensor went offline: disable external temperature (-80.0 °C = -8000)
                    for head in members:
                        await self._companion.async_send_device_set(
                            head.id,
                            external_sensor_temp_c=EXTERNAL_SENSOR_DISABLED_RAW / 100.0,
                        )
                        ext_writes += 1
                    cache.last_ext_temp_c = None
                    cache.last_ext_sent_at = ts

            # 2) Multi-head room load balancing (mean pi_heating_demand -> load_room_mean)
            if len(members) > 1:
                openings = [
                    m.valve_opening for m in members if m.valve_opening is not None
                ]
                if len(openings) == len(members):
                    mean_load = int(round(sum(openings) / len(openings)))
                    if (
                        cache.last_load_mean is None
                        or abs(mean_load - cache.last_load_mean) >= LOAD_MEAN_DELTA_PCT
                    ):
                        for head in members:
                            await self._companion.async_send_device_set(
                                head.id, load_room_mean=mean_load
                            )
                            load_writes += 1
                        cache.last_load_mean = mean_load

        return {
            "external_sensor_writes": ext_writes,
            "load_mean_writes": load_writes,
        }


def _hhmm_to_minutes(hhmm: str) -> int:
    hh, mm = (int(x) for x in hhmm.strip().split(":"))
    return hh * 60 + mm


def _build_z2m_day_transitions(
    windows: list[dict[str, str]], comfort_c: float, setback_c: float
) -> list[dict[str, float | int]]:
    """Convert comfort windows ``[{"start": "07:00", "end": "17:00"}]`` into ZCL/Z2M transitions."""
    transitions: list[dict[str, float | int]] = [
        {"transition_time": 0, "heat_setpoint": float(setback_c)}
    ]
    for w in sorted(windows, key=lambda x: _hhmm_to_minutes(x["start"])):
        start_m = _hhmm_to_minutes(w["start"])
        end_m = _hhmm_to_minutes(w["end"])
        if start_m == 0:
            transitions[0]["heat_setpoint"] = float(comfort_c)
        else:
            transitions.append({"transition_time": start_m, "heat_setpoint": float(comfort_c)})
        if end_m < 1440:
            transitions.append({"transition_time": end_m, "heat_setpoint": float(setback_c)})
    return transitions[:6]
