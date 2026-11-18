"""Embedded frontend tests: bundle serving and Lovelace resource (contract §6).

On construit directement une `ResourceStorageCollection` (sans mettre en place le
composant `frontend`/`lovelace` complet, trop lourd pour le harnais) : on teste
so our registration / update / cleanup logic against a real
collection de ressources.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.core import HomeAssistant

import custom_components.danfoss_ally_cloud.frontend as frontend
from custom_components.danfoss_ally_cloud.frontend import (
    FRONTEND_URL_BASE,
    JS_FILENAME,
    _async_register_resource,
    _async_resource_url,
    _resources_collection,
    async_register_frontend,
    async_unregister_frontend,
)

RES_BASE = f"{FRONTEND_URL_BASE}/{JS_FILENAME}"
# Version attendue = celle du manifest (le code l'injecte pour le cache-busting) : lue ici pour que
# the test does not break on every version bump.
VERSION = json.loads((Path(frontend.__file__).parent / "manifest.json").read_text())["version"]


class _FakeLovelaceConfig:
    """Config Lovelace minimale : une collection de ressources vide en mode stockage."""

    mode = "storage"

    async def async_load(self, force):  # noqa: ARG002 - signature attendue par HA
        return {}


async def _install_fake_lovelace(hass: HomeAssistant) -> ResourceStorageCollection:
    coll = ResourceStorageCollection(hass, _FakeLovelaceConfig())
    hass.data["lovelace"] = SimpleNamespace(resources=coll)
    return coll


def _module_urls(resources: ResourceStorageCollection) -> list[str]:
    return [
        str(item["url"])
        for item in resources.async_items()
        if str(item["url"]).split("?")[0] == RES_BASE
    ]


async def test_resource_url_contient_la_version(hass: HomeAssistant):
    url = await _async_resource_url(hass)
    assert url.startswith(f"{RES_BASE}?v=")
    # Manifest version injected (cache-busting, contract §6).
    assert url.endswith(f"?v={VERSION}")


async def test_collection_absent_without_lovelace(hass: HomeAssistant):
    # Lovelace not loaded: no collection -> manual add (documented YAML mode).
    assert _resources_collection(hass) is None
    # Does not raise: best-effort folder serving, resource skipped cleanly.
    await async_register_frontend(hass)
    await async_unregister_frontend(hass)


async def test_import_lovelace_indisponible(hass: HomeAssistant, monkeypatch):
    # HA minimal sans lovelace : le garde-fou renvoie None.
    monkeypatch.setattr(frontend, "_ResourcesCls", None)
    await _install_fake_lovelace(hass)  # present, but class unavailable
    assert _resources_collection(hass) is None


async def test_registration_idempotent_and_update(hass: HomeAssistant):
    resources = await _install_fake_lovelace(hass)

    # A pre-existing stale resource (old version) must be updated.
    await _async_register_resource(hass, f"{RES_BASE}?v=0.0.1")
    assert _module_urls(resources) == [f"{RES_BASE}?v=0.0.1"]

    await async_register_frontend(hass)
    assert _module_urls(resources) == [f"{RES_BASE}?v={VERSION}"]  # a single one, up to date

    # Idempotent : un second enregistrement ne duplique pas.
    await async_register_frontend(hass)
    assert _module_urls(resources) == [f"{RES_BASE}?v={VERSION}"]

    # Cleanup: the resource disappears.
    await async_unregister_frontend(hass)
    assert _module_urls(resources) == []
    # Cleanup of an already-absent resource: no effect.
    await async_unregister_frontend(hass)
    assert _module_urls(resources) == []


async def test_register_conserve_les_autres_ressources(hass: HomeAssistant):
    resources = await _install_fake_lovelace(hass)
    await resources.async_load()
    resources.loaded = True
    autre = await resources.async_create_item({"res_type": "module", "url": "/autre/carte.js"})

    await async_register_frontend(hass)
    urls = [str(i["url"]) for i in resources.async_items()]
    assert "/autre/carte.js" in urls  # ressource tierce intacte
    assert any(u.startswith(f"{RES_BASE}?v=") for u in urls)

    await async_unregister_frontend(hass)
    urls_apres = [str(i["url"]) for i in resources.async_items()]
    assert urls_apres == ["/autre/carte.js"]  # we removed ONLY ours
    assert autre["id"]  # (sanity) l'item tiers existait bien


# --- D4: side panel registration (contract §8.2) ----------------------------------------------


class _FakePanelCustom:
    def __init__(self):
        self.calls: list[dict] = []

    async def async_register_panel(self, hass, **kwargs):  # noqa: ARG002 - signature HA
        self.calls.append(kwargs)


async def test_panel_registration_idempotent(hass: HomeAssistant, monkeypatch):
    fake = _FakePanelCustom()
    monkeypatch.setattr(frontend, "panel_custom", fake)

    await frontend._async_register_panel(hass, f"{RES_BASE}?v={VERSION}")
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["frontend_url_path"] == frontend.PANEL_URL_PATH
    assert call["webcomponent_name"] == frontend.PANEL_COMPONENT
    assert call["module_url"] == f"{RES_BASE}?v={VERSION}"
    assert call["require_admin"] is False
    assert hass.data[frontend._DATA_PANEL_REGISTERED] is True

    # A second registration does not duplicate the panel.
    await frontend._async_register_panel(hass, f"{RES_BASE}?v={VERSION}")
    assert len(fake.calls) == 1


async def test_panel_registration_absent_panel_custom(hass: HomeAssistant, monkeypatch):
    # panel_custom unavailable (minimal HA): degrade cleanly, no flag, no raise.
    monkeypatch.setattr(frontend, "panel_custom", None)
    await frontend._async_register_panel(hass, f"{RES_BASE}?v={VERSION}")
    assert hass.data.get(frontend._DATA_PANEL_REGISTERED) is None


async def test_panel_registration_error_is_swallowed(hass: HomeAssistant, monkeypatch):
    class _Boom:
        async def async_register_panel(self, hass, **kwargs):  # noqa: ARG002
            raise ValueError("already registered")

    monkeypatch.setattr(frontend, "panel_custom", _Boom())
    # Best-effort: must not block setup.
    await frontend._async_register_panel(hass, f"{RES_BASE}?v={VERSION}")
    assert hass.data.get(frontend._DATA_PANEL_REGISTERED) is None


async def test_panel_removal(hass: HomeAssistant, monkeypatch):
    import homeassistant.components.frontend as ha_frontend

    removed: list[str] = []
    monkeypatch.setattr(ha_frontend, "async_remove_panel", lambda hass, path: removed.append(path))

    hass.data[frontend._DATA_PANEL_REGISTERED] = True
    frontend._async_remove_panel(hass)
    assert removed == [frontend.PANEL_URL_PATH]
    assert hass.data[frontend._DATA_PANEL_REGISTERED] is False

    # Removing when not registered is a no-op.
    frontend._async_remove_panel(hass)
    assert removed == [frontend.PANEL_URL_PATH]
