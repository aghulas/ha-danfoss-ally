"""Publication MQTT des appareils Danfoss (deux modes, configurables).

mode "discovery"  : publie la config MQTT Discovery de HA
                    (homeassistant/<composant>/<node>/config + topics d'état)
                    pour que HA crée les entités automatiquement. Un pont.
mode "zigbee2mqtt": publie sous une structure de topics compatible z2m
                    (<base>/<friendly_name>, <base>/bridge/devices) pour que
                    l'outillage et les dashboards z2m fonctionnent dessus.

source ("cloud" | "local") : d'où viennent les valeurs publiées. Le local
donne les vrais attributs (le cloud se trompe p. ex. sur le pré-chauffage) ;
le cloud est plus simple mais parfois faux. Choix laissé à l'utilisateur.
"""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)


class MqttPublisher:
    """Publie l'état des appareils vers le broker MQTT de HA."""

    def __init__(self, hass, mode: str, source: str, base_topic: str) -> None:
        self._hass = hass
        self._mode = mode
        self._source = source
        self._base = base_topic

    async def async_start(self) -> None:
        # TODO: s'abonner aux mises à jour du coordinateur (ou du tunnel local
        # selon la source) et republier. En mode discovery, publier les configs
        # au démarrage ; en mode z2m, publier bridge/devices + états.
        ...

    async def async_stop(self) -> None: ...

    def _publish_discovery(self, device) -> None: ...

    def _publish_zigbee2mqtt(self, device) -> None: ...
