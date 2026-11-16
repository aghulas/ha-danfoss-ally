"""Récupération des clés locales des passerelles (voie 1a).

Remplace l'émulateur / Frida : la localKey de chaque passerelle est renvoyée dans le champ
`localKey` de tuya.m.my.group.device.list (vérifié en réel, 10/10 passerelles). L'IP LAN vient de
smartlife.m.device.get v4.0 (meta.lan_ip). Ces clés sont des SECRETS : jamais en clair dans les
logs, les diagnostics ni le dépôt.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GatewayKey:
    """Matériel local d'une passerelle (secret : ne pas afficher local_key)."""

    dev_id: str
    nom: str | None
    local_key: str
    ip: str | None = None


def _est_passerelle(appareil: dict) -> bool:
    return (appareil.get("category") or "").startswith("wg")


async def async_fetch_gateway_keys(client) -> dict[str, GatewayKey]:
    """Retourne {gateway_devId: GatewayKey} (localKey + IP LAN) depuis le cloud. À ne pas afficher.

    `client` : CloudClient. Les têtes n'ont pas de clé propre : elles passent par la clé de leur
    passerelle (DanfossDevice.mesh_id = devId de la passerelle, node_id = cid Zigbee).
    """
    out: dict[str, GatewayKey] = {}
    for d in await client.async_list_raw():
        if _est_passerelle(d) and d.get("localKey"):
            out[d["devId"]] = GatewayKey(
                dev_id=d["devId"],
                nom=d.get("name"),
                local_key=d["localKey"],
            )
    # Compléter l'IP LAN (une requête par passerelle).
    for gw in out.values():
        try:
            meta = await client.async_device_meta(gw.dev_id)
        except Exception:  # noqa: BLE001 - l'IP peut manquer ; la passerelle reste listée
            continue
        gw.ip = meta.get("lan_ip")
    return out
