"""Couche d'accès Danfoss Ally.

À terme, extraire cette couche en bibliothèque installable (p. ex.
`pydanfoss-cloud`) partagée avec le connecteur MCP, et la référencer dans
manifest.json -> requirements. Pour l'amorçage, elle vit ici.

Réutilisation (voir docs/reuse.md) :
  - client et signature de l'application  : ~/dev/danfoss-ally-signing-re
  - récupération des clés, DP    : ~/dev/danfoss-ally-mcp (tuya/pilote_tuya.py)
  - tunnel Zigbee DP 198/199     : ~/dev/danfoss-ally-mcp (local.py)
"""
