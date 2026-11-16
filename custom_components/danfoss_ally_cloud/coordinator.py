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
