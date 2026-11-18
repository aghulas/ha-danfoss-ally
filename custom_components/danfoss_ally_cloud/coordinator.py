"""Refresh coordinator.

Polls the cloud (path-1a cloud API) at a conservative interval and normalises the devices into
``{device_id: DanfossDevice}``. The local tunnel (v0.3) will later correct the fields the cloud
reports wrong (e.g. the real preheat 0x0025); here, cloud read only.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CloudAuthError, CloudClient, CloudError, DanfossDevice
from .api.local.manager import Head, LocalTunnelManager
from .api.rooms import Room, RoomState, aggregate_room

_LOGGER = logging.getLogger(__name__)

# The room topology (Tuya groups + members) rarely changes: we cache it and only re-download it
# after this interval (or on reload), to stay conservative on the quota.
_TOPOLOGY_TTL = 3600  # seconds


class DanfossCoordinator(DataUpdateCoordinator[dict[str, DanfossDevice]]):
    """Gathers the fleet state: heads (``data``) + aggregated rooms (``rooms``)."""

    def __init__(self, hass: HomeAssistant, client: CloudClient, scan_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="danfoss_ally_cloud",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        # Aggregated rooms (group_id -> RoomState) and head -> room membership, recomputed on each
        # refresh from the cached topology and the current head state.
        self.rooms: dict[str, RoomState] = {}
        self.grouped_ids: set[str] = set()
        # Per-home holiday state (read only, contract §4.5), keyed by gid. Refreshed on the
        # topology cadence (hourly): a holiday changes rarely and the read is best-effort.
        self.holidays: dict[str, dict] = {}
        # Rooms that drive each boiler relay (read only, contract §4.6), keyed by relay devId.
        # Refreshed on the topology cadence; the relay on/off state itself is in ``data`` each poll.
        self.relay_rooms: dict[str, list[dict]] = {}
        self._rooms_topology: dict[str, Room] = {}
        self._group_of: dict[str, str] = {}
        self._topology_ts: float = 0.0

    async def _async_update_data(self) -> dict[str, DanfossDevice]:
        """Cloud read: decoded heads (indexed by id) + per-room aggregation. No secret."""
        try:
            devices = await self.client.async_list_devices()
        except CloudAuthError as err:
            # Credentials/secrets refused: triggers HA re-authentication.
            raise ConfigEntryAuthFailed(str(err)) from err
        except CloudError as err:
            raise UpdateFailed(str(err)) from err
        data = {dev.id: dev for dev in devices}
        await self._ensure_topology(data)
        self.rooms = {
            gid: aggregate_room(room, members)
            for gid, room in self._rooms_topology.items()
            if (members := [data[m] for m in room.members if m in data])
        }
        self.grouped_ids = {head_id for head_id in self._group_of if head_id in data}
        return data

    def group_of(self, head_id: str) -> str | None:
        """A head's room group_id, or None if the head is not grouped."""
        return self._group_of.get(head_id)

    async def _ensure_topology(self, data: dict[str, DanfossDevice] | None = None) -> None:
        """Refresh the room topology if the cache expired. Best-effort: never blocks.

        On a read failure: keep the previous cache if any, else an empty topology (all heads treated
        as isolated - read-only thermostat). Holiday and relay-room reads ride the same cadence.
        """
        now = time.monotonic()
        if self._rooms_topology and (now - self._topology_ts) < _TOPOLOGY_TTL:
            return
        try:
            rooms_topology, group_of = await self._fetch_topology()
        except CloudError as err:
            if self._rooms_topology:
                _LOGGER.debug("room topology kept (read failed: %s)", err)
                return
            _LOGGER.warning("room topology unavailable (%s): heads treated individually", err)
            self._rooms_topology, self._group_of, self._topology_ts = {}, {}, now
            return
        self._rooms_topology, self._group_of, self._topology_ts = rooms_topology, group_of, now
        await self._refresh_holidays()
        await self._refresh_relay_rooms(data or {})

    async def _refresh_relay_rooms(self, data: dict[str, DanfossDevice]) -> None:
        """Refresh, per boiler relay, the rooms that drive it.

        Best-effort: a per-relay read failure keeps the previous linkage for that relay.
        """
        out: dict[str, list[dict]] = {}
        for dev in data.values():
            if not dev.is_relay:
                continue
            try:
                out[dev.id] = await self.client.async_relay_rooms(dev.id)
            except CloudError as err:
                _LOGGER.debug("relay rooms kept for %s (read failed: %s)", dev.id, err)
                out[dev.id] = self.relay_rooms.get(dev.id, [])
        self.relay_rooms = out

    async def _refresh_holidays(self) -> None:
        """Refresh the per-home holiday state (best-effort; keeps the previous value on failure)."""
        try:
            holidays = await self.client.async_list_holidays()
        except CloudError as err:
            _LOGGER.debug("holiday read skipped (%s)", err)
            return
        self.holidays = {h["gid"]: h for h in holidays}

    async def _fetch_topology(self) -> tuple[dict[str, Room], dict[str, str]]:
        """Read the rooms (groups) and their members of each home (path 1a)."""
        rooms_topology: dict[str, Room] = {}
        group_of: dict[str, str] = {}
        for home in await self.client.async_get_homes():
            gid = home["gid"]
            groups = await self.client.async_list_groups(gid)
            members = await self.client.async_group_members(gid)
            for g in groups:
                gid_s = str(g["group_id"])
                member_ids = tuple(members.get(gid_s, ()))
                if not members:
                    continue
                rooms_topology[gid_s] = Room(
                    gid_s, g.get("name") or gid_s, g.get("pid"), str(gid), member_ids
                )
                for devid in member_ids:
                    group_of[devid] = gid_s
        return rooms_topology, group_of


class DanfossLocalCoordinator(DataUpdateCoordinator[dict[str, bool | None]]):
    """LOCAL survey (Zigbee tunnel) of the real preheat (0x0025), indexed by head id.

    Slow and best-effort: it corrects what the cloud reports wrong (cloud DP 1 only touches the
    gateway cache). Relies on the cloud coordinator to know the heads and their gateway.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        manager: LocalTunnelManager,
        cloud: DanfossCoordinator,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="danfoss_ally_cloud_local",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.manager = manager
        self._cloud = cloud

    def heads(self) -> list[Head]:
        """Heads reachable through the tunnel (node_id + gateway known to the manager)."""
        gws = self.manager.gateway_ids
        return [
            Head(d.id, d.node_id, d.mesh_id)
            for d in self._cloud.data.values()
            if d.is_head and d.node_id and d.mesh_id and d.mesh_id in gws
        ]

    async def _async_update_data(self) -> dict[str, bool | None]:
        heads = self.heads()
        if not heads:
            return {}
        try:
            return await self.hass.async_add_executor_job(self.manager.survey_preheat, heads)
        except Exception as err:  # noqa: BLE001 - best-effort local fallback
            raise UpdateFailed(f"local survey: {err}") from err
