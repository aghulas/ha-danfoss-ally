"""Publication MQTT des appareils Danfoss (deux modes, configurables).

mode "discovery"  : publie la config MQTT Discovery de HA
                    (homeassistant/<composant>/<node>/config + topics d'état)
                    pour que HA (ou un autre consommateur) crée les entités. Un pont.
mode "zigbee2mqtt": bridge/state + bridge/devices (avec exposes) et un topic d'état par
                    friendly_name, aux noms de propriétés z2m (local_temperature,
                    occupied_heating_setpoint, battery, pi_heating_demand, window_open).

source ("cloud" | "local") : d'où viennent les valeurs. v0.4 : source cloud, en lecture
(capteurs + binaire + disponibilité). Le pilotage par MQTT viendra plus tard.

Les messages de config et d'état sont publiés en `retain` (un abonné tardif reçoit le dernier état).
La disponibilité suit `en_ligne` (cf. docs/architecture.md : online fait foi, pas update_time).
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

# Capteurs publiés (component, clé, champ du modèle, options de config discovery).
_SENSORS: tuple[dict[str, Any], ...] = (
    {
        "key": "temperature",
        "champ": "temperature",
        "device_class": "temperature",
        "unit": "°C",
        "state_class": "measurement",
        "name": "Température",
    },
    {
        "key": "consigne",
        "champ": "consigne",
        "device_class": "temperature",
        "unit": "°C",
        "state_class": "measurement",
        "name": "Consigne",
    },
    {
        "key": "batterie",
        "champ": "batterie",
        "device_class": "battery",
        "unit": "%",
        "state_class": "measurement",
        "name": "Batterie",
    },
    {
        "key": "ouverture_vanne",
        "champ": "ouverture_vanne",
        "unit": "%",
        "state_class": "measurement",
        "icon": "mdi:radiator",
        "name": "Ouverture de vanne",
    },
)
_BINARY: tuple[dict[str, Any], ...] = (
    {"key": "fenetre", "champ": "fenetre_ouverte", "device_class": "window", "name": "Fenêtre"},
)


def etat_payload(dev: DanfossDevice) -> dict[str, Any]:
    """Valeurs publiées pour une tête (JSON de l'état). None exclus."""
    champs = {
        "temperature": dev.temperature,
        "consigne": dev.consigne,
        "batterie": dev.batterie,
        "ouverture_vanne": dev.ouverture_vanne,
        "fenetre_ouverte": dev.fenetre_ouverte,
    }
    return {k: v for k, v in champs.items() if v is not None}


# --- mode zigbee2mqtt -------------------------------------------------------------------------
# Propriétés d'état au nom z2m (eTRV Danfoss) et « exposes » minimal pour bridge/devices.
# access 1 = publié (lecture) : la v0.5 est en lecture, aucun topic de commande n'est traité.
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


def etat_z2m(dev: DanfossDevice) -> dict[str, Any]:
    """État d'une tête aux noms de propriétés zigbee2mqtt. None exclus."""
    out: dict[str, Any] = {}
    if dev.temperature is not None:
        out["local_temperature"] = dev.temperature
    if dev.consigne is not None:
        out["occupied_heating_setpoint"] = dev.consigne
    if dev.ouverture_vanne is not None:
        out["pi_heating_demand"] = dev.ouverture_vanne
        out["running_state"] = "heat" if dev.ouverture_vanne > 0 else "idle"
    if dev.batterie is not None:
        out["battery"] = dev.batterie
    if dev.fenetre_ouverte is not None:
        out["window_open"] = dev.fenetre_ouverte
    return out


def nom_z2m(dev: DanfossDevice) -> str:
    """friendly_name z2m : nom de la tête (ou id), nettoyé des caractères interdits en topic."""
    nom = (dev.nom or dev.id or "").strip() or dev.id
    for c in ("/", "+", "#"):
        nom = nom.replace(c, "_")
    return nom


class MqttPublisher:
    """Publie l'état des têtes vers le broker MQTT de HA (mode discovery, source cloud)."""

    def __init__(self, hass, coordinator, mode: str, source: str, base_topic: str) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._mode = mode
        self._source = source
        self._base = base_topic.rstrip("/")
        self._discovery_faite: set[str] = set()
        self._unsub = None

    def _state_topic(self, device_id: str) -> str:
        return f"{self._base}/{device_id}"

    def _avail_topic(self, device_id: str) -> str:
        return f"{self._base}/{device_id}/availability"

    async def async_start(self) -> None:
        """Vérifie MQTT, publie l'état initial et s'abonne aux mises à jour du coordinateur."""
        from homeassistant.components import mqtt

        if not await mqtt.async_wait_for_mqtt_client(self._hass):
            _LOGGER.warning("Publication MQTT demandée mais le broker MQTT n'est pas disponible.")
            return
        if self._source == "local":
            _LOGGER.info("Source MQTT « local » pas encore gérée : publication des valeurs cloud.")
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
            if not dev.est_tete:
                continue
            if self._mode == "zigbee2mqtt":
                await self._async_publish_device_z2m(dev)
            else:
                await self._async_publish_device(dev)

    async def _async_publish_device(self, dev: DanfossDevice) -> None:
        from homeassistant.components import mqtt

        if dev.id not in self._discovery_faite:
            for cfg in self._discovery_configs(dev):
                await mqtt.async_publish(
                    self._hass, cfg["topic"], json.dumps(cfg["payload"]), qos=0, retain=True
                )
            self._discovery_faite.add(dev.id)
        await mqtt.async_publish(
            self._hass,
            self._avail_topic(dev.id),
            AVAIL_ONLINE if dev.en_ligne else AVAIL_OFFLINE,
            qos=0,
            retain=True,
        )
        await mqtt.async_publish(
            self._hass,
            self._state_topic(dev.id),
            json.dumps(etat_payload(dev)),
            qos=0,
            retain=True,
        )

    # --- mode zigbee2mqtt ---------------------------------------------------------------------

    def _ieee(self, dev: DanfossDevice) -> str:
        base = dev.node_id or dev.id or ""
        return base if base.startswith("0x") else f"0x{base}"

    def device_z2m(self, dev: DanfossDevice) -> dict[str, Any]:
        """Descripteur z2m d'une tête pour bridge/devices (exposé pour les tests)."""
        return {
            "friendly_name": nom_z2m(dev),
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
        return [self.device_z2m(d) for d in self._coordinator.data.values() if d.est_tete]

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

        nom = nom_z2m(dev)
        await mqtt.async_publish(
            self._hass,
            f"{self._base}/{nom}/availability",
            AVAIL_ONLINE if dev.en_ligne else AVAIL_OFFLINE,
            retain=True,
        )
        await mqtt.async_publish(
            self._hass, f"{self._base}/{nom}", json.dumps(etat_z2m(dev)), retain=True
        )

    # --- mode discovery -----------------------------------------------------------------------

    def _device_block(self, dev: DanfossDevice) -> dict[str, Any]:
        return {
            "identifiers": [f"{self._base}_{dev.id}"],
            "name": dev.nom or dev.id,
            "manufacturer": "Danfoss",
            "model": dev.product_id,
        }

    def discovery_configs(self, dev: DanfossDevice) -> list[dict[str, Any]]:
        """Messages de config discovery {topic, payload} d'une tête (exposé pour les tests)."""
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
                "value_template": f"{{{{ value_json.{s['champ']} }}}}",
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
            tpl = f"{{{{ 'ON' if value_json.{b['champ']} else 'OFF' }}}}"
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
