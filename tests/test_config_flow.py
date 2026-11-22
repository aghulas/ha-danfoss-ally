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
        assert result["type"] == FlowResultType.MENU
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "cloud"}
        )
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
            "cloud_mqtt_supervised_dps": ["1"],
        },
    )
    assert result2["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options["cloud_mqtt_supervised_dps"] == ["1"]
    assert entry.options[CONF_SCAN_INTERVAL] == 120
    assert entry.options[CONF_ENABLE_LOCAL] is True
    assert entry.options[CONF_MQTT_MODE] == "discovery"


# --- Re-authentication (the coordinator raises ConfigEntryAuthFailed on a refused login) ---------

_SETUP = "custom_components.danfoss_ally_cloud.async_setup_entry"
_NEW_PASSWORD = "nouveau-mdp-synth"


def _reauth_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=dict(ENTRY_DATA), unique_id="compte@exemple.fr")
    entry.add_to_hass(hass)
    return entry


async def _reauth(hass: HomeAssistant, entry: MockConfigEntry, fake: FakeCloudClient, user_input):
    result = await entry.start_reauth_flow(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    with patch(_FLOW, return_value=fake), patch(_SETUP, return_value=True) as setup:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
        await hass.async_block_till_done()
    return result, setup


async def test_reauth_success_updates_password_and_reloads(hass: HomeAssistant, caplog):
    entry = _reauth_entry(hass)
    fake = FakeCloudClient()
    result, setup = await _reauth(
        hass, entry, fake, {"username": "Compte@Exemple.fr ", "password": _NEW_PASSWORD}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == _NEW_PASSWORD
    # Installation secrets left empty: the entry's values are kept.
    for key in ("sign_key", "device_id", "ch_key", "username", "region", "country_code"):
        assert entry.data[key] == ENTRY_DATA[key]
    assert setup.await_count == 1  # the entry was reloaded with the new credentials
    assert fake.closed is True
    assert _NEW_PASSWORD not in caplog.text


async def test_reauth_replaces_only_the_secrets_given(hass: HomeAssistant):
    entry = _reauth_entry(hass)
    result, _ = await _reauth(
        hass,
        entry,
        FakeCloudClient(),
        {
            "username": ENTRY_DATA["username"],
            "password": _NEW_PASSWORD,
            "sign_key": "com.danfoss.ally_55:66:77:88_cccc_dddd",
            "ch_key": "  ",
        },
    )
    assert result["reason"] == "reauth_successful"
    assert entry.data["sign_key"] == "com.danfoss.ally_55:66:77:88_cccc_dddd"
    assert entry.data["ch_key"] == ENTRY_DATA["ch_key"]  # blank = kept
    assert entry.data["device_id"] == ENTRY_DATA["device_id"]


async def test_reauth_wrong_password_shows_the_form_again(hass: HomeAssistant, caplog):
    entry = _reauth_entry(hass)
    fake = FakeCloudClient(validate_exc=CloudAuthError("refused"))
    result, setup = await _reauth(
        hass, entry, fake, {"username": ENTRY_DATA["username"], "password": _NEW_PASSWORD}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data == ENTRY_DATA  # nothing written
    assert setup.await_count == 0
    assert fake.closed is True
    assert _NEW_PASSWORD not in caplog.text

    # Second try with a password the account accepts.
    with patch(_FLOW, return_value=FakeCloudClient()), patch(_SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": ENTRY_DATA["username"], "password": "bon-mdp-synth"}
        )
        await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "bon-mdp-synth"


async def test_reauth_cannot_connect_and_unknown(hass: HomeAssistant):
    entry = _reauth_entry(hass)
    result, _ = await _reauth(
        hass,
        entry,
        FakeCloudClient(validate_exc=CloudError("network")),
        {"username": ENTRY_DATA["username"], "password": _NEW_PASSWORD},
    )
    assert result["errors"] == {"base": "cannot_connect"}
    with patch(_FLOW, return_value=FakeCloudClient(validate_exc=ValueError("x"))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": ENTRY_DATA["username"], "password": _NEW_PASSWORD}
        )
    assert result["errors"] == {"base": "unknown"}
    assert entry.data == ENTRY_DATA


async def test_reauth_refuses_another_account(hass: HomeAssistant):
    entry = _reauth_entry(hass)
    fake = FakeCloudClient()
    result, setup = await _reauth(
        hass, entry, fake, {"username": "autre@exemple.fr", "password": _NEW_PASSWORD}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert entry.data == ENTRY_DATA
    assert setup.await_count == 0


async def test_refused_login_at_runtime_starts_the_reauth_flow(hass: HomeAssistant):
    """End to end: the coordinator's ConfigEntryAuthFailed leads to this flow's reauth step."""
    entry = _reauth_entry(hass)
    fake = FakeCloudClient(list_exc=CloudAuthError("refused"))
    with patch("custom_components.danfoss_ally_cloud.CloudClient", return_value=fake):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]
    assert flows[0]["step_id"] == "reauth_confirm"
