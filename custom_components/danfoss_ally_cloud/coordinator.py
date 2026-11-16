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

from .api import CloudAuthError, CloudClient, CloudError, DanfossDevice, etat_tete
from .api.local.manager import Head, LocalTunnelManager

_LOGGER = logging.getLogger(__name__)

# Le programme d'une cible n'est PAS relu à chaque cycle (économie du compte réel) : cache par
# cible, rafraîchi à la demande et au plus une fois par heure, et après chaque écriture.
SCHEDULE_TTL = 3600  # secondes


class DanfossCoordinator(DataUpdateCoordinator[dict[str, DanfossDevice]]):
    """Rassemble l'état du parc (têtes, capteurs) et des pièces (groupes-programme)."""

    def __init__(self, hass: HomeAssistant, client: CloudClient, scan_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="danfoss_ally_cloud",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self.rooms: list[dict] = []  # pièces (forme Room du contrat §3.4)
        self._structure: list[dict] | None = None  # ossature des pièces, mise en cache
        self._schedules: dict[str, tuple[dict, float]] = {}  # cache programme par cible

    async def _async_update_data(self) -> dict[str, DanfossDevice]:
        """Lecture cloud : appareils décodés + pièces (états superposés). Jamais de secret ici."""
        try:
            devices = await self.client.async_list_devices()
            if self._structure is None:
                self._structure = await self.client.async_room_structure()
        except CloudAuthError as err:
            # Identifiants/secrets refusés : déclenche la ré-authentification côté HA.
            raise ConfigEntryAuthFailed(str(err)) from err
        except CloudError as err:
            raise UpdateFailed(str(err)) from err
        by_id = {dev.id: dev for dev in devices}
        self.rooms = self._build_rooms(by_id)
        return by_id

    def _build_rooms(self, devices: dict[str, DanfossDevice]) -> list[dict]:
        """Pièces (contrat §3.4) : ossature en cache + états des têtes du cycle courant (4.3)."""
        rooms: list[dict] = []
        for s in self._structure or []:
            heads: list[dict] = []
            comfort: float | None = None
            setback: float | None = None
            for dev_id in s.get("members", []):
                dev = devices.get(dev_id)
                if dev is None:
                    continue
                heads.append(etat_tete(dev, s["id"]))
                if comfort is None:
                    comfort = dev.consignes.get("confort")
                if setback is None:
                    setback = dev.consignes.get("reduit")
            rooms.append(
                {
                    "id": s["id"],
                    "name": s.get("name"),
                    "home": s.get("home"),
                    "product_id": s.get("product_id"),
                    "heads": heads,
                    "comfort": comfort,
                    "setback": setback,
                }
            )
        return rooms

    @property
    def rooms_by_id(self) -> dict[str, dict]:
        return {r["id"]: r for r in self.rooms}

    @staticmethod
    def _target_key(target: dict) -> str:
        return f"{target.get('type')}:{target.get('id')}"

    async def async_get_schedule(self, target: dict, refresh: bool = False) -> dict:
        """Programme d'une cible : cache (≤ 1 h), ou cloud si `refresh` ou cache périmé."""
        key = self._target_key(target)
        cached = self._schedules.get(key)
        if not refresh and cached is not None and (time.monotonic() - cached[1]) < SCHEDULE_TTL:
            return cached[0]
        schedule = await self.client.async_get_schedule(target)
        self._schedules[key] = (schedule, time.monotonic())
        return schedule

    def invalidate_schedule(self, target: dict) -> None:
        """Oublie le programme en cache d'une cible (relu au prochain accès)."""
        self._schedules.pop(self._target_key(target), None)


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
