"""Embedded frontend: serving the bundle and declaring the Lovelace resource.

Contract §6:
- serves the `frontend/` folder at URL `/danfoss_ally_cloud/frontend/`
  (`async_register_static_paths`);
- declares the Lovelace resource `…/danfoss-ally-cloud.js?v=<version>` for storage-mode
  dashboards, so the card appears in the picker without manual steps (in YAML mode the user adds
  it themselves — see README);
- registration IN `async_setup` (once per instance), never in `async_setup_entry`;
- cleanup of the resource when the last entry is removed.

Serving the file and declaring the resource are "best-effort": they must never prevent the
integration from configuring.

Implementation choice: `frontend`, `http` and `lovelace` are declared as `after_dependencies` (not
`dependencies`) in the manifest. As a hard dependency, Home Assistant would force the full setup of
`frontend` (onboarding → analytics → recorder → `psutil_home_assistant`), which fails in the test
harness and on any install where these dependencies are not present at our configuration time.
`after_dependencies` guarantees the load order in production (where these components are always
there via `default_config`) without imposing them. If one is missing, registration degrades
gracefully (see below).
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

# Lovelace resources collection class (storage mode). Stored in a `type | None`-annotated variable
# rather than reassigning the imported name: lovelace may be absent (minimal HA), and reassigning a
# class name upsets mypy.
try:
    from homeassistant.components.lovelace.resources import ResourceStorageCollection

    _ResourcesCls: type | None = ResourceStorageCollection
except ImportError:  # lovelace absent
    _ResourcesCls = None

# Custom-panel helper (sidebar, contract §8.2). May be absent on a minimal HA: best-effort.
try:
    from homeassistant.components import panel_custom
except ImportError:  # panel_custom absent
    panel_custom = None

_LOGGER = logging.getLogger(__name__)

# Public URL of the served folder, and the bundle name (versioned in the repo).
FRONTEND_URL_BASE = f"/{DOMAIN}/frontend"
JS_FILENAME = "danfoss-ally-cloud.js"
FRONTEND_DIR = Path(__file__).parent / "frontend"

# Side panel (contract §8.2): sidebar entry backed by the <danfoss-ally-panel> web component of the
# same bundle. Read-first, so no admin requirement.
PANEL_URL_PATH = "danfoss-ally-cloud"
PANEL_COMPONENT = "danfoss-ally-panel"
PANEL_TITLE = "Danfoss Ally"
PANEL_ICON = "mdi:radiator"

# Flag in hass.data: static path already registered for this instance.
_DATA_STATIC_REGISTERED = f"{DOMAIN}_frontend_static"
# Flag in hass.data: the side panel is registered for this instance.
_DATA_PANEL_REGISTERED = f"{DOMAIN}_frontend_panel"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the bundle, declare the Lovelace resource and the side panel (async_setup)."""
    await _async_register_static_path(hass)
    url = await _async_resource_url(hass)
    await _async_register_resource(hass, url)
    await _async_register_panel(hass, url)


async def async_unregister_frontend(hass: HomeAssistant) -> None:
    """Remove the Lovelace resource and the side panel (when the last entry is removed).

    The static path is not removed: Home Assistant offers no way to unregister it, and it is
    harmless (it disappears on the next restart).
    """
    url = await _async_resource_url(hass)
    await _async_remove_resource(hass, url)
    _async_remove_panel(hass)


async def _async_register_panel(hass: HomeAssistant, module_url: str) -> None:
    """Register the sidebar panel, once per instance. Best-effort: never blocks setup."""
    if hass.data.get(_DATA_PANEL_REGISTERED) or panel_custom is None:
        return
    try:
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name=PANEL_COMPONENT,
            module_url=module_url,
            sidebar_title=PANEL_TITLE,
            sidebar_icon=PANEL_ICON,
            require_admin=False,
            embed_iframe=False,
        )
    except Exception as err:  # noqa: BLE001 - best-effort, must not block setup
        _LOGGER.warning("Could not register the Danfoss Ally panel: %s", err)
        return
    hass.data[_DATA_PANEL_REGISTERED] = True


def _async_remove_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel (cleanup). Best-effort."""
    if not hass.data.get(_DATA_PANEL_REGISTERED):
        return
    try:
        from homeassistant.components import frontend as ha_frontend

        ha_frontend.async_remove_panel(hass, PANEL_URL_PATH)
    except Exception as err:  # noqa: BLE001 - best-effort
        _LOGGER.debug("Could not remove the Danfoss Ally panel: %s", err)
    hass.data[_DATA_PANEL_REGISTERED] = False


async def _async_resource_url(hass: HomeAssistant) -> str:
    """Resource URL with the integration version (cache-busting, contract §6)."""
    version = "0"
    try:
        integration = await async_get_integration(hass, DOMAIN)
        version = str(integration.version)
    except Exception as err:  # noqa: BLE001 - the version is not vital
        _LOGGER.debug("Integration version not found: %s", err)
    return f"{FRONTEND_URL_BASE}/{JS_FILENAME}?v={version}"


async def _async_register_static_path(hass: HomeAssistant) -> None:
    """Register the static folder, once per instance."""
    if hass.data.get(_DATA_STATIC_REGISTERED):
        return
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL_BASE, str(FRONTEND_DIR), cache_headers=False)]
        )
    except Exception as err:  # noqa: BLE001 - best-effort, does not block setup
        _LOGGER.warning("Could not serve the frontend folder: %s", err)
        return
    hass.data[_DATA_STATIC_REGISTERED] = True


def _resources_collection(hass: HomeAssistant):
    """Storage-mode Lovelace resources collection, or None.

    In YAML mode (or if lovelace is not loaded), returns None: the resource must then be added by
    hand (documented in the README).
    """
    if _ResourcesCls is None:
        return None
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if not isinstance(resources, _ResourcesCls):
        return None
    return resources


async def _async_register_resource(hass: HomeAssistant, url: str) -> None:
    """Create (or update) the module resource pointing to the bundle."""
    resources = _resources_collection(hass)
    if resources is None:
        _LOGGER.debug("Lovelace resources in YAML mode or unavailable: manual add required.")
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
        _LOGGER.warning("Could not declare the Lovelace resource: %s", err)


async def _async_remove_resource(hass: HomeAssistant, url: str) -> None:
    """Delete the module resource (cleanup)."""
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
        _LOGGER.debug("Could not remove the Lovelace resource: %s", err)
