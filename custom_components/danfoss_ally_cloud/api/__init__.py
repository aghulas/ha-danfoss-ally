"""Couche d'accès Danfoss Ally — bibliothèque réutilisable, sans dépendance Home Assistant.

Ce dossier EST la bibliothèque `pydanfoss-cloud` (cf. README.md ici) : le `pyproject.toml` du dépôt
le package sous le nom `pydanfoss_cloud` sans déplacer les fichiers. L'intégration le « vend » par
import relatif (`from .api import …`) pour rester autonome côté HACS ; le connecteur MCP pourra en
dépendre via PyPI une fois publié, puis l'intégration basculera vers manifest.json -> requirements.

Réutilisation (voir docs/reuse.md) :
  - client et signature de l'application  : ~/dev/danfoss-ally-signing-re
  - récupération des clés, DP    : ~/dev/danfoss-ally-mcp (tuya/pilote_tuya.py)
  - tunnel Zigbee DP 198/199     : ~/dev/danfoss-ally-mcp (local.py)
"""

from __future__ import annotations

from . import schedule
from .client import (
    CloudAuthError,
    CloudClient,
    CloudError,
    CloudWriteError,
    ScheduleValidationError,
    UnknownTargetError,
)
from .decode import DanfossDevice, decoder, decoder_operation, etat_tete
from .keys import GatewayKey, async_fetch_gateway_keys
from .schedule import Schedule, count_transitions, validate_days
from .writes import ecriture_autorisee, encode_consigne

__all__ = [
    "CloudAuthError",
    "CloudClient",
    "CloudError",
    "CloudWriteError",
    "DanfossDevice",
    "GatewayKey",
    "Schedule",
    "ScheduleValidationError",
    "UnknownTargetError",
    "async_fetch_gateway_keys",
    "count_transitions",
    "decoder",
    "decoder_operation",
    "ecriture_autorisee",
    "encode_consigne",
    "etat_tete",
    "schedule",
    "validate_days",
]
