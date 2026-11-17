"""Local coordinator tests (preheat survey), doubled manager, hass harness."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.danfoss_ally_cloud.coordinator import (
    DanfossCoordinator,
    DanfossLocalCoordinator,
)

from .common import FakeCloudClient, head


class FakeManager:
    """Double of LocalTunnelManager: one gateway gw-1, controlled survey/write."""

    def __init__(self, survey=None, releve_exc=None):
        self._survey = survey or {}
        self._exc = releve_exc
        self.ecrits: list = []

    @property
    def gateway_ids(self):
        return {"gw-1"}

    def survey_preheat(self, heads):
        if self._exc is not None:
            raise self._exc
        return {h.dev_id: self._survey.get(h.dev_id, True) for h in heads}

    def write_preheat(self, head, actif):
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
            "dev-1": head("dev-1", mesh_id="gw-1", node_id="node-1"),
            "dev-2": head("dev-2", mesh_id="gw-absente", node_id="node-2"),
            "dev-3": head("dev-3", mesh_id="gw-1", node_id=None),  # pas de node_id
        },
    )
    local = DanfossLocalCoordinator(hass, FakeManager(), cloud, 900)
    assert [h.dev_id for h in local.heads()] == ["dev-1"]


async def test_survey_returns_the_values(hass: HomeAssistant):
    cloud = _cloud(hass, {"dev-1": head("dev-1", mesh_id="gw-1", node_id="node-1")})
    local = DanfossLocalCoordinator(hass, FakeManager(survey={"dev-1": True}), cloud, 900)
    assert await local._async_update_data() == {"dev-1": True}


async def test_survey_without_head_returns_empty(hass: HomeAssistant):
    cloud = _cloud(hass, {})
    local = DanfossLocalCoordinator(hass, FakeManager(), cloud, 900)
    assert await local._async_update_data() == {}


async def test_survey_error_raises_updatefailed(hass: HomeAssistant):
    cloud = _cloud(hass, {"dev-1": head("dev-1", mesh_id="gw-1", node_id="node-1")})
    local = DanfossLocalCoordinator(
        hass, FakeManager(releve_exc=RuntimeError("tunnel ko")), cloud, 900
    )
    with pytest.raises(UpdateFailed):
        await local._async_update_data()
