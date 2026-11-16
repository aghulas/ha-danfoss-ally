"""Coordinateur de rafraîchissement.

Interroge le cloud (API cloud voie 1a) à intervalle conservateur et normalise les appareils en
``{device_id: DanfossDevice}``. Le tunnel local (v0.3) corrigera plus tard les champs que le cloud
remonte faux (ex. pré-chauffage réel 0x0025) ; ici, lecture cloud seule.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CloudAuthError, CloudClient, CloudError, DanfossDevice
from .api.local.manager import Head, LocalTunnelManager

_LOGGER = logging.getLogger(__name__)


class DanfossCoordinator(DataUpdateCoordinator[dict[str, DanfossDevice]]):
    """Rassemble l'état du parc (têtes, capteurs)."""

    def __init__(self, hass: HomeAssistant, client: CloudClient, scan_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="danfoss_ally_cloud",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, DanfossDevice]:
        """Lecture cloud : liste des appareils décodés, indexés par id. Jamais de secret ici."""
        try:
            devices = await self.client.async_list_devices()
        except CloudAuthError as err:
            # Identifiants/secrets refusés : déclenche la ré-authentification côté HA.
            raise ConfigEntryAuthFailed(str(err)) from err
        except CloudError as err:
            raise UpdateFailed(str(err)) from err
        return {dev.id: dev for dev in devices}


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
