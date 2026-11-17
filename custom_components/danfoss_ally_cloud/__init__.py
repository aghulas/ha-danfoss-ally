"""Intégration Danfoss Ally (Cloud).

Point d'entrée : met en place le client cloud (API cloud voie 1a), le coordinateur de
rafraîchissement, et — à terme — le tunnel local et le publicateur MQTT. Cloud-first ; repli
local pour les opérations que le cloud rate (voir docs/architecture.md). v0.1 : lecture cloud seule.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
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
    DATA_JOBS,
    DATA_LOCAL,
    DATA_MQTT,
    DATA_SCHEDULES,
    DEFAULT_LOCAL_SCAN_INTERVAL,
    DEFAULT_MQTT_BASE_TOPIC,
    DEFAULT_MQTT_MODE,
    DEFAULT_MQTT_SOURCE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import DanfossCoordinator, DanfossLocalCoordinator
from .mqtt_publisher import MqttPublisher
from .services import async_register_services
from .websocket_api import async_register as async_register_ws
from .writejob import JobManager

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Enregistre les actions et les commandes WebSocket (une fois par instance)."""
    async_register_services(hass)
    async_register_ws(hass)
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
        DATA_JOBS: JobManager(),
        DATA_SCHEDULES: {},
    }
    _cleanup_orphaned_head_climates(hass, entry, coordinator)
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


def _cleanup_orphaned_head_climates(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: DanfossCoordinator
) -> None:
    """Retire les anciens climate PAR TÊTE désormais remplacés par le climate de PIÈCE.

    Conservateur : ne supprime QUE des entités ``climate`` de CETTE entrée dont l'unique_id est l'id
    d'une tête maintenant groupée (ancien modèle « un climate par tête »). Les têtes isolées gardent
    leur climate (lecture seule), et rien d'autre n'est touché — mieux vaut laisser une entité
    orpheline que supprimer de travers une entité personnalisée par l'utilisateur.
    """
    registry = er.async_get(hass)
    for head_id in coordinator.grouped_ids:
        ent_id = registry.async_get_entity_id("climate", DOMAIN, head_id)
        if ent_id is None:
            continue
        entity = registry.async_get(ent_id)
        if entity is not None and entity.config_entry_id == entry.entry_id:
            _LOGGER.debug("Retrait de l'ancien climate par tête %s (pièce %s)", ent_id, head_id)
            registry.async_remove(ent_id)


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recharger l'entrée quand les options changent (MQTT, local, intervalle)."""
    await hass.config_entries.async_reload(entry.entry_id)
