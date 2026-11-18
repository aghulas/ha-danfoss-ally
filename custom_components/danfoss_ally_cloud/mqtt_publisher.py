"""MQTT publishing of the Danfoss devices (two configurable modes).

mode "discovery"  : publishes HA MQTT Discovery config
                    (homeassistant/<component>/<node>/config + state topics)
                    so HA (or another consumer) creates the entities. A bridge.
mode "zigbee2mqtt": bridge/state + bridge/devices (with exposes) and one state topic per
                    friendly_name, using z2m property names (local_temperature,
                    occupied_heating_setpoint, battery, pi_heating_demand, window_open).

source ("cloud" | "local"): where the values come from. v0.4: cloud source, read-only
(sensors + binary + availability). MQTT control will come later.

Config and state messages are published `retain` (a late subscriber gets the last state).
Availability follows `online` (cf. docs/architecture.md: online is authoritative, not update_time).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .api import DanfossDevice

_LOGGER = logging.getLogger(__name__)

DISCOVERY_PREFIX = "homeassistant"
AVAIL_ONLINE = "online"
AVAIL_OFFLINE = "offline"

# Published sensors (component, key, model field, discovery config options).
_SENSORS: tuple[dict[str, Any], ...] = (
    {
        "key": "temperature",
        "field": "temperature",
        "device_class": "temperature",
        "unit": "°C",
        "state_class": "measurement",
        "name": "Temperature",
    },
    {
        "key": "setpoint",
        "field": "setpoint",
        "device_class": "temperature",
        "unit": "°C",
        "state_class": "measurement",
        "name": "Setpoint",
    },
    {
        "key": "battery",
        "field": "battery",
        "device_class": "battery",
        "unit": "%",
        "state_class": "measurement",
        "name": "Battery",
    },
    {
        "key": "valve_opening",
        "field": "valve_opening",
        "unit": "%",
        "state_class": "measurement",
        "icon": "mdi:radiator",
        "name": "Valve opening",
    },
)
_BINARY: tuple[dict[str, Any], ...] = (
    {"key": "window", "field": "window_open", "device_class": "window", "name": "Window"},
)


def state_payload(dev: DanfossDevice) -> dict[str, Any]:
    """Values published for a head (state JSON). None excluded."""
    fields = {
        "temperature": dev.temperature,
        "setpoint": dev.setpoint,
        "battery": dev.battery,
        "valve_opening": dev.valve_opening,
        "window_open": dev.window_open,
    }
    return {k: v for k, v in fields.items() if v is not None}


# --- zigbee2mqtt mode -------------------------------------------------------------------------
# State properties with z2m names (Danfoss eTRV) and a minimal "exposes" for bridge/devices.
# access 1 = published (read): v0.5 is read-only, no command topic is handled.
_EXPOSES_Z2M: tuple[dict[str, Any], ...] = (
    {
        "type": "numeric",
        "name": "local_temperature",
        "property": "local_temperature",
        "access": 1,
        "unit": "°C",
    },
    {
        "type": "numeric",
        "name": "occupied_heating_setpoint",
        "property": "occupied_heating_setpoint",
        "access": 1,
        "unit": "°C",
        "value_min": 5,
        "value_max": 35,
        "value_step": 0.5,
    },
    {
        "type": "numeric",
        "name": "pi_heating_demand",
        "property": "pi_heating_demand",
        "access": 1,
        "unit": "%",
    },
    {"type": "numeric", "name": "battery", "property": "battery", "access": 1, "unit": "%"},
    {
        "type": "binary",
        "name": "window_open",
        "property": "window_open",
        "access": 1,
        "value_on": True,
        "value_off": False,
    },
)


def state_z2m(dev: DanfossDevice) -> dict[str, Any]:
    """A head's state with zigbee2mqtt property names. None excluded."""
    out: dict[str, Any] = {}
    if dev.temperature is not None:
        out["local_temperature"] = dev.temperature
    if dev.setpoint is not None:
        out["occupied_heating_setpoint"] = dev.setpoint
    if dev.valve_opening is not None:
        out["pi_heating_demand"] = dev.valve_opening
    heating = dev.heating  # work_state (DP 3), not the valve, per R-1
    if heating is not None:
        out["running_state"] = "heat" if heating else "idle"
    if dev.battery is not None:
        out["battery"] = dev.battery
    if dev.window_open is not None:
        out["window_open"] = dev.window_open
    return out


def name_z2m(dev: DanfossDevice) -> str:
    """z2m friendly_name: the head's name (or id), cleaned of topic-forbidden characters."""
    name = (dev.name or dev.id or "").strip() or dev.id
    for c in ("/", "+", "#"):
        name = name.replace(c, "_")
    return name


class MqttPublisher:
    """Publishes the heads' state to HA's MQTT broker (discovery mode, cloud source)."""

    def __init__(self, hass, coordinator, mode: str, source: str, base_topic: str) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._mode = mode
        self._source = source
        self._base = base_topic.rstrip("/")
        self._discovery_done: set[str] = set()
        self._unsub = None

    def _state_topic(self, device_id: str) -> str:
        return f"{self._base}/{device_id}"

    def _avail_topic(self, device_id: str) -> str:
        return f"{self._base}/{device_id}/availability"

    async def async_start(self) -> None:
        """Check MQTT, publish the initial state and subscribe to coordinator updates."""
        from homeassistant.components import mqtt

        if not await mqtt.async_wait_for_mqtt_client(self._hass):
            _LOGGER.warning("MQTT publishing requested but the MQTT broker is not available.")
            return
        if self._source == "local":
            _LOGGER.info("MQTT source 'local' not handled yet: publishing cloud values.")
        if self._mode == "zigbee2mqtt":
            await self._async_publish_bridge()
        await self._async_publish_all()
        self._unsub = self._coordinator.async_add_listener(self._on_update)

    def _on_update(self) -> None:
        self._hass.async_create_task(self._async_publish_all())

    async def async_stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    async def _async_publish_all(self) -> None:
        for dev in self._coordinator.data.values():
            if not dev.is_head:
                continue
            if self._mode == "zigbee2mqtt":
                await self._async_publish_device_z2m(dev)
            else:
                await self._async_publish_device(dev)

    async def _async_publish_device(self, dev: DanfossDevice) -> None:
        from homeassistant.components import mqtt

        if dev.id not in self._discovery_done:
            for cfg in self._discovery_configs(dev):
                await mqtt.async_publish(
                    self._hass, cfg["topic"], json.dumps(cfg["payload"]), qos=0, retain=True
                )
            self._discovery_done.add(dev.id)
        await mqtt.async_publish(
            self._hass,
            self._avail_topic(dev.id),
            AVAIL_ONLINE if dev.online else AVAIL_OFFLINE,
            qos=0,
            retain=True,
        )
        await mqtt.async_publish(
            self._hass,
            self._state_topic(dev.id),
            json.dumps(state_payload(dev)),
            qos=0,
            retain=True,
        )

    # --- zigbee2mqtt mode ---------------------------------------------------------------------

    def _ieee(self, dev: DanfossDevice) -> str:
        base = dev.node_id or dev.id or ""
        return base if base.startswith("0x") else f"0x{base}"

    def device_z2m(self, dev: DanfossDevice) -> dict[str, Any]:
        """A head's z2m descriptor for bridge/devices (exposed for the tests)."""
        return {
            "friendly_name": name_z2m(dev),
            "ieee_address": self._ieee(dev),
            "type": "EndDevice",
            "supported": True,
            "disabled": False,
            "definition": {
                "vendor": "Danfoss",
                "model": dev.product_id or "Ally eTRV",
                "description": "Danfoss Ally radiator thermostat",
                "exposes": list(_EXPOSES_Z2M),
            },
        }

    def bridge_devices(self) -> list[dict[str, Any]]:
        return [self.device_z2m(d) for d in self._coordinator.data.values() if d.is_head]

    async def _async_publish_bridge(self) -> None:
        from homeassistant.components import mqtt

        await mqtt.async_publish(
            self._hass, f"{self._base}/bridge/state", AVAIL_ONLINE, retain=True
        )
        await mqtt.async_publish(
            self._hass,
            f"{self._base}/bridge/devices",
            json.dumps(self.bridge_devices()),
            retain=True,
        )

    async def _async_publish_device_z2m(self, dev: DanfossDevice) -> None:
        from homeassistant.components import mqtt

        name = name_z2m(dev)
        await mqtt.async_publish(
            self._hass,
            f"{self._base}/{name}/availability",
            AVAIL_ONLINE if dev.online else AVAIL_OFFLINE,
            retain=True,
        )
        await mqtt.async_publish(
            self._hass, f"{self._base}/{name}", json.dumps(state_z2m(dev)), retain=True
        )

    # --- discovery mode -----------------------------------------------------------------------

    def _device_block(self, dev: DanfossDevice) -> dict[str, Any]:
        return {
            "identifiers": [f"{self._base}_{dev.id}"],
            "name": dev.name or dev.id,
            "manufacturer": "Danfoss",
            "model": dev.product_id,
        }

    def discovery_configs(self, dev: DanfossDevice) -> list[dict[str, Any]]:
        """Discovery config messages {topic, payload} for a head (exposed for the tests)."""
        return self._discovery_configs(dev)

    def _discovery_configs(self, dev: DanfossDevice) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        device = self._device_block(dev)
        state = self._state_topic(dev.id)
        avail = {
            "availability_topic": self._avail_topic(dev.id),
            "payload_available": AVAIL_ONLINE,
            "payload_not_available": AVAIL_OFFLINE,
        }
        for s in _SENSORS:
            payload = {
                "name": s["name"],
                "unique_id": f"{self._base}_{dev.id}_{s['key']}",
                "object_id": f"danfoss_{dev.id}_{s['key']}",
                "state_topic": state,
                "value_template": f"{{{{ value_json.{s['field']} }}}}",
                "device": device,
                **avail,
            }
            for opt in ("device_class", "state_class", "icon"):
                if opt in s:
                    payload[opt] = s[opt]
            if "unit" in s:
                payload["unit_of_measurement"] = s["unit"]
            out.append(
                {
                    "topic": f"{DISCOVERY_PREFIX}/sensor/{payload['object_id']}/config",
                    "payload": payload,
                }
            )
        for b in _BINARY:
            tpl = f"{{{{ 'ON' if value_json.{b['field']} else 'OFF' }}}}"
            payload = {
                "name": b["name"],
                "unique_id": f"{self._base}_{dev.id}_{b['key']}",
                "object_id": f"danfoss_{dev.id}_{b['key']}",
                "state_topic": state,
                "value_template": tpl,
                "payload_on": "ON",
                "payload_off": "OFF",
                "device_class": b["device_class"],
                "device": device,
                **avail,
            }
            out.append(
                {
                    "topic": f"{DISCOVERY_PREFIX}/binary_sensor/{payload['object_id']}/config",
                    "payload": payload,
                }
            )
        return out
