"""Intégration Danfoss Ally (Cloud).

Point d'entrée : met en place le client cloud (API cloud voie 1a), le
coordinateur de rafraîchissement, et — si demandé — le tunnel local et le
publicateur MQTT. Cloud-first ; repli local pour les opérations que le cloud
rate (voir docs/architecture.md).
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configurer une entrée (un compte Danfoss Ally)."""
    # TODO:
    #  1. Construire le client API cloud (api.client.CloudClient) depuis
    #     entry.data (identifiants/région), restaurer la session si possible.
    #  2. Créer le DanfossCoordinator (coordinator.py) et faire un premier
    #     refresh (await coordinator.async_config_entry_first_refresh()).
    #  3. Si options[enable_local] : préparer le tunnel local
    #     (récupérer les clés passerelles via api.keys, instancier le tunnel).
    #  4. Si options[mqtt_mode] != "off" : démarrer le MqttPublisher.
    #  5. Stocker le tout dans hass.data[DOMAIN][entry.entry_id].
    hass.data.setdefault(DOMAIN, {})
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharger une entrée (fermer session, tunnel, publicateur MQTT)."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recharger l'entrée quand les options changent (MQTT, local, intervalle)."""
    await hass.config_entries.async_reload(entry.entry_id)
