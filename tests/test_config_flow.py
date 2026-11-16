"""Tests du config flow (harnais hass, client mocké)."""

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud.api.client import CloudAuthError, CloudError
from custom_components.danfoss_ally_cloud.const import DOMAIN

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
    result = await _submit(hass, FakeCloudClient(validate_exc=CloudError("réseau")))
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_already_configured(hass: HomeAssistant):
    MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="compte@exemple.fr").add_to_hass(hass)
    result = await _submit(hass, FakeCloudClient())
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
