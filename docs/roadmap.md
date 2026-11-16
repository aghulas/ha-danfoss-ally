# Feuille de route

- **v0.0** — squelette (ce commit) : arborescence HA, config_flow/options,
  stubs, CI (hassfest + HACS + ruff + pytest).
- **v0.1** — lecture seule cloud : climate (température, consigne) + capteurs,
  sur une install réelle.
- **v0.2** — écritures cloud validées (consignes, verrou enfant, fenêtre) sur
  modèles vérifiés ; valeurs contrôlées avant envoi.
- **v0.3** — tunnel local optionnel : pré-chauffage (0x0025) et lecture du
  programme hebdomadaire dans la tête.
- **v0.4** — publication MQTT mode `discovery`.
- **v0.5** — publication MQTT mode `zigbee2mqtt` (bridge/devices + topics z2m).
- **v0.6** — extraction de la couche `api/` en bibliothèque partagée avec le
  connecteur MCP.
- **v1.0** — durcissement (tests, couverture, mypy, diagnostics), puis PR
  d'inclusion au Marketplace HACS.

But transversal : éprouver le code sur d'autres installations (firmwares,
product ids, modèles de passerelles) pour fiabiliser les hypothèses DP.
