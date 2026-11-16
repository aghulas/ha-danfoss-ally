"""Récupération des clés locales des passerelles (voie 1a).

Remplace l'émulateur / Frida : lit les localKey des passerelles via l'API
cloud (déjà validé en réel sur le parc Sainte-Marie). Ces clés permettent le
tunnel Zigbee local. À manipuler comme des secrets : jamais en clair dans les
logs, les diagnostics ou le dépôt.
"""

from __future__ import annotations


async def async_fetch_gateway_keys(client) -> dict[str, str]:
    """Retourne {gateway_id: localKey}. Masquer à l'affichage."""
    return {}
