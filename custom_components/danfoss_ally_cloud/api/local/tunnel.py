"""Tunnel Zigbee local via les passerelles Tuya (DP 198 -> réponse DP 199).

Pour les opérations que le cloud rate : lecture du programme hebdomadaire
directement dans la tête, écriture de l'attribut de pré-chauffage 0x0025,
lecture des vrais attributs. S'appuie sur tinytuya et les clés de api.keys.

Repris de ~/dev/danfoss-ally-mcp/.../local.py (trames en fonctions pures,
un verrou par passerelle, une passerelle par fil).
"""

from __future__ import annotations


class LocalTunnel:
    """Dialogue Zigbee local avec une passerelle."""

    def __init__(self, gateway_ip: str, gateway_id: str, local_key: str) -> None:
        self._ip = gateway_ip
        self._id = gateway_id
        # local_key : secret, jamais logué.

    async def read_schedule(self, cid: str) -> dict:
        ...

    async def write_attribute(self, cid: str, attr: int, value: int) -> None:
        ...
