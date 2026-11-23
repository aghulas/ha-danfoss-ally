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
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import MQTT_CANDIDATE_DPS, CloudAuthError, CloudClient, CloudError, write_allowed
from .const import (
    CONF_CH_KEY,
    CONF_CLOUD_MQTT_PROBE,
    CONF_CLOUD_MQTT_SUPERVISED_DPS,
    CONF_CLOUD_MQTT_SUPERVISED_HEAD,
    CONF_CONNECTION_MODE,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_ID,
    CONF_DISTINCT_DEVICE_ID,
    CONF_ENABLE_CLOUD_MQTT,
    CONF_ENABLE_HEAD_UNBIND,
    CONF_ENABLE_LOCAL,
    CONF_ENABLE_VACATION_WRITE,
    CONF_LOCAL_SUPERVISED_HEAD,
    CONF_LOCAL_SUPERVISED_SETTINGS,
    CONF_MQTT_BASE_TOPIC,
    CONF_MQTT_MODE,
    CONF_MQTT_PREFIXES,
    CONF_MQTT_SOURCE,
    CONF_PASSWORD,
    CONF_POST_COMMAND_REFRESH,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_SIGN_KEY,
    CONF_USERNAME,
    CONNECTION_MODE_MQTT_COMPANION,
    DATA_COORDINATOR,
    DEFAULT_CLOUD_MQTT_PROBE,
    DEFAULT_DISTINCT_DEVICE_ID,
    DEFAULT_ENABLE_CLOUD_MQTT,
    DEFAULT_ENABLE_HEAD_UNBIND,
    DEFAULT_ENABLE_VACATION_WRITE,
    DEFAULT_MQTT_BASE_TOPIC,
    DEFAULT_MQTT_MODE,
    DEFAULT_MQTT_PREFIXES,
    DEFAULT_MQTT_SOURCE,
    DEFAULT_POST_COMMAND_REFRESH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .local_write import LOCAL_TRIAL_SETTINGS

_LOGGER = logging.getLogger(__name__)


def _schema(schema: vol.Schema) -> Any:
    """Voluptuous form schema handed to HA. Runtime-accepted by every supported HA (2026.x
    included); HA 2026 types `data_schema` as probatio, hence Any at this boundary."""
    return schema


_REGIONS = ["eu", "us", "cn", "in"]

# Password and installation secrets are typed in a masked field, never shown on screen.
_SECRET = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

# Installation secrets the reauth step may replace (left empty = keep the entry's value).
_INSTALL_SECRETS = (CONF_SIGN_KEY, CONF_DEVICE_ID, CONF_CH_KEY)


def _account_id(username: str) -> str:
    """The entry's unique id for an account (the login, case and spaces ignored)."""
    return username.strip().lower()


# Labels of the cloud-MQTT candidate DPs in the supervised-trial selector.
_CANDIDATE_DP_LABELS = {
    1: "1 — preheat (confirmed only by the local tunnel, attribute 0x0025: needs enable_local)",
    101: "101 — viewing direction (confirmed by the per-device cloud route; check the display)",
    133: "133 — orientation, vertical / horizontal (confirmed only by the local tunnel, "
    "attribute 0x4014: needs enable_local)",
}


# Labels of the local-tunnel settings in their supervised-trial selector.
_LOCAL_TRIAL_LABELS = {
    "radiator_covered": "Radiator covered (attribute 0x4016)",
    "setpoint_offset": "Setpoint offset, -2.5 to 2.5 °C (attribute 0x404B; scale not confirmed)",
    "regulation_speed": "Regulation speed, 1 to 10 (attribute 0x4020)",
    "valve_exercise": "Valve exercise day and time (attributes 0x4010 / 0x4011)",
    "external_room_sensor": "External measured room sensor, °C (attribute 0x4015; "
    "-80 °C disables it; must be refreshed periodically)",
    "window_open_external": "External window open (attribute 0x4003)",
    "load_balancing": "Load balancing (attribute 0x4032; managed by the room on an Ally gateway)",
    "adaptation_run_settings": "Automatic adaptation run on/off (attribute 0x404E; NOT the "
    "run launch/cancel command 0x404C)",
}


def _local_trial_choices() -> dict[str, str]:
    return {key: _LOCAL_TRIAL_LABELS.get(key, key) for key in LOCAL_TRIAL_SETTINGS}


def _candidate_dp_choices() -> dict[str, str]:
    return {str(dp): _CANDIDATE_DP_LABELS.get(dp, str(dp)) for dp in sorted(MQTT_CANDIDATE_DPS)}


def _parse_mqtt_prefixes(raw: Any) -> list[str]:
    """Normalize a companion prefixes input (list or comma string) to a de-duplicated list."""
    if isinstance(raw, list):
        prefixes = [str(p).strip().rstrip("/") for p in raw if str(p).strip().rstrip("/")]
    else:
        prefixes = [p.strip().rstrip("/") for p in str(raw).split(",") if p.strip().rstrip("/")]
    return list(dict.fromkeys(prefixes))


class DanfossAllyCloudConfigFlow(ConfigFlow, domain=DOMAIN):
    """First-time setup: one Danfoss Ally account."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        """Choose between v2 MQTT Companion mode (Z2M / danfoss2mqtt) and v1 direct Cloud mode."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["companion", "cloud"],
        )

    async def async_step_cloud(self, user_input: dict[str, Any] | None = None) -> Any:
        """v1 direct Danfoss Ally / Tuya cloud account setup."""
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
                vol.Required(CONF_PASSWORD): _SECRET,
                vol.Required(CONF_COUNTRY_CODE, default="33"): str,
                vol.Required(CONF_REGION, default="eu"): vol.In(_REGIONS),
                vol.Required(CONF_SIGN_KEY): _SECRET,
                vol.Required(CONF_DEVICE_ID): _SECRET,
                vol.Required(CONF_CH_KEY): _SECRET,
            }
        )
        return self.async_show_form(step_id="cloud", data_schema=_schema(schema), errors=errors)

    async def async_step_companion(self, user_input: dict[str, Any] | None = None) -> Any:
        """v2.x MQTT Companion setup: connect to zigbee2mqtt and/or danfoss2mqtt via Mosquitto."""
        errors: dict[str, str] = {}
        if user_input is not None:
            prefixes = _parse_mqtt_prefixes(
                user_input.get(CONF_MQTT_PREFIXES, DEFAULT_MQTT_PREFIXES)
            )
            if not prefixes:
                errors["base"] = "empty_prefixes"
            else:
                await self.async_set_unique_id(f"mqtt_companion:{','.join(prefixes)}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Danfoss Ally Companion ({', '.join(prefixes)})",
                    data={
                        CONF_CONNECTION_MODE: CONNECTION_MODE_MQTT_COMPANION,
                        CONF_MQTT_PREFIXES: prefixes,
                    },
                )

        schema = vol.Schema({vol.Required(CONF_MQTT_PREFIXES, default=DEFAULT_MQTT_PREFIXES): str})
        return self.async_show_form(step_id="companion", data_schema=_schema(schema), errors=errors)

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
                vol.Required(CONF_PASSWORD): _SECRET,
                vol.Optional(CONF_SIGN_KEY): _SECRET,
                vol.Optional(CONF_DEVICE_ID): _SECRET,
                vol.Optional(CONF_CH_KEY): _SECRET,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=_schema(schema), errors=errors
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> Any:
        """Update region, country code, password or installation secrets without deleting the entry.

        Any secret field left blank keeps its stored value. The resulting credentials are checked
        by a real login before saving and reloading.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            updates: dict[str, Any] = {
                CONF_COUNTRY_CODE: user_input[CONF_COUNTRY_CODE],
                CONF_REGION: user_input[CONF_REGION],
            }
            for key in (CONF_PASSWORD, *_INSTALL_SECRETS):
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
                distinct_device_id=entry.options.get(
                    CONF_DISTINCT_DEVICE_ID, DEFAULT_DISTINCT_DEVICE_ID
                ),
            )
            try:
                await client.async_validate()
            except CloudAuthError:
                errors["base"] = "invalid_auth"
            except CloudError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - config_flow robustness
                _LOGGER.exception("Unexpected error while reconfiguring the Danfoss Ally account")
                errors["base"] = "unknown"
            finally:
                await client.async_close()
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates=updates)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_COUNTRY_CODE, default=entry.data.get(CONF_COUNTRY_CODE, "33")
                ): str,
                vol.Required(CONF_REGION, default=entry.data.get(CONF_REGION, "eu")): vol.In(
                    _REGIONS
                ),
                vol.Optional(CONF_PASSWORD): _SECRET,
                vol.Optional(CONF_SIGN_KEY): _SECRET,
                vol.Optional(CONF_DEVICE_ID): _SECRET,
                vol.Optional(CONF_CH_KEY): _SECRET,
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=_schema(schema), errors=errors
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

    def _local_trial_head_choices(self, current: str) -> dict[str, str]:
        """Heads a local-tunnel trial may be confined to: the heads of a verified model with a
        Zigbee node id (grouped or isolated: the tunnel writes one head), by name. Always offers
        "none", and keeps the current value selectable even when the fleet is not loaded."""
        choices: dict[str, str] = {"": "—"}
        data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id) or {}
        coordinator = data.get(DATA_COORDINATOR)
        if coordinator is not None:
            for dev in coordinator.data.values():
                if dev.is_head and write_allowed(dev) and dev.node_id:
                    choices[dev.id] = dev.name or "(unnamed head)"
        if current and current not in choices:
            choices[current] = "(head not available)"
        return choices

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        # An MQTT-companion entry wires NONE of the direct-cloud / local-tunnel / cloud-MQTT
        # machinery (docs/companion-contract.md §2.4): a Companion talks only to the bridges over
        # Mosquitto, so enable_local / enable_cloud_mqtt / the supervised-trial options would be
        # inert here. Presenting them would be a lie, so a Companion gets its own options schema
        # limited to what it actually uses (the subscribed bridge prefixes).
        if self.config_entry.data.get(CONF_CONNECTION_MODE) == CONNECTION_MODE_MQTT_COMPANION:
            return await self._async_step_companion_options(user_input)
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        o = self.config_entry.options
        choices = _candidate_dp_choices()
        heads = self._trial_head_choices(str(o.get(CONF_CLOUD_MQTT_SUPERVISED_HEAD) or ""))
        supervised = [dp for dp in o.get(CONF_CLOUD_MQTT_SUPERVISED_DPS) or [] if dp in choices]
        local_choices = _local_trial_choices()
        local_heads = self._local_trial_head_choices(str(o.get(CONF_LOCAL_SUPERVISED_HEAD) or ""))
        local_supervised = [
            k for k in o.get(CONF_LOCAL_SUPERVISED_SETTINGS) or [] if k in local_choices
        ]
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
                    CONF_LOCAL_SUPERVISED_SETTINGS, default=local_supervised
                ): cv.multi_select(local_choices),
                vol.Optional(
                    CONF_LOCAL_SUPERVISED_HEAD,
                    default=str(o.get(CONF_LOCAL_SUPERVISED_HEAD) or ""),
                ): vol.In(local_heads),
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

    async def _async_step_companion_options(self, user_input: dict[str, Any] | None = None) -> Any:
        """Options for an MQTT-companion entry: only the subscribed bridge prefixes. The
        direct-cloud options do not apply to a Companion (docs/companion-contract.md §2.4)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            prefixes = _parse_mqtt_prefixes(
                user_input.get(CONF_MQTT_PREFIXES, DEFAULT_MQTT_PREFIXES)
            )
            if not prefixes:
                errors["base"] = "empty_prefixes"
            else:
                return self.async_create_entry(title="", data={CONF_MQTT_PREFIXES: prefixes})
        current = (
            self.config_entry.options.get(CONF_MQTT_PREFIXES)
            or self.config_entry.data.get(CONF_MQTT_PREFIXES)
            or DEFAULT_MQTT_PREFIXES
        )
        default = ",".join(current) if isinstance(current, list) else str(current)
        schema = vol.Schema({vol.Required(CONF_MQTT_PREFIXES, default=default): str})
        return self.async_show_form(step_id="init", data_schema=_schema(schema), errors=errors)
