"""Tests du coordinateur local (relevé pré-chauffage), manager doublé, harnais hass."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.danfoss_ally_cloud.coordinator import (
    DanfossCoordinator,
    DanfossLocalCoordinator,
)

from .common import FakeCloudClient, tete


class FakeManager:
    """Doublure de LocalTunnelManager : une passerelle gw-1, relevé/écriture contrôlés."""

    def __init__(self, releve=None, releve_exc=None):
        self._releve = releve or {}
        self._exc = releve_exc
        self.ecrits: list = []

    @property
    def gateway_ids(self):
        return {"gw-1"}

    def relever_prechauffage(self, heads):
        if self._exc is not None:
            raise self._exc
        return {h.dev_id: self._releve.get(h.dev_id, True) for h in heads}

    def ecrire_prechauffage(self, head, actif):
        self.ecrits.append((head.dev_id, actif))
        return True


def _cloud(hass, data):
    coord = DanfossCoordinator(hass, FakeCloudClient(), 90)
    coord.data = data
    return coord


async def test_heads_filtre_sur_passerelle(hass: HomeAssistant):
    cloud = _cloud(
        hass,
        {
            "dev-1": tete("dev-1", mesh_id="gw-1", node_id="node-1"),
            "dev-2": tete("dev-2", mesh_id="gw-absente", node_id="node-2"),
            "dev-3": tete("dev-3", mesh_id="gw-1", node_id=None),  # pas de node_id
        },
    )
    local = DanfossLocalCoordinator(hass, FakeManager(), cloud, 900)
    assert [h.dev_id for h in local.heads()] == ["dev-1"]


async def test_releve_renvoie_les_valeurs(hass: HomeAssistant):
    cloud = _cloud(hass, {"dev-1": tete("dev-1", mesh_id="gw-1", node_id="node-1")})
    local = DanfossLocalCoordinator(hass, FakeManager(releve={"dev-1": True}), cloud, 900)
    assert await local._async_update_data() == {"dev-1": True}


async def test_releve_sans_tete_rend_vide(hass: HomeAssistant):
    cloud = _cloud(hass, {})
    local = DanfossLocalCoordinator(hass, FakeManager(), cloud, 900)
    assert await local._async_update_data() == {}


async def test_releve_erreur_remonte_updatefailed(hass: HomeAssistant):
    cloud = _cloud(hass, {"dev-1": tete("dev-1", mesh_id="gw-1", node_id="node-1")})
    local = DanfossLocalCoordinator(
        hass, FakeManager(releve_exc=RuntimeError("tunnel ko")), cloud, 900
    )
    with pytest.raises(UpdateFailed):
        await local._async_update_data()
