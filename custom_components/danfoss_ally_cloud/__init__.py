"""Intégration Danfoss Ally (Cloud).

Point d'entrée : met en place le client cloud (API cloud voie 1a), le coordinateur de
rafraîchissement, et — à terme — le tunnel local et le publicateur MQTT. Cloud-first ; repli
local pour les opérations que le cloud rate (voir docs/architecture.md). v0.1 : lecture cloud seule.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .api import CloudClient, async_fetch_gateway_keys
from .api.local.manager import LocalTunnelManager
from .const import (
    CONF_CH_KEY,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_ID,
    CONF_ENABLE_LOCAL,
    CONF_MQTT_BASE_TOPIC,
    CONF_MQTT_MODE,
    CONF_MQTT_SOURCE,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_SIGN_KEY,
    CONF_USERNAME,
    DATA_COORDINATOR,
    DATA_LOCAL,
    DATA_MQTT,
    DEFAULT_LOCAL_SCAN_INTERVAL,
    DEFAULT_MQTT_BASE_TOPIC,
    DEFAULT_MQTT_MODE,
    DEFAULT_MQTT_SOURCE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator
from .frontend import async_register_frontend, async_unregister_frontend
from .mqtt_publisher import MqttPublisher

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Mise en place à l'échelle de l'intégration (une fois par instance).

    Sert l'interface embarquée et déclare sa ressource Lovelace ici — jamais dans
    `async_setup_entry` (contrat §6). Best-effort : n'empêche pas le démarrage.
    """
    await async_register_frontend(hass)
    return True


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

    # Publication MQTT (optionnelle).
    publisher = await _async_setup_mqtt(hass, entry, coordinator)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_COORDINATOR: coordinator,
        DATA_LOCAL: local_coordinator,
        DATA_MQTT: publisher,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    return True


async def _async_setup_mqtt(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: DanfossCoordinator
) -> MqttPublisher | None:
    """Démarre le publicateur MQTT si mqtt_mode != off. Best-effort (broker absent → no-op)."""
    mode = entry.options.get(CONF_MQTT_MODE, DEFAULT_MQTT_MODE)
    if mode == "off":
        return None
    publisher = MqttPublisher(
        hass,
        coordinator,
        mode,
        entry.options.get(CONF_MQTT_SOURCE, DEFAULT_MQTT_SOURCE),
        entry.options.get(CONF_MQTT_BASE_TOPIC, DEFAULT_MQTT_BASE_TOPIC),
    )
    await publisher.async_start()
    return publisher


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
            publisher: MqttPublisher | None = data.get(DATA_MQTT)
            if publisher is not None:
                await publisher.async_stop()
            coordinator: DanfossCoordinator = data[DATA_COORDINATOR]
            await coordinator.client.async_close()
    return unloaded


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recharger l'entrée quand les options changent (MQTT, local, intervalle)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Au retrait de la DERNIÈRE entrée : nettoyer la ressource Lovelace (contrat §6).

    On ne nettoie pas au simple déchargement/rechargement (qui appelle seulement
    `async_unload_entry`), mais seulement quand plus aucune entrée ne subsiste.
    """
    if not hass.config_entries.async_entries(DOMAIN):
        await async_unregister_frontend(hass)
