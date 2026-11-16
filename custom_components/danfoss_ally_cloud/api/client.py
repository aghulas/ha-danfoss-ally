"""Client de l'API cloud (non publique, celle de l'application) Danfoss Ally (voie 1a).

Auth par compte de l'app (pas d'application développeur, pas de quota partagé).
Expose : session/login, liste des appareils (DP), lecture/écriture de DP
(contrôle cloud), endpoints pièces et programmes hebdomadaires.
"""

from __future__ import annotations


class CloudClient:
    """Accès cloud via l'API de l'application mobile."""

    def __init__(self, username: str, password: str, region: str) -> None:
        self._username = username
        self._region = region
        # Ne jamais conserver le mot de passe en clair plus que nécessaire ;
        # garder une session et la rafraîchir. Rien de tout ça dans les logs.

    async def async_login(self) -> None:
        ...

    async def devices(self) -> list[dict]:
        """Liste brute des appareils (DP)."""
        return []

    async def send_dp(self, device_id: str, code: int, value) -> None:
        """Écrire un DP (contrôle cloud)."""
        ...
