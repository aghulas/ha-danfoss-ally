"""Tests de l'interface embarquée : service du bundle et ressource Lovelace (contrat §6).

On construit directement une `ResourceStorageCollection` (sans mettre en place le
composant `frontend`/`lovelace` complet, trop lourd pour le harnais) : on teste
ainsi notre logique d'enregistrement / mise à jour / nettoyage sur une vraie
collection de ressources.
"""

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
    # Version du manifest injectée (cache-busting, contrat §6).
    assert url.endswith("?v=0.1.0")


async def test_collection_absente_hors_lovelace(hass: HomeAssistant):
    # Lovelace non chargé : pas de collection -> ajout manuel (mode YAML documenté).
    assert _resources_collection(hass) is None
    # Ne lève pas : service du dossier best-effort, ressource ignorée proprement.
    await async_register_frontend(hass)
    await async_unregister_frontend(hass)


async def test_import_lovelace_indisponible(hass: HomeAssistant, monkeypatch):
    # HA minimal sans lovelace : le garde-fou renvoie None.
    monkeypatch.setattr(frontend, "_ResourcesCls", None)
    await _install_fake_lovelace(hass)  # présent, mais classe indisponible
    assert _resources_collection(hass) is None


async def test_enregistrement_idempotent_et_mise_a_jour(hass: HomeAssistant):
    resources = await _install_fake_lovelace(hass)

    # Une ressource obsolète préexistante (ancienne version) doit être mise à jour.
    await _async_register_resource(hass, f"{RES_BASE}?v=0.0.1")
    assert _module_urls(resources) == [f"{RES_BASE}?v=0.0.1"]

    await async_register_frontend(hass)
    assert _module_urls(resources) == [f"{RES_BASE}?v=0.1.0"]  # une seule, à jour

    # Idempotent : un second enregistrement ne duplique pas.
    await async_register_frontend(hass)
    assert _module_urls(resources) == [f"{RES_BASE}?v=0.1.0"]

    # Nettoyage : la ressource disparaît.
    await async_unregister_frontend(hass)
    assert _module_urls(resources) == []
    # Nettoyage d'une ressource déjà absente : sans effet.
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
    assert urls_apres == ["/autre/carte.js"]  # on n'a retiré QUE la nôtre
    assert autre["id"]  # (sanity) l'item tiers existait bien
