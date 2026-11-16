"""Coordinateur de rafraîchissement.

Interroge le cloud (API cloud) à intervalle conservateur, normalise les
appareils en un modèle commun, et — quand le tunnel local est actif — corrige
les champs que le cloud remonte faux (ex. pré-chauffage réel 0x0025).
"""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class DanfossCoordinator(DataUpdateCoordinator[dict]):
    """Rassemble l'état du parc (têtes, passerelles, capteurs)."""

    def __init__(self, hass: HomeAssistant, client, scan_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="danfoss_ally_cloud",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._client = client

    async def _async_update_data(self) -> dict:
        # TODO:
        #  1. await self._client.devices() -> liste brute (DP).
        #  2. Normaliser en {device_id: DanfossDevice} (modeles communs).
        #  3. Si tunnel local actif : relire les vérités locales nécessaires
        #     (programme, 0x0025) et les superposer.
        #  Ne jamais logguer de clé ni de jeton ici.
        return {}
