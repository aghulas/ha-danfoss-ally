"""Coordinateur de rafraîchissement.

Interroge le cloud (API cloud voie 1a) à intervalle conservateur et normalise les appareils en
``{device_id: DanfossDevice}``. Le tunnel local (v0.3) corrigera plus tard les champs que le cloud
remonte faux (ex. pré-chauffage réel 0x0025) ; ici, lecture cloud seule.
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
from .api.rooms import Piece, RoomState, aggregate_room

_LOGGER = logging.getLogger(__name__)

# La topologie des pièces (groupes Tuya + membres) change rarement : on la met en cache et on ne la
# re-télécharge qu'au bout de cet intervalle (ou au reload), pour rester conservateur sur le quota.
_TOPOLOGY_TTL = 3600  # secondes


class DanfossCoordinator(DataUpdateCoordinator[dict[str, DanfossDevice]]):
    """Rassemble l'état du parc : têtes (``data``) + pièces agrégées (``rooms``)."""

    def __init__(self, hass: HomeAssistant, client: CloudClient, scan_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="danfoss_ally_cloud",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        # Pièces agrégées (group_id -> RoomState) et appartenance tête -> pièce, recalculées à
        # chaque refresh à partir de la topologie en cache et de l'état courant des têtes.
        self.rooms: dict[str, RoomState] = {}
        self.grouped_ids: set[str] = set()
        self._pieces: dict[str, Piece] = {}
        self._group_of: dict[str, str] = {}
        self._topology_ts: float = 0.0

    async def _async_update_data(self) -> dict[str, DanfossDevice]:
        """Lecture cloud : têtes décodées (indexées par id) + agrégation par pièce. Aucun secret."""
        try:
            devices = await self.client.async_list_devices()
        except CloudAuthError as err:
            # Identifiants/secrets refusés : déclenche la ré-authentification côté HA.
            raise ConfigEntryAuthFailed(str(err)) from err
        except CloudError as err:
            raise UpdateFailed(str(err)) from err
        data = {dev.id: dev for dev in devices}
        await self._ensure_topology()
        self.rooms = {
            gid: aggregate_room(piece, membres)
            for gid, piece in self._pieces.items()
            if (membres := [data[m] for m in piece.membres if m in data])
        }
        self.grouped_ids = {head_id for head_id in self._group_of if head_id in data}
        return data

    def group_of(self, head_id: str) -> str | None:
        """Group_id de la pièce d'une tête, ou None si la tête n'est pas groupée."""
        return self._group_of.get(head_id)

    async def _ensure_topology(self) -> None:
        """Rafraîchit la topologie des pièces si le cache a expiré. Best-effort : ne bloque jamais.

        En cas d'échec de lecture : on conserve le cache précédent s'il existe, sinon topologie
        vide (toutes les têtes traitées comme isolées — thermostat en lecture seule).
        """
        now = time.monotonic()
        if self._pieces and (now - self._topology_ts) < _TOPOLOGY_TTL:
            return
        try:
            pieces, group_of = await self._fetch_topology()
        except CloudError as err:
            if self._pieces:
                _LOGGER.debug("topologie des pièces conservée (lecture échouée : %s)", err)
                return
            _LOGGER.warning(
                "topologie des pièces indisponible (%s) : têtes traitées isolément", err
            )
            self._pieces, self._group_of, self._topology_ts = {}, {}, now
            return
        self._pieces, self._group_of, self._topology_ts = pieces, group_of, now

    async def _fetch_topology(self) -> tuple[dict[str, Piece], dict[str, str]]:
        """Lit les pièces (groupes) et leurs membres de chaque maison (voie 1a)."""
        pieces: dict[str, Piece] = {}
        group_of: dict[str, str] = {}
        for home in await self.client.async_get_homes():
            gid = home["gid"]
            groups = await self.client.async_list_groups(gid)
            members = await self.client.async_group_members(gid)
            for g in groups:
                gid_s = str(g["group_id"])
                membres = tuple(members.get(gid_s, ()))
                if not membres:
                    continue
                pieces[gid_s] = Piece(gid_s, g.get("nom") or gid_s, g.get("pid"), str(gid), membres)
                for devid in membres:
                    group_of[devid] = gid_s
        return pieces, group_of


class DanfossLocalCoordinator(DataUpdateCoordinator[dict[str, bool | None]]):
    """Relevé LOCAL (tunnel Zigbee) du pré-chauffage réel (0x0025), indexé par id de tête.

    Lent et best-effort : il corrige ce que le cloud remonte faux (DP 1 cloud ne touche que le cache
    passerelle). S'appuie sur le coordinateur cloud pour connaître les têtes et leur passerelle.
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
        """Têtes joignables par le tunnel (node_id + passerelle connus du manager)."""
        gws = self.manager.gateway_ids
        return [
            Head(d.id, d.node_id, d.mesh_id)
            for d in self._cloud.data.values()
            if d.est_tete and d.node_id and d.mesh_id and d.mesh_id in gws
        ]

    async def _async_update_data(self) -> dict[str, bool | None]:
        heads = self.heads()
        if not heads:
            return {}
        try:
            return await self.hass.async_add_executor_job(self.manager.relever_prechauffage, heads)
        except Exception as err:  # noqa: BLE001 - repli local best-effort
            raise UpdateFailed(f"relevé local : {err}") from err
