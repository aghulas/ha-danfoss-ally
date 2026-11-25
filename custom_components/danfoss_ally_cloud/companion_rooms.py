"""v2.x Companion Room, Schedule & External Sensor Orchestrator (``docs/companion-contract.md`` §3).

Unifies native Danfoss rooms (published on ``danfoss2mqtt/bridge/rooms``) and Companion-managed
virtual rooms (grouping ``zigbee2mqtt`` heads ``014G2461`` + an optional ``014G2480`` room sensor):

1. **Unified ``RoomState``**: aggregates member heads (via ``api.rooms.aggregate_room``) and
   overrides room temperature with the linked ``014G2480`` room sensor when online.
2. **External Room Sensor & Load Balancing Loop** (``async_sync_telemetry``), two feeds, each
   closed unless its Companion option is on (``feed_external_sensor`` / ``feed_load_mean``):
   - Pushes the linked ``014G2480`` temperature to each member head's
     ``external_measured_room_sensor`` (in 0.01 °C) when it shifted by >= 0.2 °C or the head's last
     write is >= 20 min old, never more often than every 5 min per head (and sends ``-8000`` once
     if the sensor goes offline).
   - Computes the room's mean ``load_estimate`` across member heads reporting a valid load
     (excluding -8000) and pushes ``load_room_mean`` when it shifts by >= 25 or >= 15 min, only
     when every member of the room reports ``load_balancing_enable`` on.
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
from .api.schedule import MAX_TRANSITIONS_PER_DAY
from .const import DOMAIN
from .mqtt_companion import MqttCompanionCoordinator

_ROOMS_STORE_VERSION = 1

# External-sensor feed timing. In room-sensor mode (``radiator_covered`` true) the head wants a
# write at least every 30 min, at most every 5 min, and resets the value by itself after 35 min
# (Zigbee2MQTT's documentation of 014G2461, not observed on our hardware). The feed is evaluated on
# a timer, so a keep-alive lands at most one tick after its threshold:
# EXTERNAL_SENSOR_REFRESH_SECONDS + COMPANION_TELEMETRY_INTERVAL must stay under 30 min.
EXTERNAL_SENSOR_REFRESH_SECONDS = 1200.0  # keep-alive threshold, per head
EXTERNAL_SENSOR_MIN_INTERVAL_SECONDS = 300.0  # floor between two writes to one head
EXTERNAL_SENSOR_DEADLINE_SECONDS = 1800.0  # the head's "at least every 30 min"
EXTERNAL_SENSOR_DELTA_C = 0.2
EXTERNAL_SENSOR_DISABLED_RAW = -8000
LOAD_MEAN_REFRESH_SECONDS = 900.0  # 15 min; on the telemetry tick this lands at 15-18 min
LOAD_MEAN_DELTA = 25  # load estimate delta to trigger update
LOAD_ESTIMATE_DISABLED_RAW = -8000

# ZCL/Z2M day-of-week bit per canonical (cloud, 3-letter) day key.
_Z2M_DAY_BITS: dict[str, int] = {
    "sun": 0x01,
    "mon": 0x02,
    "tue": 0x04,
    "wed": 0x08,
    "thu": 0x10,
    "fri": 0x20,
    "sat": 0x40,
}

# Accept both the cloud 3-letter day keys used by the schedule services (``api.schedule.DAYS``:
# ``mon``…``sun``) and the full English names used by the z2m-oriented callers, mapping both to the
# canonical 3-letter key. The schedule service path (``operations.set_schedule``) passes the cloud
# keys; existing virtual-room callers pass full names — both must fan out the same weekly schedule.
_DAY_ALIASES: dict[str, str] = {
    "sun": "sun", "sunday": "sun",
    "mon": "mon", "monday": "mon",
    "tue": "tue", "tues": "tue", "tuesday": "tue",
    "wed": "wed", "wednesday": "wed",
    "thu": "thu", "thur": "thu", "thurs": "thu", "thursday": "thu",
    "fri": "fri", "friday": "fri",
    "sat": "sat", "saturday": "sat",
}  # fmt: skip


def normalize_day(name: str) -> str | None:
    """Canonical 3-letter day key for ``name`` (cloud key or full name), or ``None`` if unknown."""
    return _DAY_ALIASES.get(name.strip().lower())


class UnsupportedCompanionWriteError(RuntimeError):
    """Raised when a Companion write targets a bridge that does not support that /set field."""


@dataclass(slots=True)
class CompanionRoomConfig:
    """Configuration of a Companion-managed room (e.g. grouping ``zigbee2mqtt`` heads + sensor)."""

    room_id: str
    name: str
    head_ids: list[str]
    sensor_id: str | None = None
    home_id: str | None = None
    comfort_setpoint: float = 21.0
    setback_setpoint: float = 17.0
    schedule: dict[str, list[dict[str, str]]] = field(default_factory=dict)


@dataclass(slots=True)
class _HeadSensorFeed:
    """Last external-sensor write to one head (``value`` None = never fed, or reset to -8000)."""

    value: float | None = None
    sent_at: float | None = None


@dataclass(slots=True)
class _TelemetryCache:
    last_load_mean: int | None = None
    last_load_sent_at: float = 0.0


class CompanionRoomManager:
    """Manages unified rooms, external sensor sync, load balancing, and boiler demand."""

    def __init__(
        self,
        companion: MqttCompanionCoordinator,
        *,
        feed_external_sensor: bool = False,
        feed_load_mean: bool = False,
    ) -> None:
        self._companion = companion
        self.virtual_rooms: dict[str, CompanionRoomConfig] = {}
        # Last weekly schedule fanned out per room_id (raw day keys as passed). The Companion has no
        # read-back channel from the heads, so this is the authoritative source for ``get_schedule``
        # / ``restore_schedule`` — for native (danfoss2mqtt) rooms as well as virtual ones, which
        # also persist it on their ``CompanionRoomConfig``. In-memory only (lost on restart).
        self._room_schedules: dict[str, dict[str, list[dict[str, str]]]] = {}
        self._telemetry: dict[str, _TelemetryCache] = {}
        self._sensor_feed: dict[str, _HeadSensorFeed] = {}
        # The two periodic feeds, closed unless opened (Companion options, read at every sync).
        self.feed_external_sensor = feed_external_sensor
        self.feed_load_mean = feed_load_mean

    def add_virtual_room(self, cfg: CompanionRoomConfig) -> None:
        self.virtual_rooms[cfg.room_id] = cfg
        self._telemetry.setdefault(cfg.room_id, _TelemetryCache())

    def remove_virtual_room(self, room_id: str) -> None:
        cfg = self.virtual_rooms.pop(room_id, None)
        self._telemetry.pop(room_id, None)
        for head_id in cfg.head_ids if cfg else ():
            self._sensor_feed.pop(head_id, None)

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
                    home_id=str(item["home_id"]) if item.get("home_id") else None,
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
        await store.async_save({"rooms": [asdict(cfg) for cfg in self.virtual_rooms.values()]})

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

        # 1) Native rooms from danfoss2mqtt / danfoss-room-coordinator bridge/rooms
        for gid, raw in self._companion.native_rooms.items():
            member_ids = tuple(str(m) for m in (raw.get("members") or ()))
            members = [self._companion.data[m] for m in member_ids if m in self._companion.data]
            if members:
                room = Room(
                    group_id=gid,
                    name=str(raw.get("name") or gid),
                    pid=raw.get("pid"),
                    home_gid=str(raw.get("home_id") or "default"),
                    members=member_ids,
                )
                state = aggregate_room(room, members)
                sensor_id = str(raw["sensor"]) if raw.get("sensor") else None
                if sensor_id and sensor_id in self._companion.data:
                    sensor = self._companion.data[sensor_id]
                    if sensor.online and sensor.temperature is not None:
                        state.temperature = sensor.temperature
                elif isinstance(raw.get("temperature"), (int, float)):
                    state.temperature = float(raw["temperature"])
                out[gid] = state

        # 2) Companion-managed virtual rooms (zigbee2mqtt or mixed heads + 014G2480 sensor)
        for rid, cfg in self.virtual_rooms.items():
            members = [self._companion.data[m] for m in cfg.head_ids if m in self._companion.data]
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
            demands = [m.valve_opening for m in members if m.valve_opening is not None]
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
        if self._companion.is_coordinator_room(room_id):
            prefix = self._companion.prefix_of_room(room_id)
            assert prefix is not None
            await self._companion.async_bridge_request(
                prefix,
                "room/set-setpoint",
                {"room_id": room_id, "setpoint": float(temperature_c), "source": "user"},
            )
            return len(member_ids)
        sent = 0
        for head_id in member_ids:
            if head_id in self._companion.device_route:
                await self._companion.async_send_device_set(head_id, setpoint=temperature_c)
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

        unsupported_heads = [
            head_id
            for head_id in member_ids
            if not self._companion.supports_device_set(head_id, "weekly_schedule")
        ]
        if unsupported_heads:
            raise UnsupportedCompanionWriteError(
                f"room {room_id} has head(s) whose bridge does not support /set weekly_schedule "
                f"({', '.join(unsupported_heads)}); nothing was sent"
            )

        comfort = comfort_c if comfort_c is not None else (cfg.comfort_setpoint if cfg else 21.0)
        setback = setback_c if setback_c is not None else (cfg.setback_setpoint if cfg else 17.0)

        # Validate the whole request before storing or sending anything: a refused day must not
        # leave the heads with half a week.
        payloads: list[dict[str, Any]] = []
        for day_name, windows in days.items():
            canon = normalize_day(day_name)
            day_bit = _Z2M_DAY_BITS.get(canon) if canon else None
            if day_bit is None:
                raise ValueError(f"Invalid day name: {day_name}")
            transitions = _build_z2m_day_transitions(windows, comfort, setback)
            if len(transitions) > MAX_TRANSITIONS_PER_DAY:
                raise ValueError(
                    f"Too many transitions on {day_name}: {len(transitions)} > "
                    f"{MAX_TRANSITIONS_PER_DAY} (R1); nothing was sent"
                )
            payloads.append(
                {
                    "weekly_schedule": {
                        "dayofweek": day_bit,
                        "num_of_transitions": len(transitions),
                        "mode": 1,  # heat
                        "transitions": transitions,
                    }
                }
            )

        # Record the schedule as the source for get_schedule / restore_schedule (all validated).
        self._room_schedules[room_id] = {day: list(windows) for day, windows in days.items()}
        if cfg is not None:
            cfg.schedule.update(days)
            cfg.comfort_setpoint = comfort
            cfg.setback_setpoint = setback

        sent = 0
        for payload in payloads:
            for head_id in member_ids:
                if head_id in self._companion.device_route:
                    await self._companion.async_send_raw_device_set(head_id, payload)
                    sent += 1
        return sent

    def get_room_schedule(self, room_id: str) -> dict[str, list[dict[str, str]]]:
        """Last weekly schedule fanned out to ``room_id`` (raw day keys), or ``{}`` if none.

        The Companion has no schedule read-back from the heads: this returns what the integration
        last wrote (via ``async_set_room_schedule``), preferring the in-memory record and falling
        back to the room config's persisted schedule for virtual rooms.
        """
        recorded = self._room_schedules.get(room_id)
        if recorded:
            return {day: list(windows) for day, windows in recorded.items()}
        cfg = self.virtual_rooms.get(room_id)
        if cfg is not None and cfg.schedule:
            return {day: list(windows) for day, windows in cfg.schedule.items()}
        return {}

    def _load_balancing_on(self, cfg: CompanionRoomConfig) -> bool:
        """True when every configured member of the room reports ``load_balancing_enable`` on.

        A member that is unknown, or has not reported the attribute, counts as off: a head with
        load balancing disabled has no use for a room mean, and one we know nothing about is not
        written on a guess."""
        return len(cfg.head_ids) > 1 and all(
            (dev := self._companion.data.get(head_id)) is not None
            and dev.load_balancing_enable is True
            for head_id in cfg.head_ids
        )

    async def async_sync_telemetry(self, *, now: float | None = None) -> dict[str, int]:
        """Push external sensor temperatures (014G2480 -> heads) and ``load_room_mean`` for
        virtual rooms, each feed only when its option is on.
        Returns ``{"external_sensor_writes": n1, "load_mean_writes": n2}``."""
        ts = time.monotonic() if now is None else now
        ext_writes = 0
        load_writes = 0
        # Single owner per head (§5.1): skip heads already owned by a bridge-published room.
        bridge_owned = {
            str(m)
            for raw in self._companion.native_rooms.values()
            for m in (raw.get("members") or ())
        }

        for rid, cfg in self.virtual_rooms.items():
            cache = self._telemetry.setdefault(rid, _TelemetryCache())
            members = [
                self._companion.data[m]
                for m in cfg.head_ids
                if m not in bridge_owned
                and m in self._companion.data
                and self._companion.data[m].online
            ]
            if not members:
                continue

            # 1) External room sensor temperature (014G2480 -> member heads), tracked per head so a
            #    head that missed a round (offline) is not left waiting for the room's next one.
            if self.feed_external_sensor and cfg.sensor_id:
                sensor = self._companion.data.get(cfg.sensor_id)
                temp = sensor.temperature if sensor is not None and sensor.online else None
                for head in members:
                    feed = self._sensor_feed.setdefault(head.id, _HeadSensorFeed())
                    if (
                        feed.sent_at is not None
                        and (ts - feed.sent_at) < EXTERNAL_SENSOR_MIN_INTERVAL_SECONDS
                    ):
                        continue
                    if temp is None:
                        # Sensor offline: disable the external temperature once (-80.0 °C = -8000)
                        if feed.value is None:
                            continue
                        value = EXTERNAL_SENSOR_DISABLED_RAW / 100.0
                    elif (
                        feed.value is None
                        or feed.sent_at is None
                        or abs(temp - feed.value) >= EXTERNAL_SENSOR_DELTA_C - 1e-9
                        or (ts - feed.sent_at) >= EXTERNAL_SENSOR_REFRESH_SECONDS
                    ):
                        value = temp
                    else:
                        continue
                    await self._companion.async_send_device_set(
                        head.id, external_sensor_temp_c=value
                    )
                    ext_writes += 1
                    feed.value = temp
                    feed.sent_at = ts

            # 2) Multi-head room load balancing (mean load_estimate -> load_room_mean)
            if self.feed_load_mean and len(members) > 1 and self._load_balancing_on(cfg):
                loads = [
                    m.load_estimate
                    for m in members
                    if m.load_estimate is not None and m.load_estimate != LOAD_ESTIMATE_DISABLED_RAW
                ]
                # Only balance when at least 2 member heads report a valid load estimate
                if len(loads) >= 2:
                    mean_load = int(round(sum(loads) / len(loads)))
                    due = (
                        cache.last_load_mean is None
                        or abs(mean_load - cache.last_load_mean) >= LOAD_MEAN_DELTA
                        or (ts - cache.last_load_sent_at) >= LOAD_MEAN_REFRESH_SECONDS
                    )
                    if due:
                        for head in members:
                            await self._companion.async_send_device_set(
                                head.id, load_room_mean=mean_load
                            )
                            load_writes += 1
                        cache.last_load_mean = mean_load
                        cache.last_load_sent_at = ts

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
    return transitions
