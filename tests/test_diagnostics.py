"""Diagnostics: redaction of secrets and hardware identifiers is strict."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud.const import DATA_COORDINATOR, DOMAIN
from custom_components.danfoss_ally_cloud.coordinator import DanfossCoordinator
from custom_components.danfoss_ally_cloud.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .common import ENTRY_DATA, FakeCloudClient, head

_R = "**REDACTED**"


async def test_diagnostics_redacts_secrets_and_ids(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, options={"mqtt_mode": "off"}, unique_id="compte@exemple.fr"
    )
    entry.add_to_hass(hass)
    coord = DanfossCoordinator(hass, FakeCloudClient(), 90)
    coord.data = {"dev-1": head()}
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {DATA_COORDINATOR: coord}

    diag = await async_get_config_entry_diagnostics(hass, entry)

    # Account / installation secrets redacted.
    assert diag["entry"]["password"] == _R
    assert diag["entry"]["sign_key"] == _R
    assert diag["entry"]["ch_key"] == _R
    assert diag["entry"]["device_id"] == _R
    assert diag["entry"]["username"] == _R

    # Real hardware identifiers redacted, decoded values kept.
    app = diag["devices"][0]
    assert app["id"] == _R
    assert app["node_id"] == _R
    assert app["mesh_id"] == _R
    assert app["temperature"] == 20.5
    assert app["setpoint"] == 21.0
    assert diag["device_count"] == 1
    assert diag["options"] == {"mqtt_mode": "off"}
