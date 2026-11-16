"""Diagnostics : la rédaction des secrets et des identifiants matériels est stricte."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR, DOMAIN
from custom_components.danfoss_ally_cloud.coordinator import DanfossCoordinator
from custom_components.danfoss_ally_cloud.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .common import ENTRY_DATA, FakeCloudClient, tete

_R = "**REDACTED**"


async def test_diagnostics_redige_secrets_et_ids(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, options={"mqtt_mode": "off"}, unique_id="compte@exemple.fr"
    )
    entry.add_to_hass(hass)
    coord = DanfossCoordinator(hass, FakeCloudClient(), 90)
    coord.data = {"dev-1": tete()}
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {DATA_COORDINATOR: coord}

    diag = await async_get_config_entry_diagnostics(hass, entry)

    # Secrets de compte / installation rédigés, identifiant non secret conservé.
    assert diag["entry"]["password"] == _R
    assert diag["entry"]["sign_key"] == _R
    assert diag["entry"]["ch_key"] == _R
    assert diag["entry"]["device_id"] == _R
    assert diag["entry"]["username"] == ENTRY_DATA["username"]

    # Identifiants matériels réels rédigés, valeurs décodées conservées.
    app = diag["appareils"][0]
    assert app["id"] == _R
    assert app["node_id"] == _R
    assert app["mesh_id"] == _R
    assert app["temperature"] == 20.5
    assert app["consigne"] == 21.0
    assert diag["nombre_appareils"] == 1
    assert diag["options"] == {"mqtt_mode": "off"}
