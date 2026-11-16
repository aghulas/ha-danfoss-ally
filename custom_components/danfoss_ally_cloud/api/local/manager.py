"""Gestionnaire du tunnel local : relevé et écriture du pré-chauffage (attribut 0x0025).

Isole l'I/O bloquante (tinytuya) : la couche HA l'appelle dans l'executor. Un fil par passerelle,
best-effort (une tête injoignable → None, jamais d'exception propagée au relevé global). La fabrique
de lien est injectable (``ouvrir``) pour les tests (doublure sans réseau).
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..keys import GatewayKey
from . import tunnel

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Head:
    """Tête adressable par le tunnel : son devId, son cid Zigbee (node_id) et sa passerelle."""

    dev_id: str
    node_id: str
    gateway_id: str


class LocalTunnelManager:
    """Ouvre des liens tinytuya vers les passerelles pour lire/écrire le pré-chauffage réel."""

    def __init__(
        self,
        gateways: dict[str, GatewayKey],
        ouvrir: Callable[[GatewayKey], Any] = tunnel.LocalLink,
    ) -> None:
        self._gateways = gateways
        self._ouvrir = ouvrir

    @property
    def gateway_ids(self) -> set[str]:
        return set(self._gateways)

    def relever_prechauffage(self, heads: list[Head]) -> dict[str, bool | None]:
        """Lit le pré-chauffage (0x0025 bit 1) par tête, une passerelle par fil. Best-effort."""
        res: dict[str, bool | None] = {}
        garde = threading.Lock()
        par_gw: dict[str, list[Head]] = defaultdict(list)
        for h in heads:
            if h.gateway_id in self._gateways:
                par_gw[h.gateway_id].append(h)

        def fil(gw_id: str, miennes: list[Head]) -> None:
            try:
                lien = self._ouvrir(self._gateways[gw_id])
            except Exception as err:  # noqa: BLE001 - passerelle injoignable : têtes = None
                _LOGGER.debug("tunnel local : passerelle %s injoignable (%s)", gw_id, err)
                with garde:
                    for h in miennes:
                        res[h.dev_id] = None
                return
            try:
                for h in miennes:
                    try:
                        v = tunnel.lire_prechauffage(lien, h.dev_id, h.node_id)
                    except Exception:  # noqa: BLE001 - on isole chaque tête
                        v = None
                    with garde:
                        res[h.dev_id] = v
            finally:
                lien.fermer()

        fils = [threading.Thread(target=fil, args=(g, m), daemon=True) for g, m in par_gw.items()]
        for f in fils:
            f.start()
        for f in fils:
            f.join(timeout=40)
        return res

    def ecrire_prechauffage(self, head: Head, actif: bool) -> bool:
        """Active/désactive le pré-chauffage (lit 0x0025, écrit le bit, programme préservé).

        True si la tête accepte (statut 0). Lève LocalErreur/LocalIndisponible sinon.
        """
        if head.gateway_id not in self._gateways:
            raise tunnel.LocalIndisponible(f"passerelle inconnue : {head.gateway_id}")
        lien = self._ouvrir(self._gateways[head.gateway_id])
        try:
            mode = tunnel.lire_mode_programmation(lien, head.dev_id, head.node_id)
            if mode is None:
                raise tunnel.LocalErreur("attribut 0x0025 illisible (tête injoignable)")
            statut = tunnel.ecrire_prechauffage(lien, head.dev_id, head.node_id, actif, mode)
            return statut == 0
        finally:
            lien.fermer()
