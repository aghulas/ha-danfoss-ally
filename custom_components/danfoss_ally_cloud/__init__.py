"""Intégration Danfoss Ally (Cloud).

Point d'entrée : met en place le client cloud (API cloud voie 1a), le coordinateur de
rafraîchissement, et — à terme — le tunnel local et le publicateur MQTT. Cloud-first ; repli
local pour les opérations que le cloud rate (voir docs/architecture.md). v0.1 : lecture cloud seule.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import CloudClient, async_fetch_gateway_keys
from .api.local.manager import LocalTunnelManager
from .const import (
    CONF_CH_KEY,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_ID,
    CONF_ENABLE_LOCAL,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_SIGN_KEY,
    CONF_USERNAME,
    DATA_COORDINATOR,
    DATA_LOCAL,
    DEFAULT_LOCAL_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator

_LOGGER = logging.getLogger(__name__)


def _client_from_entry(entry: ConfigEntry) -> CloudClient:
    data = entry.data
    return CloudClient(
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        country_code=data[CONF_COUNTRY_CODE],
        sign_key=data[CONF_SIGN_KEY],
        device_id=data[CONF_DEVICE_ID],
        ch_key=data[CONF_CH_KEY],
        region=data.get(CONF_REGION, "eu"),
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configurer une entrée (un compte Danfoss Ally)."""
    client = _client_from_entry(entry)
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = DanfossCoordinator(hass, client, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    # Repli local (optionnel) : best-effort, ne doit jamais empêcher le cloud de démarrer.
    local_coordinator = await _async_setup_local(hass, entry, coordinator)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_COORDINATOR: coordinator,
        DATA_LOCAL: local_coordinator,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    return True


async def _async_setup_local(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: DanfossCoordinator
) -> DanfossLocalCoordinator | None:
    """Prépare le tunnel local si l'option est active. Best-effort : renvoie None en cas d'échec."""
    if not entry.options.get(CONF_ENABLE_LOCAL):
        return None
    try:
        gateways = await async_fetch_gateway_keys(coordinator.client)
    except Exception as err:  # noqa: BLE001 - le repli local ne bloque jamais le cloud
        _LOGGER.warning("Repli local indisponible (récupération des clés) : %s", err)
        return None
    if not gateways:
        _LOGGER.warning("Repli local activé mais aucune passerelle avec clé locale trouvée.")
        return None
    manager = LocalTunnelManager(gateways)
    local = DanfossLocalCoordinator(hass, manager, coordinator, DEFAULT_LOCAL_SCAN_INTERVAL)
    # Premier relevé non bloquant : une passerelle injoignable ne doit pas empêcher le démarrage.
    await local.async_refresh()
    return local


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharger une entrée (fermer session, tunnel, publicateur MQTT)."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data:
            coordinator: DanfossCoordinator = data[DATA_COORDINATOR]
            await coordinator.client.async_close()
    return unloaded


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recharger l'entrée quand les options changent (MQTT, local, intervalle)."""
    await hass.config_entries.async_reload(entry.entry_id)
