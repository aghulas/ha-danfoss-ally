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

## Programmes par pièce et interface embarquée

Chantier décrit par `docs/cahier-des-charges-interface.md`, cadré par le
contrat `docs/contrat-interface.md` (règles R1–R7). Un lot = une branche = une
demande de fusion, validée en réel sur une pièce d'essai.

- **Lot 0** — mise à niveau des documents (R4/R5) et alignement du thermostat
  sur R3 (pas d'écriture de consigne de mode sans réécriture du programme).
- **Lot 1** — couche `api/` : `schedule.py` (modèle, conversions, validation
  R1), pièces et programme dans `client.py`, décodage de l'état réel (DP 172).
- **Lot 2** — câblage Home Assistant : appareil par pièce, entités, actions +
  WebSocket, lots d'écriture (`WriteJob`), vérification locale différée.
- **Lot 3** — socle de l'interface embarquée (`frontend/`, TypeScript + Lit,
  fichier compilé versionné, enregistrement Lovelace, carte minimale).
- **Lot 4** — carte Programme en lecture (grille 7 jours, état des têtes).
- **Lot 5** — carte Programme en écriture (édition des plages, validation R1,
  suivi du lot, retour au programme).
