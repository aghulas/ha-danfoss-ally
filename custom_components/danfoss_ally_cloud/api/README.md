# pydanfoss-cloud

Bibliothèque d'accès à l'**API cloud non officielle Danfoss Ally** (voie 1a, celle de
l'application mobile — sans application développeur ni quota partagé), extraite de l'intégration
Home Assistant [`danfoss_ally_cloud`](https://github.com/aghulas/ha-danfoss-ally). **Sans dépendance
Home Assistant.**

Elle fournit :

- `CloudClient` — login email/mot de passe (+ secrets d'installation), liste des têtes, écritures
  gardées (`tuya.m.custom.wkf.settings.change`), re-authentification robuste.
- `decode` / `DanfossDevice` — décodage des `dps` Tuya en un modèle normalisé (schéma produit
  `03wvrwpv`), décodage des codes défaut E1–E15.
- `writes` — validation des valeurs avant envoi et garde-fou par modèle.
- `keys` — récupération des `localKey` + IP LAN des passerelles depuis le cloud.
- `local/` — tunnel Zigbee local (DP 198→199, tinytuya) : lecture/écriture d'attributs (pré-chauffage
  0x0025), programme hebdomadaire.

## Statut d'extraction (roadmap v0.6)

Source **unique** : ce dossier (`custom_components/danfoss_ally_cloud/api/`). Il est packagé sous le
nom `pydanfoss_cloud` par le `pyproject.toml` du dépôt, **sans déplacement de fichiers** :

- l'intégration Home Assistant continue de « vendre » ce code (import relatif `from .api import …`),
  ce qui garde l'installation HACS autonome ;
- le connecteur MCP (`danfoss-ally-mcp`) pourra en dépendre via `pip install pydanfoss-cloud` une
  fois la bibliothèque **publiée sur PyPI**, puis l'intégration basculera vers une dépendance
  `requirements` du `manifest.json`.

Installation en développement :

```
pip install -e .            # expose le paquet pydanfoss_cloud
pip install -e '.[local]'   # + tinytuya pour le tunnel local
```

## Dépendances

`pycryptodome`, `requests` (cœur) ; `tinytuya` (extra `local`, tunnel Zigbee). Python ≥ 3.12.

## Avertissement

API non documentée, obtenue par observation du protocole de l'application : elle peut changer ou
être coupée. Secrets (jeton de session, `localKey`, identifiants) : jamais journalisés ni commités.
