"""Tests d'intégration runtime : mise en place / déchargement et coordinateur (harnais hass)."""

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud.api.client import CloudAuthError, CloudError
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR, DOMAIN
from custom_components.danfoss_ally_cloud.coordinator import DanfossCoordinator

from .common import ENTRY_DATA, FakeCloudClient, tete


async def test_setup_and_unload(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr")
    entry.add_to_hass(hass)
    fake = FakeCloudClient(devices=[tete()])
    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DanfossCoordinator = data[DATA_COORDINATOR]
    assert "dev-1" in coordinator.data
    # Les plateformes ont créé des entités (climate principal + capteurs/binaires).
    assert hass.states.get("climate.salon") is not None
    assert hass.states.get("sensor.salon_battery") is not None
    assert hass.states.get("binary_sensor.salon_online") is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert fake.closed is True
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_coordinator_mappe_les_appareils(hass: HomeAssistant):
    fake = FakeCloudClient(devices=[tete("a", "A"), tete("b", "B")])
    coordinator = DanfossCoordinator(hass, fake, 90)
    data = await coordinator._async_update_data()
    assert set(data) == {"a", "b"}
    assert data["a"].nom == "A"


async def test_coordinator_auth_error(hass: HomeAssistant):
    fake = FakeCloudClient(list_exc=CloudAuthError("refus"))
    coordinator = DanfossCoordinator(hass, fake, 90)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_coordinator_cloud_error(hass: HomeAssistant):
    fake = FakeCloudClient(list_exc=CloudError("cloud ko"))
    coordinator = DanfossCoordinator(hass, fake, 90)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
