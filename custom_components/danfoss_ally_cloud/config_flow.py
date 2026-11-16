"""Config flow et options flow.

Voie 1a : identifiants du compte de l'application (login email/mot de passe) + matériel
d'installation capturé une fois (sign_key, deviceId, chKey — voir README). Le login valide les
identifiants ET les secrets d'un coup. La ré-authentification est gérée par le client (le mot de
passe est conservé dans l'entrée, chiffré au repos par HA). Les secrets ne sont jamais journalisés.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback

from .api import CloudAuthError, CloudClient, CloudError
from .const import (
    CONF_CH_KEY,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_ID,
    CONF_ENABLE_LOCAL,
    CONF_MQTT_BASE_TOPIC,
    CONF_MQTT_MODE,
    CONF_MQTT_SOURCE,
    CONF_PASSWORD,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_SIGN_KEY,
    CONF_USERNAME,
    DEFAULT_MQTT_BASE_TOPIC,
    DEFAULT_MQTT_MODE,
    DEFAULT_MQTT_SOURCE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_REGIONS = ["eu", "us", "cn", "in"]


class DanfossAllyCloudConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Première configuration : un compte Danfoss Ally."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> Any:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].strip().lower())
            self._abort_if_unique_id_configured()
            client = CloudClient(
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                country_code=user_input[CONF_COUNTRY_CODE],
                sign_key=user_input[CONF_SIGN_KEY],
                device_id=user_input[CONF_DEVICE_ID],
                ch_key=user_input[CONF_CH_KEY],
                region=user_input[CONF_REGION],
            )
            try:
                await client.async_validate()
            except CloudAuthError:
                errors["base"] = "invalid_auth"
            except CloudError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - robustesse config_flow
                _LOGGER.exception("Erreur inattendue à la validation du compte Danfoss Ally")
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
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return DanfossAllyCloudOptionsFlow()


class DanfossAllyCloudOptionsFlow(OptionsFlow):
    """Options : intervalle, tunnel local, mode et source de publication MQTT."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        o = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=o.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): int,
                vol.Optional(CONF_ENABLE_LOCAL, default=o.get(CONF_ENABLE_LOCAL, False)): bool,
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
        return self.async_show_form(step_id="init", data_schema=schema)
