"""Device automations (actions) for Danfoss Ally Cloud rooms and heads.

Exposes two validated actions directly in the Home Assistant Automation UI when picking a
``danfoss_ally_cloud`` device:

- ``set_temperature``: calls ``climate.set_temperature`` on the device's climate entity (room or
  isolated head). Only this integration's own climate is offered.
- ``restore_schedule``: for room devices (identifier ``(DOMAIN, "group_<id>")``), calls
  ``danfoss_ally_cloud.restore_schedule`` so automations can return a room from manual mode to its
  weekly schedule. Not offered for an isolated head: back to schedule has no proven route there.

The climate is referenced by its entity REGISTRY id, as Home Assistant's own device actions do, so
an automation keeps working when the entity is renamed; a plain entity id is still accepted.
Neither action writes by itself: each goes through an existing service, which keeps its own value
checks and refusals.
"""

from __future__ import annotations

from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.climate import SERVICE_SET_TEMPERATURE
from homeassistant.components.device_automation import (
    InvalidDeviceAutomationConfig,
    async_validate_entity_schema,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_ENTITY_ID,
    CONF_TYPE,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType, TemplateVarsType

from .const import DOMAIN

ACTION_SET_TEMPERATURE = "set_temperature"
ACTION_RESTORE_SCHEDULE = "restore_schedule"

ACTION_TYPES = {ACTION_SET_TEMPERATURE, ACTION_RESTORE_SCHEDULE}

_MIN_TEMP = 5.0
_MAX_TEMP = 35.0

_SET_TEMPERATURE_SCHEMA = cv.DEVICE_ACTION_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): ACTION_SET_TEMPERATURE,
        vol.Required(CONF_ENTITY_ID): cv.entity_id_or_uuid,
        vol.Required(ATTR_TEMPERATURE): vol.All(
            vol.Coerce(float), vol.Range(min=_MIN_TEMP, max=_MAX_TEMP)
        ),
    }
)

_RESTORE_SCHEDULE_SCHEMA = cv.DEVICE_ACTION_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): ACTION_RESTORE_SCHEDULE,
    }
)

ACTION_SCHEMA = vol.Any(_SET_TEMPERATURE_SCHEMA, _RESTORE_SCHEDULE_SCHEMA)


async def async_validate_action_config(hass: HomeAssistant, config: ConfigType) -> ConfigType:
    """Validate the config and resolve the climate's registry id to its entity id."""
    return async_validate_entity_schema(hass, config, ACTION_SCHEMA)


def _room_group_id(hass: HomeAssistant, device_id: str) -> str | None:
    """Return the Danfoss group_id if ``device_id`` is a room device, else ``None``."""
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get(device_id)
    if device is None:
        return None
    for domain, ident in device.identifiers:
        if domain == DOMAIN and ident.startswith("group_"):
            return ident.removeprefix("group_")
    return None


async def async_get_actions(hass: HomeAssistant, device_id: str) -> list[dict[str, str]]:
    """List device actions for a Danfoss Ally Cloud device."""
    ent_reg = er.async_get(hass)
    actions: list[dict[str, str]] = []

    for entry in er.async_entries_for_device(ent_reg, device_id):
        # Only OUR climate: a device can carry entities of other integrations.
        if entry.domain == CLIMATE_DOMAIN and entry.platform == DOMAIN:
            actions.append(
                {
                    CONF_DEVICE_ID: device_id,
                    CONF_DOMAIN: DOMAIN,
                    CONF_ENTITY_ID: entry.id,
                    CONF_TYPE: ACTION_SET_TEMPERATURE,
                }
            )

    if _room_group_id(hass, device_id) is not None:
        actions.append(
            {
                CONF_DEVICE_ID: device_id,
                CONF_DOMAIN: DOMAIN,
                CONF_TYPE: ACTION_RESTORE_SCHEDULE,
            }
        )

    return actions


async def async_call_action_from_config(
    hass: HomeAssistant,
    config: ConfigType,
    variables: TemplateVarsType,
    context: Context | None,
) -> None:
    """Execute a configured device action."""
    action_type = config[CONF_TYPE]

    if action_type == ACTION_SET_TEMPERATURE:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {
                # Resolved here too: the config may still carry a registry id.
                ATTR_ENTITY_ID: er.async_resolve_entity_id(
                    er.async_get(hass), config[CONF_ENTITY_ID]
                ),
                ATTR_TEMPERATURE: config[ATTR_TEMPERATURE],
            },
            blocking=True,
            context=context,
        )
        return

    if action_type == ACTION_RESTORE_SCHEDULE:
        group_id = _room_group_id(hass, config[CONF_DEVICE_ID])
        if group_id is None:
            # Never a silent no-op: the automation would look as if it had restored something.
            raise InvalidDeviceAutomationConfig(
                "restore_schedule applies to a Danfoss room, and this device is not one"
            )
        await hass.services.async_call(
            DOMAIN,
            "restore_schedule",
            {"target": {"type": "room", "id": group_id}},
            blocking=True,
            context=context,
        )


async def async_get_action_capabilities(
    hass: HomeAssistant, config: ConfigType
) -> dict[str, vol.Schema]:
    """Return extra fields schema for a device action."""
    if config[CONF_TYPE] == ACTION_SET_TEMPERATURE:
        fields: dict[Any, Any] = {
            vol.Required(ATTR_TEMPERATURE): vol.All(
                vol.Coerce(float),
                vol.Range(min=_MIN_TEMP, max=_MAX_TEMP),
            )
        }
        return {"extra_fields": vol.Schema(fields)}
    return {}


__all__ = [
    "ACTION_RESTORE_SCHEDULE",
    "ACTION_SCHEMA",
    "ACTION_SET_TEMPERATURE",
    "ACTION_TYPES",
    "async_validate_action_config",
    "async_call_action_from_config",
    "async_get_action_capabilities",
    "async_get_actions",
]
