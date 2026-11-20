"""Tests for HACS / HA Quality Scale enhancements:
- manifest.json loggers & non-pinned dependency bounds,
- reconfigure config flow step,
- HA Repairs issues (offline gateways, active head faults, auto-clear & unload cleanup),
- typed ``entry.runtime_data`` (DanfossRuntimeData).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.danfoss_ally_cloud import DanfossRuntimeData
from custom_components.danfoss_ally_cloud.api import CloudAuthError, CloudError, DanfossDevice
from custom_components.danfoss_ally_cloud.const import (
    CONF_CH_KEY,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_SIGN_KEY,
    CONF_USERNAME,
    DATA_COORDINATOR,
    DOMAIN,
)
from custom_components.danfoss_ally_cloud.repairs import clear_repairs, sync_repairs
from tests.common import FakeCloudClient, head

_COMP_DIR = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "danfoss_ally_cloud"
)

_ENTRY_DATA = {
    CONF_USERNAME: "user@example.test",
    CONF_PASSWORD: "old-password",
    CONF_COUNTRY_CODE: "33",
    CONF_REGION: "eu",
    CONF_SIGN_KEY: "com.danfoss.ally_00:11_a_b",
    CONF_DEVICE_ID: "dev1234567890",
    CONF_CH_KEY: "abcd1234",
}


def test_manifest_loggers_and_flexible_requirements() -> None:
    """manifest.json declares loggers and avoids strict == pins that conflict in HA OS."""
    manifest = json.loads((_COMP_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert "custom_components.danfoss_ally_cloud" in manifest.get("loggers", [])
    for req in manifest["requirements"]:
        assert "==" not in req, f"Avoid strict pin in HACS manifest: {req}"


def test_reconfigure_and_issue_translations_present() -> None:
    """Reconfigure and Repairs translation keys exist in strings.json, en.json and fr.json."""
    for rel in ("strings.json", "translations/en.json", "translations/fr.json"):
        data = json.loads((_COMP_DIR / rel).read_text(encoding="utf-8"))
        assert "reconfigure" in data["config"]["step"]
        assert "reconfigure_successful" in data["config"]["abort"]
        assert "gateway_offline" in data["issues"]
        assert "head_fault" in data["issues"]


async def test_reconfigure_flow_updates_and_preserves_blank_secrets(hass: HomeAssistant) -> None:
    """Reconfigure validates via CloudClient, updates changed fields, keeps blank secrets."""
    entry = MockConfigEntry(domain=DOMAIN, data=dict(_ENTRY_DATA), unique_id="user@example.test")
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    # Auth error
    with patch(
        "custom_components.danfoss_ally_cloud.config_flow.CloudClient",
        return_value=FakeCloudClient(validate_exc=CloudAuthError("bad")),
    ):
        res_err = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_COUNTRY_CODE: "33", CONF_REGION: "eu", CONF_PASSWORD: "wrong"},
        )
    assert res_err["type"] is FlowResultType.FORM
    assert res_err["errors"] == {"base": "invalid_auth"}

    # Network error
    with patch(
        "custom_components.danfoss_ally_cloud.config_flow.CloudClient",
        return_value=FakeCloudClient(validate_exc=CloudError("net")),
    ):
        res_net = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_COUNTRY_CODE: "33", CONF_REGION: "eu"},
        )
    assert res_net["errors"] == {"base": "cannot_connect"}

    # Unexpected error
    with patch(
        "custom_components.danfoss_ally_cloud.config_flow.CloudClient",
        return_value=FakeCloudClient(validate_exc=RuntimeError("boom")),
    ):
        res_unk = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_COUNTRY_CODE: "33", CONF_REGION: "eu"},
        )
    assert res_unk["errors"] == {"base": "unknown"}

    # Success: change region + ch_key, leave password/sign_key/device_id blank
    with (
        patch(
            "custom_components.danfoss_ally_cloud.config_flow.CloudClient",
            return_value=FakeCloudClient(),
        ),
        patch.object(hass.config_entries, "async_reload", return_value=True),
    ):
        res_ok = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_COUNTRY_CODE: "45",
                CONF_REGION: "us",
                CONF_CH_KEY: "newchkey",
            },
        )
    assert res_ok["type"] is FlowResultType.ABORT
    assert res_ok["reason"] == "reconfigure_successful"
    assert entry.data[CONF_COUNTRY_CODE] == "45"
    assert entry.data[CONF_REGION] == "us"
    assert entry.data[CONF_CH_KEY] == "newchkey"
    assert entry.data[CONF_PASSWORD] == "old-password"
    assert entry.data[CONF_SIGN_KEY] == _ENTRY_DATA[CONF_SIGN_KEY]


def test_repairs_lifecycle_and_cleanup(hass: HomeAssistant) -> None:
    """Repairs issues appear for offline gateways / faulty heads and auto-clear on recovery."""
    reg = ir.async_get(hass)
    gw_off = DanfossDevice(
        id="gw1", name="Gateway A", category="gateway", product_id="gw", online=False
    )
    head_faulty = DanfossDevice(
        id="h1",
        name="Class 1",
        category="head",
        product_id="03wvrwpv",
        online=True,
        faults=[{"code": "E12", "label": "radio communication error"}],
    )

    sync_repairs(hass, "entry1", {"gw1": gw_off, "h1": head_faulty})
    assert reg.async_get_issue(DOMAIN, "gateway_offline_entry1_gw1") is not None
    assert reg.async_get_issue(DOMAIN, "head_fault_entry1_h1") is not None

    # Gateway recovers, head still faulty
    gw_on = DanfossDevice(
        id="gw1", name="Gateway A", category="gateway", product_id="gw", online=True
    )
    sync_repairs(hass, "entry1", {"gw1": gw_on, "h1": head_faulty})
    assert reg.async_get_issue(DOMAIN, "gateway_offline_entry1_gw1") is None
    assert reg.async_get_issue(DOMAIN, "head_fault_entry1_h1") is not None

    # Unload cleanup removes remaining issue
    clear_repairs(hass, "entry1")
    assert reg.async_get_issue(DOMAIN, "head_fault_entry1_h1") is None


async def test_setup_entry_sets_typed_runtime_data(hass: HomeAssistant) -> None:
    """async_setup_entry populates entry.runtime_data alongside hass.data."""
    entry = MockConfigEntry(domain=DOMAIN, data=dict(_ENTRY_DATA), unique_id="user@example.test")
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.danfoss_ally_cloud.CloudClient",
            return_value=FakeCloudClient(devices=[head("h1", "Salle 1")]),
        ),
        patch(
            "custom_components.danfoss_ally_cloud.async_register_frontend",
            return_value=None,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert isinstance(entry.runtime_data, DanfossRuntimeData)
    assert entry.runtime_data.coordinator is hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
