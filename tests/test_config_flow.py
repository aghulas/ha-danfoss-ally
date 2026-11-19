"""Config flow tests (hass harness, mocked client)."""

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud.api.client import CloudAuthError, CloudError
from custom_components.danfoss_ally_cloud.const import (
    CONF_ENABLE_LOCAL,
    CONF_MQTT_MODE,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)

from .common import ENTRY_DATA, FakeCloudClient

_FLOW = "custom_components.danfoss_ally_cloud.config_flow.CloudClient"


async def _submit(hass: HomeAssistant, fake: FakeCloudClient):
    with patch(_FLOW, return_value=fake):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        return await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY_DATA)


async def test_user_success(hass: HomeAssistant):
    result = await _submit(hass, FakeCloudClient())
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == ENTRY_DATA["username"]
    assert result["data"]["username"] == ENTRY_DATA["username"]


async def test_user_invalid_auth(hass: HomeAssistant):
    result = await _submit(hass, FakeCloudClient(validate_exc=CloudAuthError("refus")))
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_cannot_connect(hass: HomeAssistant):
    result = await _submit(hass, FakeCloudClient(validate_exc=CloudError("network")))
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_unknown_error(hass: HomeAssistant):
    # Toute exception inattendue -> "unknown" (robustesse du config flow).
    result = await _submit(hass, FakeCloudClient(validate_exc=ValueError("unexpected")))
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_already_configured(hass: HomeAssistant):
    MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr").add_to_hass(hass)
    result = await _submit(hass, FakeCloudClient())
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr", options={}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_SCAN_INTERVAL: 120,
            CONF_ENABLE_LOCAL: True,
            CONF_MQTT_MODE: "discovery",
            "mqtt_source": "cloud",
            "mqtt_base_topic": "danfoss_ally_cloud",
            "cloud_mqtt_supervised_dps": ["116"],
        },
    )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["cloud_mqtt_supervised_dps"] == ["116"]
    assert entry.options[CONF_SCAN_INTERVAL] == 120
    assert entry.options[CONF_ENABLE_LOCAL] is True
    assert entry.options[CONF_MQTT_MODE] == "discovery"
