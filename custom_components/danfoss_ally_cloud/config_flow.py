"""Config flow and options flow.

Path 1a: the app account's credentials (email/password login) + installation material captured
once (sign_key, deviceId, chKey - see README). The login validates the credentials AND the secrets
at once. Session renewal is handled by the client (the password is kept in the entry). When the
login itself is refused (password changed, installation secrets no longer valid), the coordinator
raises ``ConfigEntryAuthFailed`` and HA starts the ``reauth`` step below: same account, new
password, and new installation secrets only if they changed. Secrets are never logged.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .api import MQTT_CANDIDATE_DPS, CloudAuthError, CloudClient, CloudError, write_allowed
from .const import (
    CONF_CH_KEY,
    CONF_CLOUD_MQTT_PROBE,
    CONF_CLOUD_MQTT_SUPERVISED_DPS,
    CONF_CLOUD_MQTT_SUPERVISED_HEAD,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_ID,
    CONF_DISTINCT_DEVICE_ID,
    CONF_ENABLE_CLOUD_MQTT,
    CONF_ENABLE_HEAD_UNBIND,
    CONF_ENABLE_LOCAL,
    CONF_ENABLE_VACATION_WRITE,
    CONF_MQTT_BASE_TOPIC,
    CONF_MQTT_MODE,
    CONF_MQTT_SOURCE,
    CONF_PASSWORD,
    CONF_POST_COMMAND_REFRESH,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_SIGN_KEY,
    CONF_USERNAME,
    DATA_COORDINATOR,
    DEFAULT_CLOUD_MQTT_PROBE,
    DEFAULT_DISTINCT_DEVICE_ID,
    DEFAULT_ENABLE_CLOUD_MQTT,
    DEFAULT_ENABLE_HEAD_UNBIND,
    DEFAULT_ENABLE_VACATION_WRITE,
    DEFAULT_MQTT_BASE_TOPIC,
    DEFAULT_MQTT_MODE,
    DEFAULT_MQTT_SOURCE,
    DEFAULT_POST_COMMAND_REFRESH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _schema(schema: vol.Schema) -> Any:
    """Voluptuous form schema handed to HA. Runtime-accepted by every supported HA (2026.x
    included); HA 2026 types `data_schema` as probatio, hence Any at this boundary."""
    return schema


_REGIONS = ["eu", "us", "cn", "in"]

# Installation secrets the reauth step may replace (left empty = keep the entry's value).
_INSTALL_SECRETS = (CONF_SIGN_KEY, CONF_DEVICE_ID, CONF_CH_KEY)


def _account_id(username: str) -> str:
    """The entry's unique id for an account (the login, case and spaces ignored)."""
    return username.strip().lower()


# Labels of the cloud-MQTT candidate DPs in the supervised-trial selector.
_CANDIDATE_DP_LABELS = {
    16: "16 — temp_set (needed with 118: the app publishes both for the comfort setpoint)",
    18: "18 — upper bound",
    27: "27 — lower bound",
    116: "116 — window detection",
    118: "118 — comfort setpoint (with 16)",
    119: "119 — setback setpoint",
    120: "120 — pause setpoint (also needed with 27 when the lower bound rises above it)",
}


def _candidate_dp_choices() -> dict[str, str]:
    return {str(dp): _CANDIDATE_DP_LABELS.get(dp, str(dp)) for dp in sorted(MQTT_CANDIDATE_DPS)}


class DanfossAllyCloudConfigFlow(ConfigFlow, domain=DOMAIN):
    """First-time setup: one Danfoss Ally account."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(_account_id(user_input[CONF_USERNAME]))
            self._abort_if_unique_id_configured()
            client = CloudClient(
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                country_code=user_input[CONF_COUNTRY_CODE],
                sign_key=user_input[CONF_SIGN_KEY],
                device_id=user_input[CONF_DEVICE_ID],
                ch_key=user_input[CONF_CH_KEY],
                region=user_input[CONF_REGION],
                # Validate with the distinct deviceId (the runtime default), so even setup keeps
                # its own Tuya session rather than briefly stealing the app's / MCP's.
                distinct_device_id=DEFAULT_DISTINCT_DEVICE_ID,
            )
            try:
                await client.async_validate()
            except CloudAuthError:
                errors["base"] = "invalid_auth"
            except CloudError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - config_flow robustness
                _LOGGER.exception("Unexpected error while validating the Danfoss Ally account")
                errors["base"] = "unknown"
            else:
                await client.async_close()
                return self.async_create_entry(title=user_input[CONF_USERNAME], data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_COUNTRY_CODE, default="33"): str,
                vol.Required(CONF_REGION, default="eu"): vol.In(_REGIONS),
                vol.Required(CONF_SIGN_KEY): str,
                vol.Required(CONF_DEVICE_ID): str,
                vol.Required(CONF_CH_KEY): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=_schema(schema), errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> Any:
        """The login was refused at runtime (``ConfigEntryAuthFailed``): ask for new credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> Any:
        """Same account, new password; the installation secrets are replaced only if given.

        The username and the region stay those of the entry (the account cannot change here: a
        different login is refused). The new values are checked by a real login before the entry
        is updated and reloaded; nothing typed here is logged or echoed back in a message.
        """
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            expected = entry.unique_id or _account_id(entry.data[CONF_USERNAME])
            if _account_id(user_input[CONF_USERNAME]) != expected:
                return self.async_abort(reason="wrong_account")
            updates: dict[str, Any] = {CONF_PASSWORD: user_input[CONF_PASSWORD]}
            for key in _INSTALL_SECRETS:
                value = str(user_input.get(key) or "").strip()
                if value:
                    updates[key] = value
            data = {**entry.data, **updates}
            client = CloudClient(
                username=data[CONF_USERNAME],
                password=data[CONF_PASSWORD],
                country_code=data[CONF_COUNTRY_CODE],
                sign_key=data[CONF_SIGN_KEY],
                device_id=data[CONF_DEVICE_ID],
                ch_key=data[CONF_CH_KEY],
                region=data[CONF_REGION],
                distinct_device_id=DEFAULT_DISTINCT_DEVICE_ID,
            )
            try:
                await client.async_validate()
            except CloudAuthError:
                errors["base"] = "invalid_auth"
            except CloudError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - config_flow robustness
                _LOGGER.exception("Unexpected error while re-validating the Danfoss Ally account")
                errors["base"] = "unknown"
            finally:
                await client.async_close()
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates=updates)

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=entry.data.get(CONF_USERNAME, "")): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_SIGN_KEY): str,
                vol.Optional(CONF_DEVICE_ID): str,
                vol.Optional(CONF_CH_KEY): str,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=_schema(schema), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return DanfossAllyCloudOptionsFlow()


class DanfossAllyCloudOptionsFlow(OptionsFlow):
    """Options: interval, local tunnel, MQTT publishing mode and source."""

    def _trial_head_choices(self, current: str) -> dict[str, str]:
        """Heads a supervised trial may be confined to: the isolated heads on a verified model,
        by name (the stored value is the device id). Always offers "none", and keeps the current
        value selectable even when the fleet is not loaded."""
        choices: dict[str, str] = {"": "—"}
        data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id) or {}
        coordinator = data.get(DATA_COORDINATOR)
        if coordinator is not None:
            for dev in coordinator.data.values():
                if dev.is_head and write_allowed(dev) and coordinator.group_of(dev.id) is None:
                    choices[dev.id] = dev.name or "(unnamed head)"
        if current and current not in choices:
            choices[current] = "(head not available)"
        return choices

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        o = self.config_entry.options
        choices = _candidate_dp_choices()
        heads = self._trial_head_choices(str(o.get(CONF_CLOUD_MQTT_SUPERVISED_HEAD) or ""))
        supervised = [dp for dp in o.get(CONF_CLOUD_MQTT_SUPERVISED_DPS) or [] if dp in choices]
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=o.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): int,
                vol.Optional(
                    CONF_DISTINCT_DEVICE_ID,
                    default=o.get(CONF_DISTINCT_DEVICE_ID, DEFAULT_DISTINCT_DEVICE_ID),
                ): bool,
                vol.Optional(CONF_ENABLE_LOCAL, default=o.get(CONF_ENABLE_LOCAL, False)): bool,
                vol.Optional(
                    CONF_POST_COMMAND_REFRESH,
                    default=o.get(CONF_POST_COMMAND_REFRESH, DEFAULT_POST_COMMAND_REFRESH),
                ): bool,
                vol.Optional(
                    CONF_ENABLE_VACATION_WRITE,
                    default=o.get(CONF_ENABLE_VACATION_WRITE, DEFAULT_ENABLE_VACATION_WRITE),
                ): bool,
                vol.Optional(
                    CONF_ENABLE_HEAD_UNBIND,
                    default=o.get(CONF_ENABLE_HEAD_UNBIND, DEFAULT_ENABLE_HEAD_UNBIND),
                ): bool,
                vol.Optional(
                    CONF_ENABLE_CLOUD_MQTT,
                    default=o.get(CONF_ENABLE_CLOUD_MQTT, DEFAULT_ENABLE_CLOUD_MQTT),
                ): bool,
                vol.Optional(CONF_CLOUD_MQTT_SUPERVISED_DPS, default=supervised): cv.multi_select(
                    choices
                ),
                vol.Optional(
                    CONF_CLOUD_MQTT_SUPERVISED_HEAD,
                    default=str(o.get(CONF_CLOUD_MQTT_SUPERVISED_HEAD) or ""),
                ): vol.In(heads),
                vol.Optional(
                    CONF_CLOUD_MQTT_PROBE,
                    default=o.get(CONF_CLOUD_MQTT_PROBE, DEFAULT_CLOUD_MQTT_PROBE),
                ): bool,
                vol.Optional(
                    CONF_MQTT_MODE, default=o.get(CONF_MQTT_MODE, DEFAULT_MQTT_MODE)
                ): vol.In(["off", "discovery", "zigbee2mqtt"]),
                vol.Optional(
                    CONF_MQTT_SOURCE,
                    default=o.get(CONF_MQTT_SOURCE, DEFAULT_MQTT_SOURCE),
                ): vol.In(["cloud", "local"]),
                vol.Optional(
                    CONF_MQTT_BASE_TOPIC,
                    default=o.get(CONF_MQTT_BASE_TOPIC, DEFAULT_MQTT_BASE_TOPIC),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=_schema(schema))
