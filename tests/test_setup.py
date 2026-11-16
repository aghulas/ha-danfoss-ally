"""Tests d'intégration runtime : mise en place / déchargement et coordinateur (harnais hass)."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud import _cleanup_orphaned_head_climates
from custom_components.danfoss_ally_cloud.api.client import CloudAuthError, CloudError
from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR, DOMAIN
from custom_components.danfoss_ally_cloud.coordinator import DanfossCoordinator

from .common import ENTRY_DATA, FakeCloudClient, tete

_PIECE = [{"group_id": 77, "nom": "Salle", "pid": "03wvrwpv", "nb_tetes": 2}]


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


async def test_coordinator_construit_les_pieces(hass: HomeAssistant):
    fake = FakeCloudClient(
        devices=[tete("a", "A", temperature=18.0), tete("b", "B", temperature=20.0)],
        groups=_PIECE,
        members={"77": ["a", "b"]},
    )
    coordinator = DanfossCoordinator(hass, fake, 90)
    data = await coordinator._async_update_data()
    assert set(data) == {"a", "b"}
    assert "77" in coordinator.rooms
    assert coordinator.rooms["77"].temperature == 19.0  # moyenne
    assert coordinator.grouped_ids == {"a", "b"}
    assert coordinator.group_of("a") == "77"


async def test_coordinator_topologie_degrade_en_isole(hass: HomeAssistant):
    # Lecture de topologie en échec et aucun cache : têtes traitées comme isolées (pas de pièce).
    fake = FakeCloudClient(devices=[tete("a", "A")], topology_exc=CloudError("topo ko"))
    coordinator = DanfossCoordinator(hass, fake, 90)
    data = await coordinator._async_update_data()
    assert set(data) == {"a"}
    assert coordinator.rooms == {}
    assert coordinator.grouped_ids == set()
    assert coordinator.group_of("a") is None


async def test_cleanup_retire_ancien_climate_par_tete(hass: HomeAssistant):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr")
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    # Ancien modèle : un climate par tête. « a » est maintenant groupée, « c » reste isolée.
    groupee = registry.async_get_or_create("climate", DOMAIN, "a", config_entry=entry)
    isolee = registry.async_get_or_create("climate", DOMAIN, "c", config_entry=entry)
    coord = SimpleNamespace(grouped_ids={"a"})

    _cleanup_orphaned_head_climates(hass, entry, coord)

    assert registry.async_get(groupee.entity_id) is None  # tête groupée : ancien climate retiré
    assert registry.async_get(isolee.entity_id) is not None  # tête isolée : climate conservé
