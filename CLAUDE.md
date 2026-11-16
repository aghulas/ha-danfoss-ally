# ha-danfoss-ally — intégration Home Assistant Danfoss Ally par l'API cloud (non publique, celle de l'application)

Guide pour les sessions Claude Code sur ce dépôt. But : une intégration HA
communautaire qui pilote les têtes Danfoss Ally via l'**API cloud** (voie 1a),
sans application développeur ni quota partagé, avec récupération des clés
passerelles et publication MQTT des appareils.

## Ce qu'on construit

- **Domaine HA** : `danfoss_ally_cloud` (distinct de `danfoss_ally` de MTrab,
  pour coexister et avoir une entrée propre dans `home-assistant/brands`).
- **Dépôt** : `aghulas/ha-danfoss-ally` (privé au départ, destiné au Marketplace
  HACS une fois durci).
- Diffusion publique assumée : apporter des fonctions à la communauté **et**
  éprouver le code sur d'autres installations pour fiabiliser les hypothèses.

## Principe directeur : cloud-first, repli local

L'API cloud couvre l'essentiel. Mais on a établi en réel des cas où le cloud
**ment ou n'agit pas** — à traiter en local (détail dans `docs/architecture.md`) :

- Le **passage en mode manuel** (DP 2 `manual`) efface le programme de la tête
  (R4) ; `at_home` / `leaving_home` publiés par le DP 2 ne sont que des
  **étiquettes** côté cloud : la tête garde la consigne de son programme (R5).
  Le retour au programme = réécrire le programme de la pièce, puis publier
  `at_home`. Détail et règles R1–R7 : `docs/contrat-interface.md`.
- Pré-chauffage : DP 1 cloud ne touche que le cache passerelle ; le vrai levier
  est l'attribut Zigbee **0x0025**, accessible seulement par le tunnel local.
- `update_time` est événementiel : `online` fait foi, pas lui.

Donc jamais « tout cloud » : cloud par défaut, **tunnel local optionnel** pour
les opérations que le cloud rate. Les clés passerelles sont récupérées par
l'intégration elle-même, donc le repli local reste interne.

## Carte du code

- `custom_components/danfoss_ally_cloud/` — l'intégration.
  - `api/` — accès Danfoss : `client.py` (API cloud), `keys.py` (clés
    passerelles), `local/tunnel.py` (Zigbee DP 198→199). À extraire à terme en
    bibliothèque partagée avec le connecteur MCP (`manifest.json` → requirements).
  - `coordinator.py` — polling cloud conservateur + superposition locale.
  - plateformes : `climate`, `sensor`, `binary_sensor`, `number`, `switch`.
  - `mqtt_publisher.py` — modes `discovery` / `zigbee2mqtt`, source `cloud` / `local`.
  - `config_flow.py`, `diagnostics.py`, `const.py`.
- `docs/` — `architecture.md`, `roadmap.md`, `reuse.md`.
- `tests/` — pytest-homeassistant-custom-component.

## Réutilisation (ne pas réécrire)

Voir `docs/reuse.md`. En bref : signature de l'application dans `~/dev/danfoss-ally-signing-re` ;
clés, DP, tunnel et décodage défauts dans `~/dev/danfoss-ally-mcp`
(`tuya/pilote_tuya.py`, `local.py`, `modeles.py`) ; noms officiels des DP dans
`~/dev/danfoss-app-capture/dp_schema_officiel.md` (source de vérité).

## Règles non négociables

- **Secrets** : jeton de session, mot de passe, localKey des passerelles,
  identifiants d'appareil réels — jamais dans les logs (stderr compris), les
  diagnostics ni le dépôt. `diagnostics.py` rédige. `git grep` avant tout push.
- **Fragilité Tuya** : on ride l'auth de l'app Tuya ; elle peut être invalidée
  ou changée. Re-authentification robuste, défauts de polling conservateurs
  (c'est le compte réel de l'utilisateur), cadrage « non officiel » dans le README.
- **Sûreté d'écriture** (différente du MCP) : ici pas de jeton préparer→confirmer ;
  la sûreté passe par la **validation des valeurs** avant envoi et par les
  entités indisponibles plutôt que mensongères (ex. switch pré-chauffage
  indisponible si le tunnel local est coupé). N'étendre les écritures qu'aux
  modèles vérifiés en réel (`const.WRITE_VERIFIED_MODELS`).
- Pas de donnée d'école ni de clé réelle dans les tests : données synthétiques
  uniquement.

## Tests et qualité

```
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -q
```

Tout vert avant commit. La CI rejoue hassfest + validation HACS + ruff + pytest
(`.github/workflows/`). Viser à terme le niveau d'une intégration sérieuse :
couverture élevée, mypy, diagnostics rédigés, audit des dépendances.

## Publier (HACS / Marketplace)

Prérequis déjà posés : `manifest.json` (domain, name, version semver, codeowners,
documentation, issue_tracker, iot_class, config_flow), `hacs.json`, workflows CI,
un composant unique sous `custom_components/`. Restent à faire avant inclusion :
assets de marque (PR séparée dans `home-assistant/brands`, au moins `icon.png`),
releases taggées, puis PR d'inclusion (seul le propriétaire/contributeur majeur
peut la soumettre). Installable en dépôt custom dès maintenant.

## Commit, push, discipline

- Commit et push **uniquement quand Rémi le demande**. Une branche par
  changement non trivial. Messages en français, corps listant les changements
  et la validation réelle, puis les lignes d'attribution indiquées par la session.
- Avant un push : `git grep` pour vérifier l'absence de secret.

## Liens avec le reste de Hesto

Fiches du projet claude.ai à tenir cohérentes : `claude/connecteur-danfoss-ally.md`
(connecteur MCP, enseignements, parc), `claude/danfoss-cles-locales-voie-a.md`
(méthode clés), `claude/tunnel-zigbee-danfoss-dp198.md` (tunnel). Les
enseignements terrain (incidents 01/11, pré-chauffage, pièges DP) viennent de là.
