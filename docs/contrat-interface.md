# Contrat d'interface — programmes, modes et pièces

Ce document fixe ce que le backend (Python, `custom_components/danfoss_ally_cloud/`) fournit et ce que
l'interface (`frontend/`) consomme. **C'est le seul fichier partagé entre les deux chantiers** : toute
évolution d'un côté qui change une forme décrite ici passe d'abord par une modification de ce contrat.

Il s'appuie sur des essais réels du 16/11/2026 (API de l'app, relus dans les têtes par le tunnel local).
Les règles de la section 2 ne sont pas des préférences : chacune correspond à un comportement constaté.

## 1. Vocabulaire et identifiants

| Terme | Côté cloud | Identifiant | Dans Home Assistant |
|---|---|---|---|
| Maison | « home » du compte | `gid` (entier) | regroupement logique, pas d'appareil |
| Passerelle | appareil, `category` `wg2` | `devId` | appareil (hub) |
| Pièce | groupe-programme (type 5) | `group_id` (entier) ; `pid` du produit | **appareil « pièce »** (à créer), identifiant `(DOMAIN, "room_<group_id>")` |
| Tête | appareil, `category` `wk` | `devId` ; `meshId` = passerelle ; `nodeId` = adresse Zigbee | appareil existant, `via_device` = passerelle |
| Tête isolée | tête sans pièce | `devId` | idem ; se programme seule (`resType` 1) |

Une tête **groupée** ne se programme et ne se règle que par sa pièce. Une pièce a au moins deux têtes.

Appartenance des têtes aux pièces : `m.life.my.group.device.relation.list` v3.2, corps `{gid}` → clé `"5"` :
liste de groupes `{id, children: {"6": [{id: devId}, …]}}`. Liste des pièces :
`m.life.my.group.device.group.list` v4.3, corps `{gid}` → `[{id, name, deviceNum, productId}]`.

## 2. Règles établies en réel (à appliquer côté serveur, pas seulement à l'écran)

**R1 — Six transitions par jour au plus dans une tête.** Décompte des transitions qu'un jour demande :
- chaque plage compte son début, sauf s'il vaut `00:00` ;
- chaque plage compte sa fin, sauf si une autre plage commence à cette heure (plages qui se touchent) ;
- si aucune plage ne commence à `00:00`, la tête ajoute une transition « réduit » à `00:00` **s'il lui reste
  de la place** (à 6, elle l'abandonne et garde jusqu'à la première plage la consigne de la veille au soir).

Un jour est **valide si ce décompte est ≤ 6** (au plus trois plages séparées). Au-delà, **le cloud accepte et
affiche le programme, mais la tête perd toutes les transitions du jour**. Le backend refuse avant tout envoi.

> **Même limite matérielle des deux côtés.** « R1 au niveau cloud : ≤ 6 transitions/jour, règle de bord à
> `00:00` » (ce document) et la formulation côté tunnel local du connecteur MCP (« 1 à 6 transitions,
> la 1ʳᵉ à `00:00` ») décrivent **la même contrainte de la tête** (le firmware Danfoss ne retient que six
> transitions par jour, la première posée à minuit), vue respectivement par l'API cloud et par le programme
> relu dans la tête par le tunnel. Elles doivent rester cohérentes : un correctif d'un côté (décompte, règle
> de bord, nombre maximal) doit être reporté de l'autre, et non traité comme une divergence à arbitrer.

**R2 — Écrire un jour renvoie toute la semaine** aux têtes, avec les consignes confort / réduit du moment.

**R3 — Le programme porte ses propres consignes.** Après tout changement de la consigne confort ou réduit
d'une pièce, le backend réécrit le programme (un jour suffit, R2). Sans cela la consigne en cours change,
mais les transitions gardent l'ancienne valeur et la tête y revient au prochain changement d'horaire.

**R4 — Le mode manuel efface le programme de la tête.** Le retour au programme consiste à réécrire le
programme de la pièce (c'est ce qui agit sur la tête), puis à publier le mode `at_home` (pour que le cloud
n'affiche plus « manuel »). Publier `at_home` seul ne change que l'affichage.

**R5 — `at_home`, `leaving_home` et `holiday` publiés par le DP 2 ne sont que des étiquettes côté cloud.**
La tête garde la consigne de son programme. Aucun préréglage « confort / réduit maintenant » ni « vacances »
ne doit être câblé sur cet appel. L'appel réel de l'app pour ces fonctions n'est pas encore connu.

**R6 — L'état réel d'une tête se lit dans le DP 172** (`operation_mode`, reflet de l'attribut Zigbee
0x0025) : bit 0 = programme actif, bit 1 = pré-chauffage ; 0 = manuel. Le DP 2 (mode affiché) peut dire
« confort » sur une tête restée en manuel.

**R7 — Délais.** Programme, mode manuel et consigne de pièce atteignent les têtes en moins de 5 minutes
(mesuré sur une passerelle peu chargée) ; les réglages de pièce en 5 à 10 minutes. Une écriture est donc
« envoyée » tout de suite et « appliquée » plus tard, ou jamais (tête hors ligne).

## 3. Modèles de données

Toutes les heures sont des chaînes `HH:MM` sur 24 h, de `00:00` à `23:59`. Les jours sont nommés
`mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`. Les températures sont en °C, pas de 0,5.

### 3.1 Cible

```json
{ "type": "room", "id": "13000000" }
```
`type` : `room` (pièce, `id` = `group_id` en chaîne) ou `device` (tête isolée, `id` = `devId`).

### 3.2 Programme (`Schedule`)

```json
{
  "target": { "type": "room", "id": "13000000" },
  "name": "Salle 1",
  "comfort": 21.0,
  "setback": 14.0,
  "days": {
    "mon": [{ "start": "08:30", "end": "17:30" }],
    "tue": [{ "start": "08:30", "end": "17:30" }],
    "wed": [],
    "thu": [{ "start": "08:30", "end": "17:30" }],
    "fri": [{ "start": "08:30", "end": "17:30" }],
    "sat": [],
    "sun": []
  },
  "max_transitions_per_day": 6,
  "source": "cloud",
  "read_at": "2026-11-16T15:36:00+01:00"
}
```
- `days` contient toujours les sept jours ; une liste vide = jour entièrement en réduit.
- Plages triées, sans chevauchement, `start < end`. Deux plages peuvent se toucher.
- `comfort` / `setback` : consignes de la pièce (DP 118 et DP 119), en lecture ici ; elles s'écrivent par les
  entités `number` (section 5).
- `source` : `cloud` aujourd'hui ; `local` et `zigbee` sont réservés.

### 3.3 État d'une tête (`HeadState`)

```json
{
  "device_id": "<devId>",
  "name": "Salle 1 #2",
  "room_id": "13000000",
  "online": true,
  "mode_displayed": "at_home",
  "schedule_active": true,
  "preheat": false,
  "mounting": false,
  "inconsistent": false
}
```
- `schedule_active`, `preheat` : décodés du DP 172 (R6) ; `null` si le DP est absent.
- `inconsistent` : `mode_displayed` vaut `at_home` ou `leaving_home` alors que `schedule_active` est `false`
  (tête restée en manuel à l'insu de l'app).
- `mounting` : DP 149 (tête en mode montage, ne régule pas).

### 3.4 Pièce (`Room`)

```json
{
  "id": "13000000",
  "name": "Salle 1",
  "home": "Maison",
  "product_id": "03wvrwpv",
  "heads": [ /* HeadState */ ],
  "comfort": 21.0,
  "setback": 14.0
}
```

### 3.5 Suivi d'une écriture (`WriteJob`)

```json
{
  "job_id": "…",
  "kind": "set_schedule",
  "target": { "type": "room", "id": "13000000" },
  "status": "sent",
  "created_at": "…",
  "heads": [
    { "device_id": "<devId>", "status": "pending", "detail": null }
  ]
}
```
- `status` du lot : `sent` (le cloud a accepté) → `applied` (toutes les têtes vérifiées) | `partial` |
  `unverified` (pas de vérification possible) | `failed` (le cloud a refusé).
- `status` par tête : `pending` → `applied` | `mismatch` | `unreachable` | `unverified`.
- Vérification : pour le mode, DP 172 au rafraîchissement suivant ; pour le programme, lecture dans la tête par
  le tunnel local **si le repli local est activé**, sinon `unverified`.
- Les lots sont gardés en mémoire (les 50 derniers), pas persistés.

## 4. Appels cloud (couche `api/`)

Tous passent par `CloudClient._request(api, version, body)`. Formes relevées sur l'app et rejouées en réel.

### 4.1 Programme hebdomadaire

Corps commun : `{"devId": R, "gwId": G, "pid": <product id>, "resId": R, "resType": T}`.

| Cible | `R` (= `devId`/`resId`) | `G` (= `gwId`) | `T` (= `resType`) |
|---|---|---|---|
| Pièce | `group_id` (chaîne) | `group_id` (= `R`) | 2 |
| Tête isolée | `devId` | `meshId` (le `devId` de la passerelle de la tête) | 1 |

Pour une tête isolée, `gwId` est le **`meshId`** (la passerelle), **pas** le `devId` de la tête : c'est la
forme relevée sur l'application et **rejouée en réel**, implémentée par `_resolve_target` dans
`api/client.py` (`gw_id = dev.mesh_id or devId`, avec repli sur le `devId` si le `meshId` manque). Le code
reste la référence ; ce tableau a été aligné sur lui le 17/11/2026 (une version antérieure du contrat
indiquait `gwId = devId` pour la tête isolée). Réserve : la voie « tête isolée » a été relevée sur l'app
mais pas encore éprouvée bout-en-bout en réel (les essais du 16/11/2026 portaient sur des pièces) — à
confirmer lors d'un essai sur une tête non groupée.

| Opération | API | Version | Corps (en plus du corps commun) |
|---|---|---|---|
| Lire | `tuya.m.custom.wkf.week.timer.list` | 1.0 | — |
| Effacer un jour | `tuya.m.custom.wkf.week.timer.delete` | 1.0 | `loops` |
| Créer un jour | `tuya.m.custom.wkf.week.timer.create` | 1.0 | `loops`, `periods` |

- `loops` : masque de 7 caractères, **dimanche en premier** : `1000000` = dimanche, `0100000` = lundi, …
  `0000001` = samedi. Un jour par appel.
- `periods` : **chaîne JSON** d'une liste `[{"startTime": "08:30", "endTime": "17:30"}]`.
- Réponse de la lecture : liste (parfois sous la clé `data`) de
  `{"loops": "0100000", "loopData": [{"startTime": 510, "endTime": 1050, "mode": "at_home"}]}` — heures en
  **minutes depuis minuit**, `mode` `at_home` = plage de confort. Un jour absent de la réponse est vide.
- Écrire un jour = `delete` puis, s'il reste des plages, `create`. Un jour vide = `delete` seul.

### 4.2 DP d'une pièce

`s.m.dev.group.dp.publish` v1.0, corps `{"dps": "<chaîne JSON>", "groupId": <entier>}`.

| Usage | `dps` | Effet réel |
|---|---|---|
| Consigne confort | `{"118": 210}` (dixièmes de °C) | appliqué ; puis R3 |
| Consigne réduit | `{"109": 140, "119": 140}` (les deux ensemble, comme l'app) | accepté ; puis R3 |
| Mode manuel | `{"2": "manual"}` | appliqué, **efface le programme** (R4) |
| Fin du retour au programme | `{"2": "at_home"}` | affichage seulement (R4, R5) |
| Réglages de pièce | `{"1": bool}` pré-chauffage, `{"30": bool}` verrou, `{"116": bool}` fenêtre, `{"18": 210}` borne haute | appliqué en 5 à 10 min |

Une tête isolée se règle par `tuya.m.custom.wkf.settings.change` (déjà dans `async_write_setting`) ; cette voie
s'est montrée peu fiable sur les têtes groupées.

### 4.3 État

`tuya.m.my.group.device.list` v1.0 (paramètre `gid`) donne par appareil `dps["2"]` (mode affiché), `dps["172"]`,
`dps["149"]`, `dps["118"]`, `dps["119"]`. Aucun appel supplémentaire n'est nécessaire pour `HeadState`.

## 5. Ce que l'intégration expose

### 5.1 Appareils et entités

- Un **appareil par pièce**, avec : `binary_sensor` « programme actif » (vrai si toutes ses têtes ont
  `schedule_active`), `number` consigne confort et consigne réduit (écriture = publication du DP + réécriture
  du programme, R3), `sensor` « têtes incohérentes » (nombre).
- Par tête : `binary_sensor` « programme actif » (DP 172, catégorie diagnostic).
- **Thermostat (`climate`)** : pas de préréglage `confort` / `réduit` / `vacances` relié au DP 2 (R5).
  Écriture de consigne **durable au niveau pièce** : dans les modes `confort` (`at_home`) et `réduit`
  (`leaving_home`), changer la température publie la consigne sur le groupe puis réécrit un jour du
  programme (R3) — même chemin que les entités `number` ci-dessus (`async_set_room_setpoint`, prouvé en
  réel le 16/11/2026, PR #10). Hors de ces modes, ou pour une tête non groupée, l'écriture échoue
  proprement (erreur plutôt que valeur mensongère). Les entités `number` de la pièce offrent le même
  réglage, par pièce ; le thermostat reste l'accès par tête.

### 5.2 Actions (services)

Domaine `danfoss_ally_cloud`. Les actions d'écriture **refusent un utilisateur non administrateur**
(`Unauthorized`). Toutes prennent `config_entry_id` quand plusieurs comptes sont configurés.

| Action | Champs | Réponse | Effet |
|---|---|---|---|
| `get_rooms` | — | `{"rooms": [Room]}` | lecture |
| `get_schedule` | `target`, `refresh` (bool, défaut faux) | `Schedule` | lecture (cache, ou cloud si `refresh`) |
| `set_schedule` | `target`, `days` (un ou plusieurs jours) | `WriteJob` | valide R1, écrit les jours donnés |
| `copy_schedule` | `source`, `targets` (liste), `days` (optionnel) | `{"jobs": [WriteJob]}` | recopie le programme |
| `restore_schedule` | `target` | `WriteJob` | R4 : réécrit les 7 jours puis publie `at_home` |
| `get_write_job` | `job_id` | `WriteJob` | lecture |

`set_schedule` ne touche que les jours fournis ; les autres restent tels qu'ils sont dans le cloud.

### 5.3 Commandes WebSocket (pour l'interface)

| Type | Champs | Réponse | Droits |
|---|---|---|---|
| `danfoss_ally_cloud/info` | — | `{"version": "<version de l'intégration>", "local_enabled": bool, "is_admin": bool}` | tous |
| `danfoss_ally_cloud/rooms` | `entry_id` (optionnel) | `{"rooms": [Room]}` | tous |
| `danfoss_ally_cloud/schedule/get` | `target`, `refresh` | `Schedule` | tous |
| `danfoss_ally_cloud/schedule/validate` | `days` | `{"valid": bool, "errors": [Erreur], "transitions": {"mon": 3, …}}` | tous |
| `danfoss_ally_cloud/schedule/set` | `target`, `days` | `WriteJob` | administrateur |
| `danfoss_ally_cloud/schedule/restore` | `target` | `WriteJob` | administrateur |
| `danfoss_ally_cloud/jobs/subscribe` | — | événements `WriteJob` à chaque changement | tous |

Les commandes WebSocket et les actions partagent la même implémentation : une seule fonction par opération.

### 5.4 Erreurs

Forme : `{"code": "…", "message": "…", "day": "mon" | null}`. Le message est traduit ; le code est stable.

| Code | Cas |
|---|---|
| `invalid_time` | heure hors `00:00`–`23:59` ou mal formée |
| `empty_or_reversed` | `start` ≥ `end` |
| `overlap` | deux plages se chevauchent |
| `too_many_transitions` | R1 : décompte > 6 |
| `unknown_target` | pièce ou tête inconnue |
| `grouped_device` | tête groupée visée directement : viser sa pièce |
| `not_admin` | écriture par un utilisateur non administrateur |
| `cloud_refused` | le cloud a refusé l'appel |
| `session_expired` | session à renouveler (ré-authentification en cours) |

## 6. Interface embarquée

- Sources dans `frontend/` à la racine du dépôt (TypeScript + Lit). Le build produit **un seul fichier**
  `custom_components/danfoss_ally_cloud/frontend/danfoss-ally-cloud.js`.
- L'intégration sert ce dossier à l'URL `/danfoss_ally_cloud/frontend/` (`async_register_static_paths`) et
  déclare la ressource Lovelace `…/danfoss-ally-cloud.js?v=<version>` (tableaux de bord en mode stockage ; en
  mode YAML, l'utilisateur l'ajoute à la main — à documenter).
- Enregistrement dans `async_setup` (une fois par instance), jamais dans `async_setup_entry`.
- Au chargement, l'interface compare sa version (injectée au build) à `danfoss_ally_cloud/info` ; si elles
  diffèrent, elle propose de recharger la page.
- Éléments déclarés : `danfoss-ally-schedule-card` (carte Programme) ; plus tard `danfoss-ally-room-card` et
  le panneau `danfoss-ally-panel`.
- L'interface n'appelle **que** les commandes de la section 5.3 et les entités ; jamais le cloud.
- Un utilisateur non administrateur (`is_admin` faux) voit la carte en lecture seule.

## 7. Hors contrat pour l'instant

Vacances (écriture non connue), dérogation ponctuelle hors modes confort / réduit (R5), gestion des
pièces (créer, renommer, attacher), relais chaudière, firmware, panneau complet. Chacun fera l'objet
d'un ajout à ce contrat. (La consigne durable de pièce, elle, est désormais au contrat — voir §5.1, PR #10.)
