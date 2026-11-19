"""Refresh coordinator.

Polls the cloud (path-1a cloud API) at a conservative interval and normalises the devices into
``{device_id: DanfossDevice}``. The local tunnel (v0.3) will later correct the fields the cloud
reports wrong (e.g. the real preheat 0x0025); here, cloud read only.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from datetime import timedelta

from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CloudAuthError, CloudClient, CloudError, DanfossDevice, apply_dps_overlay
from .api.local.manager import Head, LocalTunnelManager
from .api.rooms import Room, RoomState, aggregate_room
from .const import (
    POST_COMMAND_REFRESH_MAX_HEADS,
    POST_COMMAND_REFRESH_TTL,
    POST_COMMAND_SETTLE,
)

_LOGGER = logging.getLogger(__name__)

# The room topology (Tuya groups + members) rarely changes: we cache it and only re-download it
# after this interval (or on reload), to stay conservative on the quota.
_TOPOLOGY_TTL = 3600  # seconds


class DanfossCoordinator(DataUpdateCoordinator[dict[str, DanfossDevice]]):
    """Gathers the fleet state: heads (``data``) + aggregated rooms (``rooms``)."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: CloudClient,
        scan_interval: int,
        *,
        post_command_refresh: bool = False,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="danfoss_ally_cloud",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        # Post-command refresh (R-3): head_id -> (not_before, deadline), monotonic. Between the two
        # the head is read via the per-device route instead of trusting the lagging bulk list;
        # before not_before (settle delay) the cloud may not have taken the command yet, so the
        # bulk value is kept. Empty (and a no-op) unless the option is on.
        self._post_command_refresh = post_command_refresh
        self._commanded: dict[str, tuple[float, float]] = {}
        # One-shot refresh scheduled at the end of the settle delay (cancelled on shutdown).
        self._settle_unsub: CALLBACK_TYPE | None = None
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
        await self._overlay_commanded(data)
        await self._ensure_topology(data)
        self.rooms = {
            gid: aggregate_room(room, members)
            for gid, room in self._rooms_topology.items()
            if (members := [data[m] for m in room.members if m in data])
        }
        self.grouped_ids = {head_id for head_id in self._group_of if head_id in data}
        return data

    def note_commanded(self, head_ids: Iterable[str]) -> None:
        """Mark heads just commanded so the next polls read them via the per-device route (R-3).

        No-op unless the post-command refresh option is on. Called by the write paths (room
        setpoint, schedule set / restore, room settings) right after a successful cloud write.
        Each call (re)arms the window for ``POST_COMMAND_REFRESH_TTL`` seconds.

        The overlay only starts after ``POST_COMMAND_SETTLE`` seconds: a per-device read made right
        after the write returns the pre-command state (the cloud takes the command in ~15 s), which
        left the written entity one write behind until the next poll. The write's own immediate
        refresh therefore keeps the bulk value, and one extra refresh is scheduled at the end of the
        settle delay to read the commanded heads once the cloud has them. Never optimistic: what is
        shown is always what the cloud returns.
        """
        if not self._post_command_refresh:
            return
        now = time.monotonic()
        window = (now + POST_COMMAND_SETTLE, now + POST_COMMAND_REFRESH_TTL)
        marked = False
        for head_id in head_ids:
            if head_id:
                self._commanded[head_id] = window
                marked = True
        if marked:
            self._schedule_settle_refresh()

    def _schedule_settle_refresh(self) -> None:
        """(Re)schedule the one-shot refresh at the end of the settle delay."""
        if self._settle_unsub is not None:
            self._settle_unsub()
        self._settle_unsub = async_call_later(
            self.hass, POST_COMMAND_SETTLE, self._async_settle_refresh
        )

    async def _async_settle_refresh(self, _now: object) -> None:
        self._settle_unsub = None
        await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        """Cancel a pending settle refresh, then the base shutdown."""
        if self._settle_unsub is not None:
            self._settle_unsub()
            self._settle_unsub = None
        await super().async_shutdown()

    async def _overlay_commanded(self, data: dict[str, DanfossDevice]) -> None:
        """Overlay the per-device (fresh) DPs onto recently commanded heads (R-3). Best-effort.

        Bounded on purpose (the user's real account): only heads still inside their post-command
        window and past the settle delay are read, at most ``POST_COMMAND_REFRESH_MAX_HEADS`` per
        poll, one per-device read each. A read failure or an empty response keeps the bulk value
        (never raises). Expired entries are pruned so a head returns to the bulk route after its
        window.
        """
        if not self._post_command_refresh or not self._commanded:
            return
        now = time.monotonic()
        self._commanded = {h: w for h, w in self._commanded.items() if w[1] > now}
        hot = [
            h
            for h, (not_before, _) in self._commanded.items()
            if not_before <= now and h in data and data[h].is_head
        ]
        for head_id in hot[:POST_COMMAND_REFRESH_MAX_HEADS]:
            try:
                fresh = await self.client.async_get_device_dps(head_id)
            except CloudError as err:
                _LOGGER.debug("post-command refresh kept bulk for %s (%s)", head_id, err)
                continue
            if fresh:
                data[head_id] = apply_dps_overlay(data[head_id], fresh)

    def group_of(self, head_id: str) -> str | None:
        """A head's room group_id, or None if the head is not grouped."""
        return self._group_of.get(head_id)

    def room_members(self, group_id: str) -> tuple[str, ...]:
        """Member head ids of a room (group), from the cached topology. Empty if unknown."""
        room = self._rooms_topology.get(group_id)
        return room.members if room else ()

    def home_of(self, group_id: str) -> str | None:
        """The home gid a room (group) belongs to, from the cached topology."""
        room = self._rooms_topology.get(group_id)
        return room.home_gid if room else None

    def invalidate_topology(self) -> None:
        """Drop the topology cache so the next refresh re-reads rooms (and holidays, relay links).

        Called after a structural write (create / rename / delete / attach / detach a room, or a
        relay link): the room topology is otherwise cached for an hour, so without this the new or
        changed room would stay invisible to ``rooms`` / ``get_rooms`` / the room-id resolver until
        the next hourly poll.

        Uses ``-inf`` (not ``0``): the freshness guard is ``now - _topology_ts < TTL`` with ``now =
        time.monotonic()``, which can be smaller than the TTL on a freshly booted host, so ``0``
        would not reliably force the refetch. ``-inf`` always does.
        """
        self._topology_ts = float("-inf")

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

    async def async_refresh_head(self, head: Head) -> bool | None:
        """Re-read ONE head's preheat through the tunnel and update its entry in ``data``.

        Called after a preheat write: the full survey reads every head (~8 s each), so a write was
        only reflected ~13 min later on a site-sized install (real hardware, 2026-11-19). This reads
        back the head itself, never assumes the written value: an unanswered read stores ``None``,
        which makes the switch unavailable until the next survey (rather than lying). The survey
        schedule is left untouched (listeners are notified directly).
        """
        try:
            value = await self.hass.async_add_executor_job(self.manager.read_preheat, head)
        except Exception as err:  # noqa: BLE001 - best-effort, as the survey
            _LOGGER.debug("local preheat read-back failed (%s)", type(err).__name__)
            value = None
        data = dict(self.data or {})
        data[head.dev_id] = value
        self.data = data
        self.async_update_listeners()
        return value

    async def _async_update_data(self) -> dict[str, bool | None]:
        heads = self.heads()
        if not heads:
            return {}
        try:
            return await self.hass.async_add_executor_job(self.manager.survey_preheat, heads)
        except Exception as err:  # noqa: BLE001 - best-effort local fallback
            raise UpdateFailed(f"local survey: {err}") from err
