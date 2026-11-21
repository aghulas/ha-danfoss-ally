"""Refresh coordinators: cloud HTTP polling (``DanfossCoordinator``) and local Zigbee tunnel
survey (``DanfossLocalCoordinator``).

Polls the cloud (path-1a cloud API) at a conservative interval, overlays fresh per-device DPs for
recently commanded heads (R-3), and aggregates rooms, holidays and relay linkage. The optional
local tunnel coordinator surveys the real preheat state (attribute 0x0025) in the background.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable
from datetime import timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    CloudAuthError,
    CloudClient,
    CloudError,
    DanfossDevice,
    DanfossMessage,
    apply_dps_overlay,
)
from .api.local.manager import Head, LocalTunnelManager
from .api.rooms import Room, RoomState, aggregate_room
from .const import (
    EVENT_MESSAGE,
    LOCAL_SETTINGS_INTERVAL,
    MESSAGES_SCAN_INTERVAL,
    POST_COMMAND_REFRESH_MAX_HEADS,
    POST_COMMAND_REFRESH_TTL,
    POST_COMMAND_SETTLE,
)

_LOGGER = logging.getLogger(__name__)

# The room topology (Tuya groups + members) rarely changes: we cache it and only re-download it
# after this interval (or on reload), to stay conservative on the quota.
_TOPOLOGY_TTL = 3600  # seconds

# Cap for exponential polling backoff on repeated transient CloudError failures.
_MAX_BACKOFF_SECONDS = 900


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
        self._base_interval = timedelta(seconds=scan_interval)
        self._consecutive_failures = 0
        super().__init__(
            hass,
            _LOGGER,
            name="danfoss_ally_cloud",
            update_interval=self._base_interval,
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
        # False until a topology read in which every home that lists rooms also gave their
        # members (see ``room_retired``).
        self._topology_complete = False
        # Per-home holiday state (read only, contract §4.5), keyed by gid. Refreshed on the
        # topology cadence (hourly): a holiday changes rarely and the read is best-effort.
        self.holidays: dict[str, dict] = {}
        # Rooms that drive each boiler relay (read only, contract §4.6), keyed by relay devId.
        # Refreshed on the topology cadence; the relay on/off state itself is in ``data`` each poll.
        self.relay_rooms: dict[str, list[dict]] = {}
        # Room map of each home (Tuya rooms, type 4: [{room_id, name}]), keyed by home gid. Read on
        # the topology cadence; names the app room of a single-head room (§3.6), by name only.
        self.home_rooms: dict[str, list[dict]] = {}
        # Head/device id -> home gid, from the per-home device lists of the last poll (exact).
        self.device_home: dict[str, str] = {}
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
            self._consecutive_failures += 1
            base_s = max(int(self._base_interval.total_seconds()), 60)
            backoff_s = min(
                base_s * (2 ** min(self._consecutive_failures - 1, 3)),
                _MAX_BACKOFF_SECONDS,
            )
            self.update_interval = timedelta(seconds=backoff_s)
            raise UpdateFailed(str(err)) from err
        if self._consecutive_failures:
            self._consecutive_failures = 0
            self.update_interval = self._base_interval
        data = {dev.id: dev for dev in devices}
        homes = getattr(self.client, "device_home", None)
        if isinstance(homes, dict):
            # Merge: a home whose list failed this poll keeps its devices' last known home.
            self.device_home = {**self.device_home, **homes}
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

    def head_home(self, dev_id: str) -> str | None:
        """The home gid a device belongs to (per-home device list), or None if unknown."""
        return self.device_home.get(dev_id)

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
        await self._refresh_home_rooms()

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

    async def _refresh_home_rooms(self) -> None:
        """Refresh each home's room map (``room.map.get``). Best-effort, read only.

        A home whose read fails keeps its previous map. Used only to name single-head rooms in the
        fleet overview: the room (type 4) membership is empty on the cloud, so the link is by name.
        """
        try:
            homes = await self.client.async_get_homes()
        except CloudError as err:
            _LOGGER.debug("room maps kept (home list failed: %s)", err)
            return
        out: dict[str, list[dict]] = {}
        for home in homes:
            gid = str(home["gid"])
            try:
                out[gid] = list(await self.client.async_list_rooms(home["gid"]))
            except CloudError as err:
                _LOGGER.debug("room map kept for a home (read failed: %s)", err)
                if gid in self.home_rooms:
                    out[gid] = self.home_rooms[gid]
        self.home_rooms = out

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
        complete = True
        for home in await self.client.async_get_homes():
            gid = home["gid"]
            groups = await self.client.async_list_groups(gid)
            members = await self.client.async_group_members(gid)
            if groups and not members:
                # Rooms listed but no membership at all for this home: a degraded answer, not a
                # home whose rooms vanished. Its rooms are left out, and nothing may be retired.
                complete = False
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
        self._topology_complete = complete
        return rooms_topology, group_of

    def room_retired(self, group_id: str) -> bool:
        """True only when a room is positively known to be gone, so its entities may be removed.

        A room leaves ``rooms`` as soon as none of its heads is in the last device list, and that
        list can be a SUBSET without any error when one home does not answer
        (``CloudClient.device_list_complete``). Removing registry entries then would drop the
        entity ids, names and areas the user set, on a single degraded poll. So a room is retired
        only when the last device list was complete, the last topology read was complete, and
        that topology no longer lists the room. Anything less: the entities stay (unavailable).
        """
        if group_id in self.rooms or group_id in self._rooms_topology:
            return False
        if not self._topology_complete:
            return False
        return bool(getattr(self.client, "device_list_complete", False))


class DanfossLocalCoordinator(DataUpdateCoordinator[dict[str, bool | None]]):
    """LOCAL survey (Zigbee tunnel) of the real preheat (0x0025), indexed by head id.

    Slow and best-effort: it corrects what the cloud reports wrong (cloud DP 1 only touches the
    gateway cache). Relies on the cloud coordinator to know the heads and their gateway.

    A survey reads the heads one by one (seconds each, minutes for a whole site), so it is never
    awaited by the entry setup: ``data`` starts EMPTY (every preheat switch unavailable, never a
    default ON/OFF) and each head is published as soon as it is read. Only one survey runs at a
    time, and it is aborted when its task is cancelled (entry unload, Home Assistant stop).
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
        # Nothing read yet: a head absent from ``data`` is unknown, hence unavailable.
        self.data = {}
        self._surveying = False
        # Heads read back on their own (after a write) while a survey runs: that read is at least
        # as fresh as the survey's, which must not overwrite it with a pre-write value.
        self._read_back: dict[str, bool | None] = {}
        # Standard attributes carried by the same frame as the preheat read (programming mode,
        # setpoint change source...), per head. A head that did not answer has no entry.
        self.attributes: dict[str, dict[str, Any]] = {}
        # Danfoss settings attributes (orientation, radiator covered...), per head, read by a
        # separate pass at most once per ``LOCAL_SETTINGS_INTERVAL``: two more frames per head.
        # Each entry also carries ``read_at`` (UTC). A head that misses a pass keeps its last
        # entry: these settings hardly ever change, and ``read_at`` says how old the value is.
        self.settings: dict[str, dict[str, Any]] = {}
        self._settings_at: float | None = None
        # Heads whose settings were read on their own (after a write) while a settings pass runs:
        # that read is fresher, the pass must not overwrite it with a pre-write value.
        self._settings_read_back: set[str] = set()

    def heads(self) -> list[Head]:
        """Heads reachable through the tunnel (node_id + gateway known to the manager)."""
        gws = self.manager.gateway_ids
        return [
            Head(d.id, d.node_id, d.mesh_id)
            for d in self._cloud.data.values()
            if d.is_head and d.node_id and d.mesh_id and d.mesh_id in gws
        ]

    def unaddressable(self) -> dict[str, str]:
        """Heads the tunnel cannot address (the complement of ``heads``): head id -> reason.

        ``no_node_id``: the cloud gives no Zigbee node id for the head; ``no_gateway_key``: its
        gateway is unknown or its local key was not fetched. Such a head is never surveyed and has
        no preheat switch.
        """
        gws = self.manager.gateway_ids
        return {
            d.id: "no_node_id" if not d.node_id else "no_gateway_key"
            for d in self._cloud.data.values()
            if d.is_head and not (d.node_id and d.mesh_id and d.mesh_id in gws)
        }

    async def async_refresh_head(self, head: Head) -> bool | None:
        """Re-read ONE head's preheat through the tunnel and update its entry in ``data``.

        Called after a preheat write: the full survey reads every head (~8 s each), so a write was
        only reflected ~13 min later on a site-sized install (real hardware, 2026-11-19). This reads
        back the head itself, never assumes the written value: an unanswered read stores ``None``,
        which makes the switch unavailable until the next survey (rather than lying). The survey
        schedule is left untouched (listeners are notified directly).
        """
        attrs: dict[str, Any] | None
        try:
            attrs = await self.hass.async_add_executor_job(self.manager.read_standard, head)
        except Exception as err:  # noqa: BLE001 - best-effort, as the survey
            _LOGGER.debug("local preheat read-back failed (%s)", type(err).__name__)
            attrs = None
        value: bool | None = None if attrs is None else attrs.get("preheat")
        self._store_attributes(head.dev_id, attrs)
        if self._surveying:
            self._read_back[head.dev_id] = value
        data = dict(self.data or {})
        data[head.dev_id] = value
        self.data = data
        self.async_update_listeners()
        return value

    async def async_refresh_settings(self, head: Head) -> dict[str, Any] | None:
        """Re-read ONE head's Danfoss settings through the tunnel and update its ``settings``
        entry (with a fresh ``read_at``). Returns what the head gave, None without an answer.

        The settings counterpart of ``async_refresh_head``, used to read a setting back after a
        write (orientation). An unanswered read leaves the last entry as it was (dated by its
        ``read_at``), as the daily pass does; a caller that has just written must therefore look
        at ``read_at`` or at the returned value, never at the stored entry alone."""
        attrs: dict[str, Any] | None
        try:
            attrs = await self.hass.async_add_executor_job(self.manager.read_settings, head)
        except Exception as err:  # noqa: BLE001 - best-effort, as the pass
            _LOGGER.debug("local settings read-back failed (%s)", type(err).__name__)
            attrs = None
        if attrs is None:
            return None
        if self._surveying:
            self._settings_read_back.add(head.dev_id)
        self.settings[head.dev_id] = {**attrs, "read_at": dt_util.utcnow()}
        self.async_update_listeners()
        return attrs

    def _store_attributes(self, dev_id: str, attrs: dict[str, Any] | None) -> bool:
        """Keep (or drop, for a head that did not answer) a head's attributes. True if changed."""
        if attrs is None:
            return self.attributes.pop(dev_id, None) is not None
        if self.attributes.get(dev_id) == attrs:
            return False
        self.attributes[dev_id] = attrs
        return True

    @callback
    def _async_head_attributes(self, dev_id: str, attrs: dict[str, Any] | None) -> None:
        """Keep the attributes of ONE head just read by the running survey (event loop)."""
        if not self._surveying or dev_id in self._read_back:
            return
        if self._store_attributes(dev_id, attrs):
            self.async_update_listeners()

    @callback
    def _async_head_settings(self, dev_id: str, attrs: dict[str, Any] | None) -> None:
        """Keep the settings of ONE head just read by the settings pass (event loop)."""
        if not self._surveying or attrs is None or dev_id in self._settings_read_back:
            return
        self.settings[dev_id] = {**attrs, "read_at": dt_util.utcnow()}
        self.async_update_listeners()

    async def _async_survey_settings(self, heads: list[Head], stop: threading.Event) -> None:
        """The settings pass, right after a preheat survey so the two never overlap.

        Best-effort: a failure is logged and tried again after the next preheat survey; it never
        fails the preheat survey it follows.
        """
        loop = self.hass.loop
        # Also kept here, from the worker: a callback posted to the loop may run only after the
        # pass has returned (seen on Python 3.14), when ``_async_head_settings`` drops it.
        collected: dict[str, dict[str, Any]] = {}

        def on_result(dev_id: str, attrs: dict[str, Any] | None) -> None:  # worker thread
            if attrs is not None:
                collected[dev_id] = attrs
            loop.call_soon_threadsafe(self._async_head_settings, dev_id, attrs)

        failed = False
        try:
            await self.hass.async_add_executor_job(
                self.manager.survey_settings, heads, on_result, stop
            )
        except Exception as err:  # noqa: BLE001 - best-effort
            _LOGGER.debug("local settings survey failed (%s)", type(err).__name__)
            failed = True
        # What the heads gave is kept even when the pass failed part-way (best-effort).
        # A head read back on its own during the pass (after a write) keeps that fresher read.
        now = dt_util.utcnow()
        for dev_id, attrs in collected.items():
            if dev_id not in self._settings_read_back:
                self.settings[dev_id] = {**attrs, "read_at": now}
        if not failed:
            self._settings_at = time.monotonic()

    @callback
    def _async_head_read(self, dev_id: str, value: bool | None) -> None:
        """Publish ONE head just read by the running survey (called on the event loop)."""
        if not self._surveying or dev_id in self._read_back:
            return
        if (self.data or {}).get(dev_id) == value:
            return  # unchanged (or still unknown): nothing to tell the entities
        data = dict(self.data or {})
        data[dev_id] = value
        self.data = data
        self.async_update_listeners()

    async def _async_update_data(self) -> dict[str, bool | None]:
        heads = self.heads()
        if not heads:
            return {}
        if self._surveying:
            # Never two surveys at once on the gateways (a survey can outlast the scan interval):
            # the running one keeps publishing, this refresh changes nothing.
            return self.data or {}
        loop = self.hass.loop

        def on_result(dev_id: str, value: bool | None) -> None:  # worker thread
            loop.call_soon_threadsafe(self._async_head_read, dev_id, value)

        # Also kept here, from the worker: a callback posted to the loop may run only after the
        # survey has returned and ``_surveying`` is False (seen on Python 3.14), when
        # ``_async_head_attributes`` drops it. The survey's result is merged below, as for preheat.
        collected: dict[str, dict[str, Any] | None] = {}

        def on_attributes(dev_id: str, attrs: dict[str, Any] | None) -> None:  # worker thread
            collected[dev_id] = attrs
            loop.call_soon_threadsafe(self._async_head_attributes, dev_id, attrs)

        stop = threading.Event()
        stop_settings = threading.Event()
        self._read_back = {}
        self._settings_read_back = set()
        self._surveying = True
        try:
            try:
                res = await self.hass.async_add_executor_job(
                    self.manager.survey_preheat, heads, on_result, stop, on_attributes
                )
            except Exception as err:  # noqa: BLE001 - best-effort local fallback
                raise UpdateFailed(f"local survey: {err}") from err
            for dev_id, attrs in collected.items():
                # A head read back on its own meanwhile (after a write) keeps that fresher read.
                if dev_id not in self._read_back:
                    self._store_attributes(dev_id, attrs)
            if self._settings_at is None or (
                time.monotonic() - self._settings_at >= LOCAL_SETTINGS_INTERVAL
            ):
                await self._async_survey_settings(heads, stop_settings)
        finally:
            # Also reached on cancellation (unload / stop): release the gateways.
            stop.set()
            stop_settings.set()
            self._surveying = False
        return {**res, **self._read_back}


class DanfossMessageCoordinator(DataUpdateCoordinator[list[DanfossMessage]]):
    """The app's message center (docs/message-center.md), read on its own slow cadence.

    Kept apart from ``DanfossCoordinator`` so that the device poll keeps its cost and cadence, and
    so that a message-center failure never makes a head unavailable. Read only.

    New messages: the ids seen are remembered; from the second successful read on, each message
    not seen before fires ``EVENT_MESSAGE`` (oldest first). The backlog present at the first read
    fires nothing, so a restart or a reload never replays old alerts. The event carries the HA
    ``device_id`` of the device concerned when it is known, never a Danfoss identifier.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: CloudClient,
        entry_id: str,
        scan_interval: int = MESSAGES_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="danfoss_ally_cloud_messages",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.entry_id = entry_id
        self._seen: set[str] | None = None  # None until the first successful read

    def device_entry(self, source_id: str | None) -> dr.DeviceEntry | None:
        """HA device of a message's source devId (None: no source, or a removed device)."""
        if not source_id:
            return None
        # Local import: device_links imports this module (cycle at import time otherwise).
        from .device_links import find_device

        device: dr.DeviceEntry | None = find_device(
            dr.async_get(self.hass), self.entry_id, source_id
        )
        return device

    def device_name(self, source_id: str | None) -> str | None:
        device = self.device_entry(source_id)
        if device is None:
            return None
        return device.name_by_user or device.name

    async def _async_update_data(self) -> list[DanfossMessage]:
        try:
            messages = await self.client.async_list_messages()
        except CloudError as err:
            # Auth errors included: the device coordinator owns re-authentication (it raises
            # ConfigEntryAuthFailed); here a failed read only makes the message sensor unavailable.
            raise UpdateFailed(str(err)) from err
        ids = {m.message_id for m in messages}
        if self._seen is None:
            self._seen = ids
            return messages
        new = [m for m in messages if m.message_id not in self._seen]
        # Remember the ids still listed plus the new ones; ids dropped by the cloud are forgotten.
        self._seen = ids
        for msg in sorted(new, key=lambda m: m.time):
            self._fire(msg)
        return messages

    @callback
    def _fire(self, msg: DanfossMessage) -> None:
        device = self.device_entry(msg.source_id)
        name = (device.name_by_user or device.name) if device is not None else None
        data = {
            "config_entry_id": self.entry_id,
            "device_id": device.id if device is not None else None,
            **msg.public_dict(name),
        }
        self.hass.bus.async_fire(EVENT_MESSAGE, data)
