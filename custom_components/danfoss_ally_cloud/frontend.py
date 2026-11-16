"""Interface embarquée : service du bundle et déclaration de la ressource Lovelace.

Contrat §6 :
- sert le dossier `frontend/` à l'URL `/danfoss_ally_cloud/frontend/`
  (`async_register_static_paths`) ;
- déclare la ressource Lovelace `…/danfoss-ally-cloud.js?v=<version>` pour les
  tableaux de bord en mode stockage, afin que la carte apparaisse dans le
  sélecteur sans manipulation manuelle (en mode YAML, l'utilisateur l'ajoute
  lui-même — voir README) ;
- enregistrement DANS `async_setup` (une fois par instance), jamais dans
  `async_setup_entry` ;
- nettoyage de la ressource au retrait de la dernière entrée.

Le service du fichier et la déclaration de la ressource sont « best-effort » :
ils ne doivent jamais empêcher l'intégration de se configurer.

Choix d'implémentation : `frontend`, `http` et `lovelace` sont déclarés en
`after_dependencies` (et non en `dependencies`) dans le manifest. En dépendance
dure, Home Assistant forcerait la mise en place complète de `frontend`
(onboarding → analytics → recorder → `psutil_home_assistant`), ce qui échoue dans
le harnais de test et sur toute installation où ces dépendances ne sont pas
présentes au moment de notre configuration. `after_dependencies` garantit l'ordre
de chargement en production (où ces composants sont toujours là via
`default_config`) sans les imposer. Si l'un manque, l'enregistrement se dégrade
proprement (voir ci-dessous).
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

try:
    from homeassistant.components.lovelace.resources import ResourceStorageCollection
except Exception:  # noqa: BLE001 - lovelace peut être absent (HA minimal)
    ResourceStorageCollection = None

_LOGGER = logging.getLogger(__name__)

# URL publique du dossier servi, et nom du bundle (versionné dans le dépôt).
FRONTEND_URL_BASE = f"/{DOMAIN}/frontend"
JS_FILENAME = "danfoss-ally-cloud.js"
FRONTEND_DIR = Path(__file__).parent / "frontend"

# Drapeau dans hass.data : chemin statique déjà enregistré pour cette instance.
_DATA_STATIC_REGISTERED = f"{DOMAIN}_frontend_static"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Servir le bundle et déclarer la ressource Lovelace. À appeler dans async_setup."""
    await _async_register_static_path(hass)
    url = await _async_resource_url(hass)
    await _async_register_resource(hass, url)


async def async_unregister_frontend(hass: HomeAssistant) -> None:
    """Retirer la ressource Lovelace (au retrait de la dernière entrée).

    Le chemin statique n'est pas retiré : Home Assistant ne propose pas de le
    désenregistrer, et il est inoffensif (il disparaît au prochain redémarrage).
    """
    url = await _async_resource_url(hass)
    await _async_remove_resource(hass, url)


async def _async_resource_url(hass: HomeAssistant) -> str:
    """URL de la ressource avec la version de l'intégration (cache-busting, contrat §6)."""
    version = "0"
    try:
        integration = await async_get_integration(hass, DOMAIN)
        version = str(integration.version)
    except Exception as err:  # noqa: BLE001 - la version n'est pas vitale
        _LOGGER.debug("Version de l'intégration introuvable : %s", err)
    return f"{FRONTEND_URL_BASE}/{JS_FILENAME}?v={version}"


async def _async_register_static_path(hass: HomeAssistant) -> None:
    """Enregistrer le dossier statique, une seule fois par instance."""
    if hass.data.get(_DATA_STATIC_REGISTERED):
        return
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL_BASE, str(FRONTEND_DIR), cache_headers=False)]
        )
    except Exception as err:  # noqa: BLE001 - best-effort, ne bloque pas le setup
        _LOGGER.warning("Service du dossier de l'interface impossible : %s", err)
        return
    hass.data[_DATA_STATIC_REGISTERED] = True


def _resources_collection(hass: HomeAssistant):
    """Collection de ressources Lovelace en mode stockage, ou None.

    En mode YAML (ou si lovelace n'est pas chargé), renvoie None : la ressource
    doit alors être ajoutée à la main (documenté dans le README).
    """
    if ResourceStorageCollection is None:
        return None
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if not isinstance(resources, ResourceStorageCollection):
        return None
    return resources


async def _async_register_resource(hass: HomeAssistant, url: str) -> None:
    """Créer (ou mettre à jour) la ressource module pointant sur le bundle."""
    resources = _resources_collection(hass)
    if resources is None:
        _LOGGER.debug("Ressources Lovelace en mode YAML ou indisponibles : ajout manuel requis.")
        return
    try:
        if not getattr(resources, "loaded", False):
            await resources.async_load()
            resources.loaded = True

        base = url.split("?")[0]
        for item in resources.async_items():
            if str(item.get("url", "")).split("?")[0] == base:
                if item.get("url") != url:
                    await resources.async_update_item(item["id"], {"url": url})
                return
        await resources.async_create_item({"res_type": "module", "url": url})
    except Exception as err:  # noqa: BLE001 - best-effort
        _LOGGER.warning("Déclaration de la ressource Lovelace impossible : %s", err)


async def _async_remove_resource(hass: HomeAssistant, url: str) -> None:
    """Supprimer la ressource module (nettoyage)."""
    resources = _resources_collection(hass)
    if resources is None:
        return
    try:
        if not getattr(resources, "loaded", False):
            await resources.async_load()
            resources.loaded = True

        base = url.split("?")[0]
        for item in resources.async_items():
            if str(item.get("url", "")).split("?")[0] == base:
                await resources.async_delete_item(item["id"])
                return
    except Exception as err:  # noqa: BLE001 - best-effort
        _LOGGER.debug("Suppression de la ressource Lovelace impossible : %s", err)
