"""Mise en place runtime : repli local + publication MQTT + rechargement (harnais hass).

Couvre les branches de __init__ (local/MQTT), la branche locale de switch.async_setup_entry
(création du switch pré-chauffage) et son écriture. Tout est doublé : ni réseau, ni tinytuya,
ni broker réel.
"""

from unittest.mock import AsyncMock, patch

import homeassistant.components.mqtt as mqtt_mod
import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.danfoss_ally_cloud as integration
from custom_components.danfoss_ally_cloud.api import GatewayKey
from custom_components.danfoss_ally_cloud.const import (
    CONF_ENABLE_LOCAL,
    CONF_MQTT_MODE,
    DATA_LOCAL,
    DATA_MQTT,
    DOMAIN,
)

from .common import ENTRY_DATA, FakeCloudClient, tete
from .test_coordinator_local import FakeManager

_GW = {"gw-1": GatewayKey("gw-1", "GW", "cle-synth", ip="10.0.0.1")}


@pytest.fixture
def mqtt_double(monkeypatch):
    publie = AsyncMock()
    monkeypatch.setattr(mqtt_mod, "async_publish", publie)
    monkeypatch.setattr(mqtt_mod, "async_wait_for_mqtt_client", AsyncMock(return_value=True))
    return publie


async def _setup(hass: HomeAssistant, fake: FakeCloudClient, manager: FakeManager):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id="compte@exemple.fr",
        options={CONF_ENABLE_LOCAL: True, CONF_MQTT_MODE: "discovery"},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value=_GW),
        ),
        patch("custom_components.danfoss_ally_cloud.LocalTunnelManager", return_value=manager),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_setup_local_et_mqtt(hass: HomeAssistant, mqtt_double):
    fake = FakeCloudClient(devices=[tete()])
    manager = FakeManager(releve={"dev-1": True})
    entry = await _setup(hass, fake, manager)

    data = hass.data[DOMAIN][entry.entry_id]
    assert data[DATA_LOCAL] is not None  # coordinateur local en place
    assert data[DATA_MQTT] is not None  # publicateur MQTT démarré
    assert mqtt_double.await_count > 0  # a publié (broker simulé présent)

    # Le switch pré-chauffage est créé (tête rattachée à une passerelle connue) et vaut ON.
    etat = hass.states.get("switch.salon_pre_heating")
    assert etat is not None and etat.state == "on"

    # Écriture du pré-chauffage via le service HA : passe par le manager.
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.salon_pre_heating"}, blocking=True
    )
    assert manager.ecrits == [("dev-1", False)]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert fake.closed is True


async def test_local_sans_passerelle_rend_none(hass: HomeAssistant):
    """enable_local sans passerelle à clé : repli local = None, le cloud démarre quand même."""
    fake = FakeCloudClient(devices=[tete()])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id="compte@exemple.fr",
        options={CONF_ENABLE_LOCAL: True},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value={}),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.data[DOMAIN][entry.entry_id][DATA_LOCAL] is None


async def test_local_echec_recuperation_cles(hass: HomeAssistant):
    """Une erreur de récupération des clés ne doit pas empêcher le cloud de démarrer."""
    fake = FakeCloudClient(devices=[tete()])
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id="compte@exemple.fr",
        options={CONF_ENABLE_LOCAL: True},
    )
    entry.add_to_hass(hass)
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(side_effect=RuntimeError("cloud ko")),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.data[DOMAIN][entry.entry_id][DATA_LOCAL] is None


async def test_update_options_recharge(hass: HomeAssistant, mqtt_double):
    fake = FakeCloudClient(devices=[tete()])
    manager = FakeManager(releve={"dev-1": True})
    entry = await _setup(hass, fake, manager)
    with (
        patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake),
        patch(
            "custom_components.danfoss_ally_cloud.async_fetch_gateway_keys",
            AsyncMock(return_value=_GW),
        ),
        patch("custom_components.danfoss_ally_cloud.LocalTunnelManager", return_value=manager),
    ):
        await integration._async_update_options(hass, entry)
        await hass.async_block_till_done()
    # L'entrée est toujours en place après rechargement.
    assert entry.entry_id in hass.data[DOMAIN]
