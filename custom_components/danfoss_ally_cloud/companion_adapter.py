"""v2.x Companion Store & Coordinator View Adapter (Batch 2.5, ``docs/companion-contract.md`` §4).

Adapts ``MqttCompanionCoordinator`` + ``CompanionRoomManager`` to the ``DanfossCoordinator`` store
interface consumed by ``ops_views.py`` (``rooms_payload``, ``overview_payload``,
``holidays_payload``, ``relays_payload``), ``websocket_api.py``, ``services.py``, and the Home
Assistant entity platforms — so the existing Lovelace panel (``<danfoss-ally-panel>``) and cards
render a mixed ``zigbee2mqtt`` + ``danfoss2mqtt`` fleet without a single line changed in the
TypeScript frontend bundle.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant

from .api import DanfossDevice
from .api.rooms import RoomState
from .companion_rooms import CompanionRoomManager
from .const import DATA_COORDINATOR, DATA_JOBS, DATA_SCHEDULES
from .mqtt_companion import MqttCompanionCoordinator
from .writejob import JobManager


class CompanionCoordinatorView:
    """Drop-in ``DanfossCoordinator``-compatible view backed by ``MqttCompanionCoordinator``."""

    def __init__(
        self,
        companion: MqttCompanionCoordinator,
        room_manager: CompanionRoomManager,
    ) -> None:
        self.companion = companion
        self.room_manager = room_manager
        self.hass: HomeAssistant = companion.hass
        self.home_rooms: dict[str, list[dict[str, Any]]] = {}
        self.device_home: dict[str, str] = {}
        self.messages: list[Any] = []
        self.last_update_success: bool = True

    @property
    def data(self) -> dict[str, DanfossDevice]:
        return self.companion.data

    @property
    def rooms(self) -> dict[str, RoomState]:
        return self.room_manager.build_rooms()

    @property
    def relay_rooms(self) -> dict[str, list[dict[str, Any]]]:
        """Relay id -> rooms eligible to drive it, as the bridges publish them (``bridge/relays``).

        Empty for a relay no bridge has published: read-only here, and never assumed.
        """
        return self.companion.relay_rooms

    @property
    def holidays(self) -> dict[str, dict[str, Any]]:
        return self.companion.holidays

    def group_of(self, head_id: str) -> str | None:
        """Return the ``group_id`` of the room containing ``head_id``, or ``None`` if isolated."""
        for gid, member_ids in self.room_manager.room_members().items():
            if head_id in member_ids:
                return gid
        return None

    def room_members(self, group_id: str) -> tuple[str, ...]:
        """Member head ids of a room (group), matching ``DanfossCoordinator.room_members``."""
        return self.room_manager.room_members().get(group_id, ())

    def home_of(self, group_id: str) -> str | None:
        """Return the home gid of ``group_id``."""
        raw = self.companion.native_rooms.get(group_id)
        if isinstance(raw, dict):
            return str(raw.get("home_id") or "default")
        cfg = self.room_manager.virtual_rooms.get(group_id)
        if cfg is not None:
            return cfg.home_id or "companion"
        return None

    def head_home(self, head_id: str) -> str | None:
        """Return the home gid of ``head_id``."""
        if head_id in self.device_home:
            return self.device_home[head_id]
        if head_id in self.companion.device_home:
            return self.companion.device_home[head_id]
        gid = self.group_of(head_id)
        if gid is not None:
            return self.home_of(gid)
        route = self.companion.device_route.get(head_id)
        return route[0] if route is not None else None

    def sensor_rooms(self) -> dict[str, str]:
        """Room sensor id -> ``group_id`` of the room it measures (overview, contract §3.6).

        A native room names its sensor in ``bridge/rooms`` (``sensor``); a Companion-managed room in
        its stored configuration (``sensor_id``); an isolated head (no schedule group) names the
        sensor of its Tuya room in ``bridge/devices`` (``danfoss.room_sensor``), and the sensor then
        maps to the head's id, which is its single-head room's id in the overview. Only sensors
        present in the fleet are returned; a sensor named by two rooms keeps the first one.
        """
        out: dict[str, str] = {}
        for gid, raw in self.companion.native_rooms.items():
            sensor_id = str(raw["sensor"]) if isinstance(raw, dict) and raw.get("sensor") else None
            if sensor_id and sensor_id in self.data:
                out.setdefault(sensor_id, gid)
        for gid, cfg in self.room_manager.virtual_rooms.items():
            if cfg.sensor_id and cfg.sensor_id in self.data:
                out.setdefault(cfg.sensor_id, gid)
        for head_id, sensor_id in self.companion.head_room_sensor.items():
            head = self.data.get(head_id)
            if head is None or not head.is_head or self.group_of(head_id) is not None:
                continue
            if sensor_id in self.data and self.data[sensor_id].is_sensor:
                out.setdefault(sensor_id, head_id)
        return out

    @property
    def grouped_ids(self) -> set[str]:
        out: set[str] = set()
        for member_ids in self.room_manager.room_members().values():
            for member_id in member_ids:
                if member_id in self.data:
                    out.add(member_id)
        return out

    def room_retired(self, group_id: str) -> bool:
        return group_id not in self.rooms

    def async_add_listener(
        self, update_callback: Callable[[], None], context: Any = None
    ) -> CALLBACK_TYPE:
        return self.companion.async_add_listener(update_callback, context)

    def note_commanded(self, head_ids: Any) -> None:
        """No-op: the R-3 "freshen on next poll" hint has no meaning for a push-based coordinator.

        The cloud ``DanfossCoordinator`` uses this to shorten the next poll of just-commanded heads;
        the Companion state is pushed over MQTT, so there is nothing to schedule. Provided so the
        shared write path (``operations.set_schedule`` / ``restore_schedule``, entity platforms)
        runs unchanged against this view.
        """

    async def async_request_refresh(self) -> None:
        """No-op: Companion device/room state is already current from MQTT (no poll to trigger)."""


def build_companion_store(
    companion: MqttCompanionCoordinator,
    room_manager: CompanionRoomManager,
) -> dict[str, Any]:
    """Build a ``hass.data[DOMAIN][entry_id]`` store dict backed by the MQTT Companion."""
    view = CompanionCoordinatorView(companion, room_manager)
    return {
        DATA_COORDINATOR: view,
        DATA_JOBS: JobManager(),
        DATA_SCHEDULES: {},
        "companion": companion,
        "room_manager": room_manager,
    }
