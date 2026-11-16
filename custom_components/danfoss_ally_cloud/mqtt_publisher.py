"""Publication MQTT des appareils Danfoss (deux modes, configurables).

mode "discovery"  : publie la config MQTT Discovery de HA
                    (homeassistant/<composant>/<node>/config + topics d'état)
                    pour que HA (ou un autre consommateur) crée les entités. Un pont.
mode "zigbee2mqtt": topics compatibles z2m (v0.5).

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
            if dev.est_tete:
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
