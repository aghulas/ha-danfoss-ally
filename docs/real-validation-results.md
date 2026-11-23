# Real-hardware validation — results

Session interactive du 2026-11-18, Rémi présent (app Danfoss iPhone = vue de référence).
Suit `docs/real-validation-plan.md`. Claude lit HA (`homeassistant-admin`, `danfoss-ally`) + MQTT
(`mqtt`), Rémi lit l'app. Pass = cohérence des trois vues.

## Prérequis §0

| Prérequis | État |
|---|---|
| Intégration `danfoss_ally_cloud` chargée (Pi <pi-ip>) | ✅ `loaded` |
| deviceId distinct du connecteur MCP (coexistence, PR #59) | ✅ `distinct_device_id = true`, les deux sessions tiennent |
| MQTT : mode / source / base topic | ✅ activé en session : `mqtt_mode = discovery` (était `off`), `mqtt_source = cloud`, base `danfoss_ally_cloud` |
| Broker Mosquitto joignable | ✅ <pi-ip>:1883, mosquitto 2.1.2 |
| `enable_local` | ✅ true (préchauffe testable) |
| `enable_vacation_write` | ⛔ false — vacances gaté (W-6 / CIBLE 2 non testé) |
| `enable_head_unbind` | ⛔ absent des options — §2b non exposé |

Écriture faite : `mqtt_mode off → discovery` (lot `20261118-200821-RAqA`, accord explicite de Rémi).

### Structure de publication confirmée (discovery, source cloud)
- État : `danfoss_ally_cloud/<devId>` → JSON `{temperature, setpoint, battery, valve_opening, window_open}`
- Disponibilité : `danfoss_ally_cloud/<devId>/availability` → `online` / `offline`
- 198 topics (2 / appareil). Configs discovery sous `homeassistant/<composant>/danfoss_<devId>_<clé>/config`.
- ⚠️ Faux ami : 660 topics `danfoss_l/…` (+ entités `*_local`) = **bridge local du projet pilote**
  (`sainte-marie-pilote/config/ha/danfoss/bridge.py`), **pas** notre intégration. Écartés.

## Tête de test

- **C-1 Salle ASH** — devId `<devId C-1>`, passerelle C-1.
- Entités de notre intégration : `climate.c_1_salle_ash_2`, `sensor.c_1_salle_ash_temperature_2`,
  `sensor.c_1_salle_ash_battery_2`, `sensor.c_1_salle_ash_valve_opening_2`,
  `sensor.c_1_salle_ash_fault_code`, `binary_sensor.c_1_salle_ash_window`,
  `binary_sensor.c_1_salle_ash_online`, `switch.c_1_salle_ash_child_lock`,
  `switch.c_1_salle_ash_open_window_detection_2`, `switch.c_1_salle_ash_pre_heating`.
- Entités MQTT auto-créées (discovery) : `sensor.c_1_salle_ash_temperature_3`,
  `…_battery_3`, `…_valve_opening_3`, `sensor.c_1_salle_ash_setpoint`, `binary_sensor.c_1_salle_ash_window_2`.
- (Coexistent aussi les entités MTrab `danfoss_ally` sans suffixe, et les entités `*_local` du bridge.)
- type : « Danfoss Ally™ Radiator Thermostat ». Firmware : ZigBee Module **0.2.2** ;
  Product Version 1.0.0 ; RSSI **−75 dBm**.

## §1 — Lecture (R-1), 2026-11-18 ~20:12

| Grandeur | App (réf.) | HA `danfoss_ally_cloud` | MQTT discovery | Verdict |
|---|---|---|---|---|
| Température mesurée | ~18,7 | 18,7 (`current_temperature` / `sensor…_temperature_2`) | `temperature` 18,7 | ✅ |
| Consigne | **14** (réduit) | attribut `setpoint` **21** (= comfort) ; `setpoints`={comfort 21, setback 14, manual 8, pause 5, holiday 14.5} ; `mode`=setback | `setpoint` **21** | ❌ **MISMATCH** |
| Vanne / chauffe | **ne chauffe pas** | `valve_opening` 1 % ; **`hvac_action` = heating** | `valve_opening` 1 % | ❌ **MISMATCH** (hvac_action) |
| Batterie | — | 68 % | `battery` 68 | ✅ |
| Fenêtre ouverte | — | `off` | `window_open` false | ✅ |
| En ligne | — | `on` | availability `online` | ✅ |
| Défaut | — | `none` | (non publié) | ✅ |

### Anomalie trouvée (R-1) — racine unique
La consigne « active » exposée par l'intégration ne tient **pas compte du mode/créneau courant** :
en mode `setback`, elle devrait valoir `setback` (14), mais l'intégration publie `comfort` (21)
à la fois dans l'attribut `setpoint` du climate **et** dans le JSON MQTT `setpoint`.
Cette même erreur contamine `hvac_action` : 18,7 °C comparé à 21 (confort) → `heating`, alors qu'avec
la consigne active réelle (14) la pièce est au-dessus de consigne → devrait être `idle`/`off` (l'app
confirme : ne chauffe pas, vanne 1 %).

→ **Racine confirmée par les statuts bruts** : le cloud expose déjà les bonnes valeurs, l'intégration
ne les utilise pas.
- `OccupiedSetpoint = 1400` (= 14,0 °C) = consigne active réelle → **à publier comme `setpoint`**,
  au lieu de `temp_set` / `at_home_setting` (210 = confort).
- `work_state = NoHeat` (et `pi_heating_demand = 1`) = état de chauffe réel → **`hvac_action` doit
  suivre `work_state`**, au lieu d'être recalculé localement (18,6 vs confort 21 → heating à tort).
- Autres codes utiles : `mode = leaving_home` (réduit), `SetpointChangeSource = Schedule`,
  `at_home_setting=210`, `leaving_home_setting=140`, `holiday_setting=145`, `pause_setting=50`.

À corriger dans le coordinator/climate + `mqtt_publisher` (hors de cette session de validation).
Impacte directement W-1 (écriture confort) : à interpréter en conséquence.
→ Session correctif lancée : `fix-consigne-active-hvac` (task_8953a1cb), branche dédiée.

## §1 — Lecture R-3 (demande de chaleur / vanne), 2026-11-18 ~21:06

Rémi monte la consigne de C-1 Salle ASH à **21** (max = borne haute `upper_temp`=210 de la tête)
en mode manuel. Baseline avant : vanne 1 %, `pi_heating_demand` 1, `work_state` NoHeat.

| Vue | Vanne | pi_heating_demand | mode / consigne active | work_state |
|---|---|---|---|---|
| Cloud **route individuelle** (`danfoss_appareil`) | **82 %** | **82** | manuel / 21 (`OccupiedSetpoint` 2100) | **Heat** |
| Cloud **route liste/bulk** (`danfoss_appareils` rafraichir) | **1 %** | — | reduit / 14 (`consigne_active`) | — |
| HA `sensor…_valve_opening_2` | **1,0 %** (figé, maj 20:10) | — | — | — |
| MQTT `valve_opening` | **1,0 %** (figé) | — | — | — |

### Anomalie trouvée (R-3) — fraîcheur de la source
Le coordinator poll **`async_list_devices`** (route liste/bulk, [coordinator.py:57]) qui **retarde
fortement** : plusieurs minutes après le changement, et malgré `rafraichir=true`, elle montre encore
l'état du programme (reduit / 14 / vanne 1 %), alors que la route **individuelle** (et la tête
physique) sont à manuel / 21 / vanne **82 %**. Le connecteur MCP, lui, lit la route individuelle →
frais.
Conséquence : les valeurs à variation rapide (vanne, demande) — et les **round-trips d'écriture**
(W-1…W-5) — ne se reflètent pas en temps utile dans l'intégration ni dans le MQTT.
→ Distinct du bug de mapping R-1. Piste : pour les têtes récemment commandées, interroger la route
individuelle (plus d'appels API) ou accepter la latence et la documenter. À arbitrer (charge API vs
réactivité), hors de cette session.

**Précision (session correctif, capture Frida du SDK Tuya) :** le payload bulk
`tuya.m.my.group.device.list` **contient bien** DP 171 (`OccupiedSetpoint`, centièmes /100) et DP 3
(`work_state` Heat/NoHeat), à côté de DP 2/16/118/119/170. Donc le **fix de mapping R-1 fonctionne
sur le bulk** (pas besoin de la route individuelle pour la *sélection* de la consigne active). La
capture montre même le cas R-1 : tête at_home, DP 171=2100, DP 3=NoHeat, vanne DP 170=2.
⚠️ À ne pas confondre : la **présence** de ces DP dans le bulk ≠ leur **fraîcheur**. R-3 reste un
problème de fraîcheur de l'endpoint `device.list` (valeurs retardées vs la route individuelle),
indépendant du mapping. Les deux sont nécessaires pour une bonne réactivité.

Verdict R-3 : **vanne/demande montent bien côté tête réelle + cloud individuel (82 %)**, mais
**mismatch HA/MQTT** par latence de la route bulk. À reconfirmer en relisant plus tard si le bulk
rattrape.

## §1 — Lecture R-2 (détection fenêtre), 2026-11-18

**Observation de validation :** l'**app Danfoss iPhone n'affiche pas** le flag « fenêtre ouverte »
par tête. Donc la vue de référence n'a **pas de contrepartie** pour `window_open` : on ne peut pas
valider cette ligne contre l'app. Le flag existe côté cloud (`window_state` dans le status brut) et
est exposé par HA (`binary_sensor.c_1_salle_ash_window`) et MQTT (`window_open`). Validation repliée
sur cloud (route individuelle) ↔ HA ↔ MQTT, sans la jambe app.

**Reporté à demain matin (2026-11-19) :** à l'ouverture de l'école, l'aération fait naturellement
passer **plusieurs vannes** en fenêtre ouverte — test R-2 opportuniste sans manip, sur plusieurs
têtes, en comparant cloud ↔ HA ↔ MQTT. À grouper avec la préchauffe §3 (P-1…P-3), qui se lit aussi
sur les courbes du matin, et avec un re-contrôle de la latence bulk (R-3 : voir si HA/MQTT ont
rattrapé la vanne).

### R-2 — résultat 2026-11-19 (aération matinale) ✅

À 08:06, `danfoss_sante` signale **4 têtes** en fenêtre ouverte (aile A) : A-0 Secrétariat
(`bf74…vzld`), A-0 A03 (`bf3b…0w1`), A-0 A02 #1 (`bfeaab…qzsr`), A-1 Escalier Aile (`bfd7…oiby`).
MQTT `window_open` = **true** pour les 4 → cohérence cloud ↔ MQTT **4/4** (vanne 1 % partout, chauffe
coupée). Version en place = **pré-fix** (main non déployé).

**Transition captée (sans manip)** entre 08:06 et 08:14, fin d'aération :

| Tête | window_open (MQTT) | vanne | |
|---|---|---|---|
| A-0 A02 #1 | true → **false** | 1 % → **98 %** | fenêtre refermée, chauffe reprise |
| A-0 A03 | true → **false** | 1 % → 56 % | idem |
| A-1 Escalier Aile | true → **false** | 1 % → 12 % | idem |
| A-0 Secrétariat | true (inchangé) | 1 % | reste ouverte (témoin) |

Confirmation **route individuelle fraîche** sur A02 #1 : `fenetre_ouverte=false`,
`window_state=close`, `ouverture_vanne=98`, `pi_heating_demand=98`, `work_state=Heat` → **concorde
avec MQTT**.

**Verdict R-2 : ✅** le flag bascule `true→false` **et** la vanne se rouvre, cohérent entre
l'intégration (MQTT) et le cloud frais. Pas de jambe app (flag non affiché — établi la veille).

**R-3 observé en direct :** à 08:14 `danfoss_sante` (route **bulk**) liste **encore les 4** en fenêtre
ouverte, dont A02 #1 déjà refermée selon la route individuelle + MQTT. Illustration nette de la
latence de `device.list` → pour une transition live, se fier à la route **individuelle + MQTT**, pas
à `danfoss_sante`. (PR #66, fraîcheur ciblée, mergée mais gatée off / non déployée.)

**Note consigne :** `setpoint` MQTT = 21 partout n'est **pas** une preuve du défaut R-1 ce matin :
`OccupiedSetpoint` = 2100 (21 °C), le créneau actif du matin **est** 21 (confort/at_home). Le défaut
R-1 ne se distingue que quand actif ≠ confort (cf. C-1 la veille : actif 14 vs confort 21).

## §1 — Ampleur du bug R-1 sur la flotte (tests autonomes, 2026-11-18 ~21:51)

Comparaison **consigne active (cloud, `consigne_active`)** vs **MQTT `setpoint` publié**, sur un
échantillon discriminant de 8 têtes (modes et consignes variés) :

| Tête | mode | consigne active (cloud) | MQTT `setpoint` | verdict |
|---|---|---|---|---|
| C-1 Salle ASH | réduit | 14 | 21 | ❌ |
| B-0 Clocher | réduit | 5 | 12 | ❌ |
| C-0 Sanitaire Garçons | réduit | 7 | 18 | ❌ |
| E-0 Sanitaires Filles | réduit | 12 | 18 | ❌ |
| A-0 Secretariat | manuel | 21 | 21 | ✅ (confort = actif) |
| E-2 Local Electrique | manuel | 5 | 21 | ❌ |
| E-1 CTA | réduit | 5 | 5 | ✅ (confort = actif) |
| A-0 Hall Garderie | réduit | 14 | 21 | ❌ |

**Conclusion** : le MQTT publie systématiquement la consigne **confort/at_home** (valeur propre à
chaque pièce : 21, 18, 12…), jamais la consigne **active**. Coïncide uniquement quand confort = actif.
Au relevé du soir, **~95 des 99 têtes sont en mode `reduit`** → le mismatch R-1 touche **quasiment
toute la flotte**. Confirme un bug déterministe (sélection de consigne), pas un cas isolé. Sert de
**base de re-vérification après merge de PR #65**.

## §1 — Re-validation R-1 après déploiement du correctif (2026-11-19 ~08:45) ✅

**Déploiement** : `danfoss_ally_cloud` déployé sur le Pi à 08:27:50 (lot `20261119-082750-bAIc`,
outil `ha_composant_deployer_preparer` du connecteur, source = branche `docs/real-validation-plan`
= commit `67b6c1e`, code R-1 identique à PR #65). Redémarrage du cœur lancé à 08:30
(tâche `20261119-083025-w8bv` : config ✅, redémarrage ✅ 141 s, dernière étape « HA reparti »
❌ `state = None` après 600 s — **faux négatif du vérificateur** : HA `running`, intégration
`loaded`, nouveau code actif). **Non présents sur le Pi** : #66 (R-3), #63/#64 (unbind) — gatés off.

**Piège de méthode** : les têtes de test évidentes n'étaient **pas discriminantes** ce matin —
C-1 et B-0 Clocher sont en créneau confort (`OccupiedSetpoint` = confort ; B-0 = 12 °C et
`work_state=Heat`). Le `danfoss_appareils` du connecteur annonçait B-0 « réduit / 5 » à 08:36 :
**périmé** (route bulk). Têtes discriminantes choisies dans le relevé cloud brut de 08:43
(`OccupiedSetpoint` ≠ `at_home_setting` **et** `work_state` en désaccord avec temp vs confort) :

| Tête | état cloud (08:43) | MQTT `setpoint` hier | MQTT `setpoint` maintenant | HA `hvac_action` |
|---|---|---|---|---|
| E-2 Local Electrique | manuel, actif **5**, confort 21, 14,4 °C, NoHeat | **21** ❌ | **5** ✅ | **idle** ✅ |
| E-2 Local Menage | manuel, actif **5**, confort 21, 14,2 °C, NoHeat | — | **5** ✅ | — |
| E-2 CTA | manuel, actif **5**, confort 21, 14,1 °C, NoHeat | — | **5** ✅ | — |

**Verdict R-1 : ✅** consigne publiée = consigne active (DP 171), `hvac_action` = `work_state`.

Remarques (non bloquantes, suites possibles) :
- Attribut HA `setpoints.setpoint` = **21** : c'est la table brute par DP (`_SETPOINT_DPS`, clé
  `setpoint` = DP 16 / `temp_set`), pas la consigne active → nom trompeur.
- Le climate **tête** a `supported_features: 0` → HA n'expose pas `temperature` : la consigne
  active n'est visible dans HA que via l'entité MQTT `sensor.<tête>_setpoint`.
- Vérificateur de redémarrage du connecteur : `state = None` sur 600 s alors que HA tournait.
- Origine du redémarrage de 08:30 non établie (ni la session de validation, ni le connecteur
  d'après leurs rapports).

## Déploiement de `main` complet (2026-11-19 ~08:40–08:58) ✅

- `main` (`f9827b5` : R-1 #65, R-3 #66, unbind #63/#64) **posé sur le Pi vers 08:4x** par la session
  « Point d'avancement projet » (accord direct de Rémi), depuis un extrait propre de `origin/main`.
  Le confirm a **expiré côté client** : les fichiers ont bien été poussés (jeton ensuite « déjà
  utilisé »), mais **aucune entrée au journal** du connecteur → dépôt non tracé, identifié
  après coup par comparaison des empreintes (le lot de 08:27 = `67b6c1e` ; le Pi = `main`, 41
  fichiers identiques ; un aperçu depuis `67b6c1e` proposait ~14).
- **Redémarrage du cœur** 08:55:15 (tâche `20261119-085515-65CR`, accord de Rémi) : config ✅ 34 s,
  redémarrage ✅ 155 s. Juste avant, re-vérifié que le disque = `main` (aucun dépôt intercalé).
  Le confirm a lui aussi expiré côté client, mais la tâche détachée a tourné.
- **Preuve que `main` est chargé** : le formulaire d'options expose désormais
  `post_command_refresh` (R-3) et `enable_head_unbind` (absents la veille), tous deux à `false`.
- Origine du redémarrage de 08:30 : très probablement une autre session (sauvegarde « Avant
  ha-weishaupt 0.3.0rc2 » 08:27:16, options eBUSd 08:27:34).

- **Option R-3 activée** : `post_command_refresh` false → **true** à 09:08 (lot
  `20261119-090839-FLdl`, accord de Rémi), autres options inchangées. Première tentative (08:59)
  abandonnée sans effet : en attente du verrou tenu par le vérificateur de redémarrage défaillant.
  Intégration rechargée → `loaded` ; MQTT toujours correct (E-2 Local Electrique `setpoint` 5,
  `online`). R-3 reste **à valider** par un aller-retour d'écriture (W-x).

## §2 — W-1 (consigne confort) + validation R-3, 2026-11-19 ~09:21 ✅

Pièce test **E-2 Circulation** (groupe `13448871`, pid `03wvrwpv`, 2 têtes, couloir ; C-1 Salle
ASH n'a pas d'entité de pièce écrivable). Levier : `climate.set_temperature` sur le climate de
**pièce** `climate.e_2_circulation` (mode confort → consigne durable `at_home` du groupe) — c'est
ce chemin qui appelle `note_commanded` (R-3). Écriture 21 → **20,5** à **09:20:54** (lot
`20261119-092054-kxrc`, accord de Rémi). Pièce à ~21,7 °C, sans effet perceptible.

| Instant | Cloud individuel (#1/#2) | HA climate pièce | MQTT `setpoint` (2 têtes) | Route bulk (connecteur) |
|---|---|---|---|---|
| T0 + ~10 s | `at_home_setting` 205 ✅, `OccupiedSetpoint` encore 2100 | `setpoints.comfort` 20,5, `temperature` 21 | 21 / 21 | — |
| ~09:22–09:23 | `OccupiedSetpoint` **2050** | `temperature` **20,5** (maj 09:22) | **20,5 / 20,5** ✅ | consigne_active **21** (périmé) |

- **W-1 ✅** : la consigne confort écrite apparaît côté cloud, HA et MQTT.
- **W-7 (W-1) ✅** : MQTT reflète la nouvelle consigne active ~2 min après l'écriture.
- **R-3 ✅** : l'intégration reflète le changement en ~1–2 relevés (scan 90 s), alors que la route
  bulk est encore à 21 au même moment — le recouvrement par la route individuelle fonctionne. (La
  veille, sans R-3, un aller-retour sur C-1 n'avait jamais été reflété.)
- **R4 ✅** : programme hebdomadaire de la pièce relu après écriture = **identique** à l'état de
  référence (lun/mar/jeu/ven 08:30–17:30 confort ; mer/sam/dim vides). À recouper dans l'app.
- Délai propre à la tête : la consigne active (DP 171) ne bascule qu'après la synchronisation de
  la tête (`at_home_setting` écrit immédiatement, `OccupiedSetpoint` ~1–2 min plus tard).
- Incohérence de code relevée : l'entité `number` confort/réduit (`DanfossRoomSetpoint`) fait la
  même écriture **sans** `note_commanded` → pas de R-3 sur ce chemin.
- **Remise en état** : retour 20,5 → **21** à 09:23:54 (lot `20261119-092354-cQxO`, accord de
  Rémi). À ~09:26 : cloud `at_home_setting` 210 / `OccupiedSetpoint` 2100, HA cible 21 (maj
  09:25), MQTT 21 / 21, programme toujours identique à la référence. Second aller-retour R-3 ✅
  en ≤ ~2 min.

## §2 — W-2 (consigne réduit), 2026-11-19 ~09:42 ✅ (avec un effet transitoire)

Même pièce (E-2 Circulation). Toutes les pièces sont en créneau confort de 08:30 à 17:30 → pas de
pièce en réduit pour faire basculer la consigne active ; W-2 fait via l'entité
`number.e_2_circulation_setback_setpoint` 14 → **13,5** (chemin sans R-3).

- 1er essai (09:28:35) **perdu sans effet** : en attente du verrou tenu par un redémarrage du cœur
  lancé par une autre session (déploiement ha-weishaupt 0.3.0rc3, 09:27:58), abandon à 09:33:35.
  Collision d'écritures entre sessions sur le Pi, signalée.
- 2e essai **09:42:15** (lot `20261119-094215-bTp7`, accord de Rémi).

| Instant | Cloud (#1 et #2) | HA `number` | MQTT `setpoint` |
|---|---|---|---|
| T0 + ~15 s | `leaving_home_setting` **135** ✅ ; ⚠️ `OccupiedSetpoint` **1350**, `SetpointChangeSource` = **Externally** (mode `at_home`, `temp_set` 210) | **13,5** ✅ | 21 |
| ~09:45 | `leaving_home_setting` 135 ; `OccupiedSetpoint` **2100**, source **Schedule** | 13,5 | 21 ✅ |

- **W-2 ✅** : consigne réduit écrite (cloud + HA).
- **MQTT ✅** : reste 21 (pièce en confort) ; l'excursion transitoire n'a pas été publiée (bulk).
- **R4 ✅** : programme identique à la référence.
- ⚠️ **Comportement non documenté** : publier le réduit (`{"109": …, "119": …}`) fait appliquer
  **immédiatement** la valeur de réduit comme consigne courante (source `Externally`), même en
  créneau confort ; la réécriture du programme (R3) la ramène au créneau ~1–3 min plus tard. Pas
  d'effet thermique observé (couloir à ~21,5 °C). À ajouter au contrat (§4.2, ligne « Setback
  setpoint ») ; piste : DP 109 = consigne « maintenant », DP 119 = réglage réduit.
- **Remise en état** : réduit 13,5 → **14** à 09:46:06 (lot `20261119-094606-5l1s`, accord de
  Rémi). À ~09:49 : les deux têtes `leaving_home_setting` 140, `OccupiedSetpoint` 2100 (source
  Schedule), programme identique. (HA indisponible au même moment : nouveau déploiement
  ha-weishaupt 0.3.0rc4 + redémarrage du cœur à 09:48 par l'autre session.)

## §2 — W-3 (verrouillage enfant, DP 30), 2026-11-19 ~09:59 ❌ non appliqué

Tête **isolée** C-1 Salle ASH (aucune pièce ; les switches de l'intégration écrivent par tête via
`tuya.m.custom.wkf.settings.change`, resType 1, `gwId = meshId`). Référence : `child_lock` true
(cloud, HA `on`, app « activé »). `switch.turn_off` à **09:59:01** (lot `20261119-095901-ZtnM`,
accord de Rémi). Lock du Pi vérifié libre avant (redémarrage ha-weishaupt terminé à 09:51).

| Instant | Cloud `child_lock` | HA switch | App (Rémi) |
|---|---|---|---|
| T0 + ~10 s | true | on (maj 09:50) | — |
| T0 + ~3 min | true (tête active : 20,9 °C, Heat, vanne 39 %) | on | **activé** |
| T0 + ~10 min | true (21 °C, vanne 36 %) | on | — |

- **W-3 ❌** : requête acceptée (service `ok`, aucune erreur levée), **jamais appliquée** à la tête
  au bout de 10 min (au-delà du délai R7 de 5–10 min pour les réglages).
- **Cohérence ✅** : les trois vues restent alignées sur l'état réel (verrouillé) — l'intégration
  ne ment pas (pas d'état optimiste).
- Rejoint l'avertissement du code (`async_write_setting` : « effet réel à confirmer ; certains
  réglages par ce chemin n'atteignaient pas toutes les têtes isolées ») : premier point de mesure
  en réel **négatif** pour l'adressage `gwId = meshId` sur un réglage de tête isolée.
- Rien à remettre en état ; **à revérifier plus tard** (application tardive possible → re-verrouiller).
- W-4 (détection fenêtre, DP 116) : le **switch** cloud emprunte le même chemin ; le **service**
  `set_window_detection` passe, lui, par le tunnel local.

### W-3 — diagnostic (2026-11-19 ~10:13–10:24)

Hypothèse : depuis PR #35 (`c6511a6`), l'intégration écrit les réglages avec **`gwId = meshId`**
(justifié par l'essai C0b… qui portait sur une écriture de **programme**), alors que le connecteur
MCP utilise **`gwId = devId`** (validé une fois en réel : orientation d'écran sur tête isolée).

Test discriminant (accord de Rémi) : même écriture DP 30 → false sur C-1 par le connecteur
(`danfoss_tuya_reglage_*`, `gwId = devId`) à ~10:13 ; requête acceptée (`reponse: true`).

| Instant | Cloud `child_lock` | Tête active ? |
|---|---|---|
| T0 | true | oui |
| T0 + ~4 min | true | oui (vanne 36 %) |
| T0 + ~10 min | **true** | oui (20,9 °C, Heat, vanne 35 %) |

**Conclusion** : échec aussi avec `gwId = devId` → **l'adressage n'est pas la cause**.
`tuya.m.custom.wkf.settings.change` n'applique pas (ou pas de façon fiable) les réglages d'une tête
**isolée** — cohérent avec le constat du connecteur du 15/11 (DP 116 : 0/7 têtes isolées en 8 min).
Ce qui marche : le réglage **par pièce** (`s.m.dev.group.dp.publish`, têtes groupées) et le
**tunnel local**. La lecture locale de C-1 n'expose pas le verrouillage enfant (pas de preuve en
tête possible pour DP 30).

Conséquences / suites pour l'intégration :
- les switches `child_lock` / `window_detection` des **têtes isolées** ne doivent pas s'afficher
  comme écrivables tant que ce chemin n'est pas prouvé (principe « indisponible plutôt que
  mentir ») ; pour la détection de fenêtre, router vers le tunnel local ;
- pour les **têtes groupées**, écrire le réglage par la pièce (group publish, prouvé) au lieu de
  `settings.change` par tête ;
- le contrat §4.2 / l'avertissement de `async_write_setting` sont à mettre à jour avec ce résultat.
Rien à remettre en état (aucune écriture appliquée) ; vérifier plus tard qu'aucune ne s'applique
en différé.

## §2 — W-4 (détection fenêtre, DP 116) par le tunnel local, 2026-11-19 ~10:22 ✅

Tête isolée C-1 Salle ASH (passerelle C-2). Service de l'intégration
`danfoss_ally_cloud.set_window_detection {target: {type: device, id}, enabled: false}` — écrit par
le **tunnel local** (pas `settings.change`). Appelé via le Supervisor : **pas** de refus
`not_admin`. 10:22:44, lot `20261119-102244-bxWt` (accord de Rémi) ; réponse en 0,1 s.

| Vue | Avant | Après | Délai |
|---|---|---|---|
| Tête (lecture locale, fait foi) | `detection_fenetre` true | **false** | immédiat (relu à T0 + ~20 s) |
| Cloud (route individuelle) | `window_toggle` true | **false** | < 1 min |
| HA `switch…_open_window_detection_2` | on | **off** (maj 10:25) | ~2,5 min |
| App | (Rémi) | à confirmer | |

- **W-4 ✅** par le chemin local, là où le chemin cloud (W-3, `settings.change`) n'applique rien.
- La tête **remonte** ensuite le réglage au cloud : le switch HA (qui lit le cloud) suit seul.
- Fenêtre d'incohérence ~2,5 min où le switch HA affiche encore `on` alors que la tête est `off`
  (ce chemin n'appelle pas `note_commanded` → pas de R-3 ; la route bulk rattrape).
- Le reste de la tête est inchangé (programme, consignes, réglages relus localement).
- **Remise en état** : réactivation à 10:28:35 (lot `20261119-102835-kdzN`, accord de Rémi) →
  tête `detection_fenetre` true (relu immédiatement), cloud `window_toggle` true, HA `on` (maj
  10:28, < 1 min cette fois). Contrôle W-3 au passage : `child_lock` toujours **true** (aucune des
  deux écritures `settings.change` ne s'est appliquée en différé).

## §2 — W-5 (dérogation puis retour au programme), 2026-11-19 ~10:34–10:49 ✅

Portée : le W-5 **que l'intégration expose** — `set_override` / `clear_override`, par le tunnel
local (DP 171 « consigne maintenant », jusqu'au prochain changement du programme ; **pas** de mode
manuel, donc R4 ne s'applique pas). Le scénario « manuel → `restore_schedule` (réécriture du
programme puis `at_home`) » n'est pas couvert ici (l'intégration n'expose pas le passage en manuel).

Tête isolée C-1 Salle ASH (passerelle C-2), créneau confort 21. Programme de la tête relevé en local
avant (lun/mar/jeu/ven 00:00→14, 08:30→21, 17:30→14 ; mer/sam/dim 14).

| Étape | Tête (local, fait foi) | Cloud | MQTT | HA climate tête |
|---|---|---|---|---|
| Avant | consigne 21, source 1 (programme) | `OccupiedSetpoint` 2100 | 21 | — |
| `set_override 19` 10:34:13 (lot `…QoZq`) | **19**, source 2 (externe) à T0+~20 s ; programme **identique** | **1900**, `Externally` | **19** (≤ ~3 min) | `hvac_action` idle (21 > 19) |
| `clear_override` 10:46:37 (lot `…7beW`, 4,7 s) | **21**, source 2 ; programme **identique** | **2100**, `Externally`, `work_state` Heat | **21** (≤ ~2,5 min) | — |

- **W-5 ✅** : la dérogation s'applique dans la tête en ~20 s, le retour au programme remet la
  consigne prévue (21) ; **le programme de la tête n'est jamais modifié** (relu en local).
- La source reste « externe » après `clear_override` : attendu (la dérogation vaut la consigne du
  programme et expire au prochain changement, 17:30). **À revérifier après 17:30** : retour à la
  source programme.
- **W-7 (W-5) ✅** : MQTT suit en quelques minutes ; ce chemin n'appelle pas `note_commanded` (pas de
  R-3). Le climate tête n'affiche pas la consigne (limite UX déjà relevée).
- Accès : appel via le Supervisor accepté (pas de refus `not_admin`), comme W-4.

## §3 — Préchauffe (P-1…P-3), courbes du 2026-11-19 — voir `docs/real-validation-preheat.md`

Lecture seule par une session dédiée (aucune écriture). Synthèse :
- **P-1 ✅** : 70 têtes préchauffe ON exploitables ; vanne ≥ 10 % de 52 à 448 min avant le
  créneau (médiane 252 min) ; le drapeau cloud « Pre-Heating » (MTrab) passe ON simultanément.
- **P-2 ✅ (2 têtes)** : E-0 Buanderie et E-1 Local Photocopieur (préchauffe OFF) ouvrent à 08:34
  (créneau + 4 min), sans rampe anticipée. Limite : déjà OFF avant la fenêtre → le chemin
  d'écriture switch → 0x0025 n'est **pas** validé.
- **P-3 ✅ partiel** : switch préchauffe `unavailable` tête par tête quand le tunnel ne répond pas
  (online = on, aucun ON/OFF fictif) ; coupure totale du tunnel non observée.
- Annexes : préchauffe très en avance (jusqu'à 7 h 50 ; montée en température à partir de ~06:00,
  chaufferie ?) ; entités switch orphelines à nettoyer.
- **Essai contrôlé lancé** (accord de Rémi) : préchauffe OFF sur E-1 E13 (lot
  `20261119-105755-32Oc`) et ON sur E-1 Local Photocopieur (lot `20261119-105804-07UC`), 10:58,
  ~7 s chacune par le tunnel. **Écriture switch → 0x0025 validée en réel** : relu en local aussitôt,
  E13 `pre_chauffage` true → **false** (`mode_programmation` 3 → 1), Photocopieur false → **true**
  (1 → 3), programmes et consignes inchangés ; toujours en place à ~11:04 (pas de retour arrière).
  Switches HA mis à jour seulement à **11:11** (~13 min) : l'état vient du relevé local (15 min,
  ~8 s/tête), pas d'état optimiste après écriture.
  À lire **vendredi 20/11** (créneau 08:30) : E13 doit rester fermée jusqu'à ~08:30 sans drapeau
  cloud ; Photocopieur doit ouvrir avant 08:30 avec le drapeau. Puis **remise en état** (E13 ON,
  Photocopieur OFF) après 09:00.

## Déploiement de `main` `f1cf051` (#67 + #68), 2026-11-19 ~11:14 ✅

Accord de Rémi (« Déploie immédiatement », en heures de cours). Extrait propre de `origin/main`
(worktree détaché, HEAD `f1cf051`, non sale), verrou du Pi libre. Déploiement 11:14:33 (lot
`20261119-111433-4Mnf`, +0 ~4 −32 caches, vérification conforme 41 fichiers), puis redémarrage du
cœur (confirm expiré côté client, tâche détachée exécutée). Intégration `loaded`.

- **#67 ✅** sur `climate.c_1_salle_ash_2` : `active_setpoint` 21, `temperature` 21 désormais
  exposée (`supported_features` 0 → **1**), `setpoints.temp_set` 21 + alias déprécié `setpoint`.
- **#68 ✅** (relais par bâtiment, « Hors ligne ») : contrôlé visuellement par Rémi dans le panneau
  — Hc3 sous « Batiment A - B », Hc2 sous « Batiment C - D - E - F », tous deux « Hors ligne ».

## Déploiement `1.1.0-rc1` (`b246f6d`, #69 réglages par pièce / tunnel), 2026-11-19 ~12:20

Accord de Rémi. Extrait propre du tag `1.1.0-rc1` (= `main` `b246f6d`, manifest 1.1.0, non sale),
verrou libre. Déploiement 12:20:22 (lot `20261119-122022-5Y3Z`, +0 ~5 −32 caches, conforme 41
fichiers) puis redémarrage du cœur (confirm expiré côté client, tâche exécutée).

Routage #69 vérifié sur les entités :
- C-1 Salle ASH (isolée) : `switch…_child_lock` **unavailable** ✅ ; détection fenêtre `write_path:
  local`, `write_scope: head` ✅.
- E-2 Circulation (pièce, 2 têtes) : `child_lock` `write_path: room`, `write_scope: room`,
  `room_head_count: 2` ✅.

**Écriture par la pièce (W-3 corrigé)** : `switch.turn_off` sur `switch.e_2_circulation_1_child_lock`
à 12:25:23 (lot `20261119-122523-lC9U`, accord de Rémi).
- Cloud : `child_lock` **false sur les DEUX têtes** dès T0 + ~15 s ✅ (là où `settings.change` par
  tête échouait au bout de 10 min).
- HA : switch **#2 → off** (maj 12:25) ✅, mais switch **#1 (celui actionné) encore `on`** (maj
  12:23) au même moment ⚠️ — l'entité écrite reste en retard sur sa voisine. À surveiller /
  corriger avant `1.1.0` final.
- App ✅ (Rémi : E-2 Circulation conforme). Version **1.1.0** affichée dans le panneau ✅ (Rémi).
- **Remise en état** : `switch.turn_on` #1 à 12:26:00 (lot `20261119-122600-ZwSs`) → cloud
  `child_lock` **true sur les deux têtes** immédiatement ✅. HA à 12:26 : #2 `on` ✅ mais #1 `off`
  (= valeur de l'écriture précédente) ; **#1 se recale à `on` à 12:27** (relevé suivant).
- **Constat** : l'entité **actionnée** a **une écriture de retard** pendant ~1 relevé (le
  rafraîchissement qui suit l'écriture lit sa tête avant que le cloud ne l'ait prise ; la tête
  voisine, lue au même relevé, est juste). Transitoire (~1 min), non bloquant ; à corriger de
  préférence avant `1.1.0` final (état optimiste après écriture réussie, ou relecture différée).
- **W-3 ✅ via la pièce** pour les têtes groupées ; tête isolée : verrouillage enfant indisponible
  (pas de chemin prouvé), détection fenêtre par le tunnel (W-4 ✅).

## Déploiement `1.1.0-rc2` (`50b4ed3`, #73 délai de stabilisation R-3), 2026-11-19 ~13:19 ✅

Accord de Rémi. Extrait propre du tag `1.1.0-rc2` (= `main` `50b4ed3`, manifest 1.1.0, non sale ;
seul ajout vs rc1 : #73). Déploiement 13:19:01 (lot `20261119-131901-IohO`, +0 ~2 −32 caches,
conforme 41 fichiers) puis redémarrage du cœur (confirm expiré côté client, tâche exécutée ; HA
reparti à 13:21). R-3 (`post_command_refresh`) ON.

Test (accord de Rémi) : `switch.turn_off` sur `switch.e_2_circulation_1_child_lock` (pièce, 2 têtes)
à 13:22:04 (lot `20261119-132204-IEmj`).

| Instant | Switch #1 (actionné) | Switch #2 | Cloud #1 |
|---|---|---|---|
| T0 + ~3 s | on (maj 13:21) | — | — |
| T0 + ~20 s | **off** (maj 13:22) ✅ | **off** (maj 13:22) | `child_lock` false |

- **#73 ✅** : le switch actionné concorde en ~15–20 s (délai de stabilisation), au lieu d'avoir
  une écriture de retard jusqu'au relevé suivant (constat rc1, 12:25–12:27).
- **Remise en état** : `switch.turn_on` à 13:23:01 (lot `20261119-132301-XIsj`) → à T0 + ~22 s,
  switches #1 et #2 **on** (maj 13:23), cloud `child_lock` true ✅ — même comportement dans le
  sens inverse.

## Sonde d'écoute Tuya cloud MQTT (R&D, PR #71 non mergée), 2026-11-19 ~13:48–14:04 ✅ coexistence

Accord de Rémi, une seule session sur le Pi (la session R&D s'est retirée). Code audité avant
déploiement : la sonde (`CloudMqttListener`) n'a **aucun chemin d'envoi** ; la voie d'écriture MQTT
présente dans le même commit (`CloudMqttLink`, chemin `cloud_mqtt` des switches) est **doublement
fermée** (`enable_cloud_mqtt` OFF par défaut, lien câblé à `None`). CI verte.

- `cb05109` déployé 13:48 (lot `…cEcR`) + redémarrage ; puis `3313f7f` (même code + 2 lignes de log
  du verdict, pour le lire sans les diagnostics) 13:52 (lot `…nHMa`) + redémarrage.
- Rémi ouvre l'app Danfoss sur iPhone ; option `cloud_mqtt_probe` → true à 13:58:03 (lot `…kjM6`).
- **13:59:34 — `cloud-mqtt probe: CONNACK rc=0 (Connection Accepted.)`** avec la session propre de
  l'intégration (deviceId distinct).
- **App iPhone : toujours connectée** (Rémi).
- Option → false à 14:04:16 (lot `…SPQc`) → `cloud-mqtt probe stopped (unload): connack_rc=0
  received=426 decoded=426 last_error=None` (≈ 4 min 40 d'écoute, 100 % des trames décodées).

**Verdict : connexion par SESSION** — le broker accepte la session de l'intégration en parallèle de
celle de l'app, sans éjection. La voie MQTT (lecture, et à terme écriture des réglages de têtes
isolées) est **viable** ; le décodeur tient sur 426 trames réelles.
Hygiène : le nom du thread paho (`paho-mqtt-client-<client id>`) expose le client id MQTT dans le
journal HA (les diagnostics le masquent) — à corriger.
Retour : rc2 `50b4ed3` redéployée à 14:04:19 (lot `…wJ3k`, +0 ~7 −36 : code sonde retiré) ;
redémarrage du cœur par Rémi. **Vérifié ~14:10** : intégration `loaded`, les options
`cloud_mqtt_probe` / `enable_cloud_mqtt` ont disparu du formulaire (rc2 chargée), R-3 toujours ON ;
empreinte d'options identique à celle d'avant la sonde (`dafc163576abe1cf`).
Correctif d'hygiène appliqué par la R&D : thread paho renommé (commit `e0334bc` sur #71).

## §2 — W-6 (vacances « absent », CIBLE 2), 2026-11-19 ~14:12–14:16 ✅

rc2 sur le Pi. Rémi confirme dans l'app : **aucune vacance programmée** sur le Bâtiment C-D-E-F
(nécessaire : `cancel_vacation` porte sur toute la maison). Test conçu **sans effet thermique** :
samedi (programme déjà en réduit 14 °C toute la journée), 14,5 °C = `holiday_setting` actuel des
têtes, une seule pièce (couloir).

- `enable_vacation_write` → true à 14:12:48 (lot `…iMYO`, accord de Rémi).
- `set_vacation` à 14:14:35 (lot `20261119-141435-34p4`) : home `256784132` (Bâtiment C-D-E-F),
  rooms = E-2 Circulation (groupe `13448871`), 20261205 08:00 → 20261205 18:00, 14,5 °C → réponse
  ok en 1,6 s.
- **HA, immédiatement** : `binary_sensor.batiment_c_d_e_f_holiday_active` attribut `detail` =
  `{startDate 20261205, startTime 08:00, endDate 20261205, endTime 18:00, temperature 145,
  roomList [E-2 Circulation], isRunning false, vacationType 3}` ; `sensor…_holiday_setpoint` 14,5.
- **App ✅** (Rémi) : vacances visibles sur E-2 Circulation, dates et température conformes.
- `cancel_vacation` à 14:15:34 (lot `20261119-141534-tBS8`) → ok ; HA à 14:15 : `holiday_active`
  **off**, plus de `detail`, `holiday_setpoint` unknown ✅.

- `enable_vacation_write` → **false** à 14:16:09 (lot `20261119-141609-tkeT`) : retour à l'état
  par défaut.

**Verdict W-6 ✅** (plan.leave + cancel validés en réel, round-trip HA immédiat). Restent non testés :
`set_vacation_at_home` (plan.athome) et `end_vacation` (leave.now, vacances en cours).

⚠️ **Défaut** : `binary_sensor…_holiday_active` passe à **on** pour une vacance **planifiée**
(`isRunning: false`) — il traite « detail non vide » comme « active ». Corriger : `is_on =
detail.isRunning` (et exposer « planifiée » à part). NB : `vacation.detail` contient donc aussi les
vacances planifiées (le détail vide initial prouvait bien l'absence de vacance programmée).

## Première écriture Tuya cloud MQTT (DP 30, tête isolée), 2026-11-19 ~14:26–14:35 ✅

Code `0e39fc0` (PR #71 brouillon, jamais mergé ; = rc2 + chemin d'écriture MQTT gaté). Audit avant
déploiement : `MQTT_WRITE_DPS = frozenset({30})` (refus de tout autre DP avant encodage) ; seul
`CloudMqttLink.publish_dp` publie vers les têtes, atteint uniquement par un switch sur le chemin
`cloud_mqtt` (option ON + lien présent + DP ∈ {30} + tête **isolée** de modèle vérifié — une tête
groupée part par la pièce, testé avant). CI verte.

- Déploiement 14:26:28 (lot `…93op`, +2 ~10 −32) + redémarrage (14:26:31). Option
  `enable_cloud_mqtt` présente et OFF ; switch verrou-enfant de C-1 `unavailable` (pas de chemin).
- Baseline C-1 Salle ASH : `child_lock` **true** (V0). NB : confort C-1 passé 21 → 20,5 dans la
  journée **par Rémi depuis l'app** (aucune écriture du connecteur) — confirmé.
- `enable_cloud_mqtt` → true à 14:31:59 (lot `…p1k4`). **Point 1** : `binary_sensor.cloud_mqtt_link`
  **on** (14:33:28) ; journal `cloud-mqtt link: CONNACK rc=0` (thread `danfoss-cloud-mqtt-link`,
  sans client id) ; switch C-1 `on`, available, `write_path: cloud_mqtt`, `write_scope: head`.
- **Écriture** `switch.turn_off` C-1 à 14:34 (lot `20261119-143427-fbiT`, accord de Rémi) → service
  **sans erreur** en 0,5 s (= confirmation, écho protocole 4 ou relecture cloud — non distingué dans
  le journal). **Point 2** : cloud `child_lock` **false** en quelques secondes (remonté par la tête ;
  vs W-3 `settings.change` : jamais), switch HA `off` (14:34) ; **app ET tête physique déverrouillées**
  (Rémi) ; aucun autre réglage de C-1 modifié ; app non éjectée.

**Verdict : ✅ première écriture Tuya cloud MQTT validée en réel** — le DP 30 d'une tête isolée
s'applique par MQTT (là où `settings.change` échoue). Valide aussi le chemin entrant de bout en bout.

Remise en état après la 1re écriture MQTT : C-1 reverrouillée par MQTT à 14:36 (lot `…xYEP`,
cloud `child_lock` true, switch `on`). `enable_cloud_mqtt` → false à 14:40:46 (lot `…rDw1`, mis en
file derrière un redémarrage HA lancé par la session ha-weishaupt à 14:37:37 — collision, sans
dommage). Retour **directement sur la rc3** (au lieu de la rc2) sur décision de Rémi.

## Déploiement `1.1.0-rc3` (`0541a5b`, #74 correctifs), 2026-11-19 ~14:43 ✅ (contrôle rapide)

Extrait propre du tag `1.1.0-rc3` (= `main`, manifest 1.1.0). Déploiement 14:43:35 (lot
`20261119-144335-35Wm`, +0 ~16 −36 : code MQTT retiré) + redémarrage du cœur. Contrôle en lecture :
- intégration `loaded` ; **aucune ligne d'erreur** `danfoss_ally_cloud` dans le journal au démarrage ;
- options MQTT (`enable_cloud_mqtt`, `cloud_mqtt_probe`) **disparues** du formulaire ; R-3 ON ;
- `binary_sensor.cloud_mqtt_link` : plus fourni → restait au registre comme **orpheline** ;
  **supprimée** à 14:57:25 (lot `20261119-145725-dwcq`, accord de Rémi, contrôle orpheline OK) ;
- `holiday_active` **off** sur les deux maisons avec l'attribut **`scheduled: false`** (correctif #74) ;
- climate C-1 disponible (`active_setpoint` 20,5) ; switch verrou-enfant C-1 `unavailable` (attendu :
  tête isolée, pas de chemin prouvé sans MQTT) ; C-1 verrouillée (V0) côté cloud ;
- préchauffe : switches disponibles, essai en cours (E-1 E13 `off`, Photocopieur `on`) jusqu'à vendredi ;
- version **1.1.0** affichée dans le panneau ✅ (Rémi).
Écritures des correctifs #74 (R-3 sur `number`, relecture préchauffe, vacance planifiée) : couvertes par
tests unitaires, validation réelle à la prochaine fenêtre.

**Défauts de l'outillage connecteur relevés** (à remonter à `homeassistant-admin-mcp`) :
- un confirm qui expire côté client **perd l'entrée de journal** alors que l'écriture a eu lieu ;
- le vérificateur de redémarrage « HA reparti » renvoie `state = None` pendant 600 s alors que HA
  tourne (faux négatif, tâche marquée en échec) ;
- `reconnect_session_connector` ne peut pas recharger un serveur MCP stdio sain : un nouvel outil
  n'apparaît qu'après relance manuelle du serveur.

## §3 — online vs update_time (spot-check autonome)

- C-1 Salle ASH (en ligne) → availability MQTT `online` ✅.
- **D-1 Local Apel #3** (tête hors ligne, `danfoss_sante`) → availability MQTT **`offline`** ✅ →
  la disponibilité suit bien `online`, pas `update_time`.
- B-0 Chapelle (**capteur**) et Hc2 Relay (**relais**) → topic availability **absent** : ces
  catégories ne sont **pas publiées** en discovery (l'intégration publie les têtes ; capteurs/relais
  hors périmètre MQTT). À noter, pas un défaut.

## R-3 — complément (transitoire perdu)

Re-lecture de C-1 Salle ASH ~21:51 : revenue au programme (`reduit`, `OccupiedSetpoint` 1400, vanne
1 %, `work_state` NoHeat). Le pic manuel (21 / vanne 82 %) de ~21:06 **n'a jamais été reflété** par
l'intégration ni le MQTT (route bulk) : né et mort entre deux polls visibles. Confirme que les
variations rapides passent sous le radar de la route bulk.

## État de la session (2026-11-18, soir)

- **Faits** : §0 (prérequis + activation discovery), R-1 (2 mismatch : consigne + hvac_action),
  R-3 (latence route bulk). Firmware tête relevé.
- **Reporté à demain matin** : R-2 (fenêtres à l'aération), P-1…P-3 (courbes préchauffe),
  re-contrôle latence bulk.
- **Suspendu** : écritures W-1…W-7 — peu concluantes tant que (a) le correctif mapping n'est pas
  mergé et (b) la latence bulk n'est pas tranchée (les round-trips ne se voient pas en temps utile).
- **Gaté / non testé** : W-6 vacances (CIBLE 2, option off), §2b unbind (CIBLE 3, non exposé).
- **Correctif R-1** : session `fix-consigne-active-hvac` (task_8953a1cb) — **codé, tests verts**
  (407 passed, couverture 93.45 %, ruff OK), **non commité**, en attente de relecture/commit par Rémi.
  Mapping : DP 171 → (repli : mode+settings) → DP 16. R-3 (fraîcheur) laissé hors de ce PR.
- **À remettre** : C-1 Salle ASH laissée en manuel 21 pendant R-3 → à repasser sur programme.
- **Config** : `mqtt_mode=discovery` laissé actif pour l'observation de demain matin.

## Lecture de l'essai préchauffe, vendredi 2026-11-20 ~10:00 — essai annulé par un retour arrière nocturne

Lecture seule (historique HA de `danfoss_ally_cloud`, puis `danfoss_local_tete` sur les deux têtes à ~10:00).

- **Retour arrière sans écriture de notre part** : les switches préchauffe, alimentés par le relevé
  local, montrent E-1 E13 **off → on à 04:54:52** et E-1 Local Photocopieur **on → off à 04:55:02**
  (deux lectures du même relevé, à 10 s d'écart, sans contexte utilisateur dans le journal de bord).
  Aucun lot dans le journal du connecteur ni dans `ha_journal` cette nuit-là.
- **Relu en local à ~10:00** : E13 `mode_programmation` 3, `pre_chauffage` true ; Photocopieur
  `mode_programmation` 1, `pre_chauffage` false ; programmes et consignes inchangés. Les deux têtes
  sont donc déjà dans leur état d'origine : **aucune remise en état n'est nécessaire**.
- **Courbes du matin**, cohérentes avec l'état revenu :
  - E13 (préchauffe revenue à ON) : vanne ≥ 10 % à **07:12**, soit 78 min avant le créneau ;
    18,3 °C → 22,1 °C à 08:27 ; vanne refermée à 08:32.
  - Photocopieur (revenu à OFF) : vanne ≥ 10 % à **08:35**, soit le créneau + 5 min, sans rampe
    anticipée ; 17,7 °C à 08:45 → 22,4 °C à 09:46.
- **Hypothèse sur la cause** : l'écriture locale de 0x0025 (hier 10:58) n'a pas touché le DP 1 du
  cloud, resté à la valeur d'origine (E13 true, Photocopieur false, visible sur les
  `switch.*_pre_heat` de MTrab, inchangés toute la nuit). La passerelle a pu réimposer à la tête sa
  valeur en cache, à une resynchronisation nocturne. Cela rejoint l'étape A de la session
  « Préchauffe par MQTT cloud » (une publication DP 1 de l'app atteint bien 0x0025). **À confirmer**,
  mais si c'est le cas, une écriture préchauffe par le seul tunnel n'est pas durable : il faut
  aligner le DP 1 du cloud en même temps.
- **Ce que l'essai ne prouve plus** : l'effet d'une bascule tenue toute une nuit (E13 fermée jusqu'à
  08:30, Photocopieur anticipé). À refaire avec le DP 1 du cloud aligné sur la valeur locale.

## Déploiement `1.3.0-rc3` (`015fdf5`, #121 → #124) et essai C2 par le tunnel, 2026-11-20 ~14:20–15:07 ✅

Dépôt des fichiers depuis le tag (Marketplace toujours refusé), redémarrage du cœur 14:20, intégration
`loaded`, journal propre. Code rc3 vérifié par les nouveaux champs d'options (`local_supervised_*`,
DP 101/133 candidats).

**Lecture seule (lots A/B, carte par zone)** — tête C-1 Circulation : capteurs nouveaux cohérents avec
`danfoss_ally` (MTrab) : radiateur couvert off/off, mode de programmation `schedule_with_preheat` /
préchauffe on, mode montage off/off, état de fenêtre `closed` / fenêtre off. 5 capteurs désactivés par
défaut (orientation, vitesse, décalage, jour/heure de dégommage). Aucune entité d'essai tant que fermé.
Panneau : bundle rc3 servi, autres zones masquées par défaut. Carte `area_id: a_0_salle_a05` montée en
mémoire (rien d'enregistré) : 2 thermostats `danfoss_ally` listés sans commande, y compris avec
`allow_foreign_writes: true` (doublons). Non testable : thermostat Z2M réglable (aucune tête Z2M n'a
de zone). ⚠️ URL du bundle `?v=1.3.0` identique pour toutes les rc : rechargement forcé nécessaire.

**Essai C2 (tunnel local), tête C-1 Circulation, un réglage armé à la fois, Rémi présent.**
V0 relevé par le connecteur (tunnel) : radiateur couvert off, décalage 0, vitesse 1, dégommage samedi 10:00.

| Heure | Écriture | `trial_result` | Relecture connecteur (tunnel) |
|---|---|---|---|
| 14:41 | radiateur couvert off → on | confirmed_by_tunnel | on |
| 14:42 | on → off | confirmed_by_tunnel | off |
| 14:47 | décalage 0 → +0,1 (raw 1) | confirmed_by_tunnel | 1 |
| 14:47 | → 0 | confirmed_by_tunnel | 0 |
| 14:48 | décalage 0 → +0,5 (raw 5, demande de Rémi) | confirmed_by_tunnel | 5 |
| 14:50 | → 0 | confirmed_by_tunnel | 0 |
| 14:57 | vitesse 1 → 2 | confirmed_by_tunnel | 2 |
| 14:58 | → 1 | confirmed_by_tunnel | 1 |
| 15:03 | dégommage jour samedi → dimanche (heure 10:00 gardée) | confirmed_by_tunnel | dimanche 10:00 |
| 15:04 | heure 10:00 → 11:00 (jour gardé) | confirmed_by_tunnel | dimanche 11:00 |
| 15:05 | jour → samedi, puis heure → 10:00 | confirmed_by_tunnel ×2 | samedi 10:00 |

Après chaque écriture : rien d'autre ne change sur la tête (programme, consignes, préchauffe, autres
réglages). Désarmé 15:05 : entités d'essai et entrées du registre retirées.

Constats :
- **Sources indépendantes absentes** : l'app n'affiche pas le décalage (Rémi) ; le switch « radiator
  covered » de `danfoss_ally` (API officielle) est resté off pendant l'écriture à on (dernière mise à
  jour 14:21). Comme pour la préchauffe, le cloud peut ignorer ces écritures tunnel et réimposer sa
  valeur : tenue dans la durée non établie.
- **Échelle du décalage non confirmée.** Hypothèse de Rémi : le décalage modifie la température
  remontée. Historique : température 21,0 → 21,2 à 14:48:48 (pas +0,5) et restée 21,2 après retour à 0 ;
  vanne 41 → 56 % à 14:47:18, 12 s après +0,1 (plage 37–41 % l'heure d'avant), 33 % à 14:51:48.
  Plutôt un décalage de la cible de régulation (nom Z2M `regulation_setpoint_offset`). Essai proposé :
  +2,5 °C observé 10 min (température remontée vs vanne).
- **État de fenêtre en quarantaine (0)** depuis 14:44:19 (première relecture après le rechargement de
  14:42:44, juste après le retour du radiateur couvert à off ; le connecteur lisait 1 à 14:42). Toujours 0
  à 15:05. Détection de fenêtre toujours activée. À relire plus tard.

## Essai lot C (MQTT cloud), tête C-1 Circulation, 2026-11-20 ~15:08–15:22

Armement : `enable_cloud_mqtt` on, tête désignée, un DP à la fois. Désarmé 15:22 (`enable_cloud_mqtt`
remis à off, comme avant l'essai) : entités d'essai retirées, registre revenu à 14 064, lien en écoute
seule (sonde de couverture).

**DP 101 (sens d'affichage) — refusé avant tout envoi (15:11).** Switch créé sur la seule tête désignée,
`off` (liste globale), concordant avec l'écran et l'app (Rémi). `turn_on` → `trial_result: refused` :
« the per-device cloud route does not give DP 101 ». La liste globale porte le DP 101, la route
individuelle (`smartlife.m.device.get`) non. Rien publié. À corriger dans le code : autre source de
confirmation (liste globale avec une fenêtre plus longue), la preuve restant l'écran.

**DP 133 (orientation) — validé aller-retour.** Correspondance établie avant écriture : tête montée
horizontalement (Rémi), app horizontale, tunnel `0x4014 = false`, cloud `Horizontal` → false = horizontal
(lecture de Zigbee2MQTT confirmée).

| Heure | Écriture | `trial_result` | Délai | Tunnel (connecteur) | Cloud |
|---|---|---|---|---|---|
| 15:20 | horizontal → vertical | confirmed_by_tunnel | 22 s | true | Vertical |
| 15:21 | vertical → horizontal | confirmed_by_tunnel | 17 s | false | Horizontal |

Rien d'autre ne change sur la tête. Le cloud suit (contrairement aux écritures tunnel seules du C2).

**Incident de coordination.** 15:13:57, une autre session (projet weishaupt-ebus, « Home Assistant :
déploiements et essais ») a redémarré le cœur. Notre première écriture vers vertical (15:15:51) a
attendu le verrou, puis est partie à 15:17:14, 2 s après le retour du cœur, avant la recréation du
select : appel sans entité, rien envoyé (vérifié : pas de `trial_result`, tunnel false). Annulation non
envoyée : l'outil aurait aussi libéré le verrou tenu par l'autre session. Relancée à 15:20 après avoir
vérifié qu'aucune tâche ne tenait le Pi.

## Essais sur la rc4 puis la 1.3.0, tête C-1 Circulation, 2026-11-20 ~15:55–16:26 (session « Zigbee2MQTT »)

Pilote unique de l'intégration sur le Pi pendant l'essai ; deux sessions weishaupt-ebus tournaient
encore (aucun lot de leur part dans le journal du connecteur pendant l'essai). Rémi a mis à jour
l'intégration en 1.3.0 par HACS vers 16:20 (redémarrage du cœur) : code du Pi identique au tag
`1.3.0` (aperçu de déploiement depuis `fb9d0eb` : 0 ajout, 0 modification, annulé).

**Lecture seule après le dépôt de la rc4** : intégration chargée ; C-1 Circulation cohérente avec
`danfoss_ally` (radiateur couvert off, mode montage off, mode de programmation
`schedule_with_preheat`, origine `schedule`, adaptation `found`). **État de fenêtre revenu à
`closed`** (brut 1, lu 16:02) : la quarantaine vue après l'essai de 14:44 ne persiste pas.

**Décalage de consigne +2,5 °C pendant 10 min** (armé 15:58, `local_supervised_settings =
[setpoint_offset]`, V0 = 0, brut 0).

| Heure | Décalage | Température (intégration) | Vanne (tunnel) | Action |
|---|---|---|---|---|
| 16:01 | 0 | 21,0 | 38 % | idle |
| 16:02:44 | → +2,5, `confirmed_by_tunnel`, brut 25 | | | |
| 16:06–16:07 | +2,5 | 20,9 | 42 % | heating |
| 16:12 | +2,5 | 21,2 | 52 % | idle |
| 16:13:16 | → 0, `confirmed_by_tunnel`, brut 0 | | | |

Constats : la température remontée ne se décale pas (hypothèse « décalage de la mesure »
écartée) ; la vanne s'ouvre de 38 à 52 % à la consigne, ce qui va dans le sens d'un décalage de la
cible de régulation (`regulation_setpoint_offset` de Z2M), mais l'effet est faible face à la
variation naturelle (37–41 % la veille). Échelle (brut 25 = 2,5 °C ?) toujours non prouvée. Essai
proposé : 30 min à +2,5 puis 30 min à −2,5, pièce à la consigne.

**Tenue sur une nuit d'un réglage écrit par le tunnel seul** (armé 16:18,
`local_supervised_settings = [valve_exercise]`). V0 relu après le redémarrage : samedi 10:00.
16:25:15 jour → dimanche, `confirmed_by_tunnel`, heure 10:00 inchangée. Essai refermé 16:25:33
(liste vide, aucune tête). Relecture indépendante par le connecteur (`danfoss_local_tete`, 16:26) :
dégommage dimanche 10:00, décalage 0, radiateur couvert off, vitesse 1, programme inchangé.

**À faire le 21/11 au matin** : relire le dégommage par `danfoss_local_tete("C-1 Circulation")`.
Dimanche = la tête garde un réglage écrit par le tunnel ; samedi = le cloud le réimpose, comme la
préchauffe. Puis remettre samedi 10:00 (réarmer `valve_exercise` sur C-1 Circulation, écrire,
refermer).

**Décalage +2,5 °C pendant 30 min** (même tête, réarmé 16:31, V0 = 0). 16:34:47 → +2,5
(`confirmed_by_tunnel`, brut 25) ; 17:05:07 → 0 (`confirmed_by_tunnel`, brut 0) ; essai refermé 17:05:17.
Historique HA : vanne (tunnel) 41 % (16:32) → 37 → 52 → 62 → 72 → 84 % (16:57) ; température 21,4 → 21,3
→ 21,5 → 21,8 → 22,3 → 22,5 °C (16:58), consigne 21. **Le décalage relève la cible de régulation**
(la tête chauffe au-dessus de sa consigne, la mesure ne saute pas) : sens confirmé, comme
`regulation_setpoint_offset` de Z2M. Échelle non prouvée (pas de palier atteint en 30 min). À documenter :
avec un décalage, la consigne affichée ne dit plus jusqu'où la pièce monte.

**Zone B-0 Chapelle** : les 5 appareils Zigbee2MQTT (Chapelle-1 à -4, sonde 014G2480) rangés dans la zone
(16:57, connecteur PR #11, lot `20261120-165758-zAox`). Carte par zone montée en mémoire : 4 têtes listées
avec badges (batterie, vanne…), lecture seule par défaut, boutons avec `allow_foreign_writes`. Les têtes
régulent sur la sonde (`external_measured_room_sensor` ≈ 17,4 °C) et chauffent vanne 100 % à 20–24 °C de
mesure propre : la carte ne montrait pas la sonde → PR #128.

## Relecture de l'essai de nuit et 1.3.1-rc1, samedi 2026-11-21 ~09:56–10:06

**Tenue d'un réglage écrit par le tunnel seul : ✅ tenu.** `danfoss_local_tete("C-1 Circulation")` à
~09:56 : dégommage **dimanche 10:00** (écrit hier 16:25), reste de la tête inchangé. Le réglage a passé
l'heure (~05:00) où la préchauffe écrite par le tunnel avait été réimposée. Un réglage, une tête, une nuit.
Restauré : armé 10:01 (`valve_exercise`), samedi écrit 10:05:01 (`confirmed_by_tunnel`), essai refermé
10:05:18 ; relu par le connecteur : samedi 10:00.

**`1.3.1-rc1` (`409d9ee`, #128 carte avec sonde)** : fichiers déposés hier 17:32 (verrou tenu 7 min par une
installation eBUSd d'une session weishaupt, premier dépôt abandonné sans rien écrire), cœur redémarré ce
matin 09:56 (aucune écriture d'autre session depuis 19:39). Ressource Lovelace mise à jour sur place :
`danfoss-ally-cloud.js?v=1.3.1-338788d9` (empreinte du bundle déposé). Carte zone `chapelle` en mémoire :
« 14 °C · 69 % — Room sensor » (sonde 14,01 °C / 69,19 %) ; chaque tête « Regulates on an external room
sensor (14 °C) », mesure propre 15,2 / 16,4 °C, consigne 14 °C ; `external_measured_room_sensor` = 1403.
Une autre session a lu une tête Z2M de la Chapelle (`mqtt.publish …/get`) à 10:01 : lecture seule.

## Échelle du décalage de consigne, tête C-1 Circulation, samedi 2026-11-21 (session « essais réels 1.3.1 »)

But : établir l'échelle de `setpoint_offset` (attribut 0x404B) en forçant une dérogation par le tunnel
(DP 171) pour rendre la vanne lisible un samedi (toute l'école en réduit, aucun créneau confort). Accord
de Rémi pour la séquence W1–W7.

- **W1** 10:31:32 (lot `…vbOe`) : armement `local_supervised_settings = [setpoint_offset]`,
  `local_supervised_head = C-1 Circulation`. Entité `number.c_1_circulation_setpoint_offset_setting`
  apparue à 0,0 (brut 0), bornes −2,5…+2,5 par 0,1, `write_path=local`, `write_scope=head`.
- **W2** 10:31:53 (lot `…x7Dj`) : `danfoss_ally_cloud.set_override` 17 °C (dérogation « maintenant »,
  tunnel DP 171). Relu par `danfoss_local_tete` ~10:35 : `consigne_en_cours` 17, `source_consigne` 2
  (externe), `decalage_consigne` 0, programme inchangé.

**V0 (baseline, décalage 0, dérogation 17 °C)** — 10:35 :

| Heure | Décalage | Température | Vanne (tunnel) | Cible régul. théorique |
|---|---|---|---|---|
| 10:35 | 0 | 16,9 | 1 % | 17,0 |
| 10:55 | 0 | 16,9 | 1 % | 17,0 | baseline settled, aucune demande |

- **W3** 10:55:12 (lot `…z57j`) : décalage **−2,5** via `number…setpoint_offset_setting`.
  `trial_result = confirmed_by_tunnel`, **brut −25** (dixièmes). Cible théorique 14,5 < pièce 16,9 →
  vanne reste fermée (sens négatif cohérent, non distinguable de la baseline).

- **W4** 11:09:55 (lot `…jtjx`) : décalage **+2,5** (brut +25, `confirmed_by_tunnel`). Cible théorique
  19,5 > pièce 16,9 → vanne doit s'ouvrir, pièce monter vers un palier. Suivi vanne/température :

| Heure | Décalage | Température | Vanne | Note |
|---|---|---|---|---|
| 11:10 | +2,5 | 16,9 | — | départ, cible ~19,5 |
| 11:18 | +2,5 | 16,9¹ | 20 % | vanne ouverte, `demande_chaleur` true (sens + confirmé) |

**Interruption (teardown de session).** Le +2,5 (W4) a bien ouvert la vanne (1 → 20 % à 11:18,
`demande_chaleur` true, sens positif confirmé) mais l'essai n'a **pas** atteint de palier mesurable :
la sonde cloud est restée bloquée à 16,9 °C (dernière maj 10:31), et la session a été coupée vers 11:30
avant la lecture de l'historique HA. Le décalage +2,5 et l'override 17 sont donc restés posés ~2,5 h,
la pièce a chauffé (vanne vue à 99 % par la session principale). **Échelle du décalage toujours non
mesurée** (sens + confirmé ; brut = dixièmes, −25 / +25 lus et confirmés par le tunnel).

**Nettoyage (feu vert explicite de Rémi « Oui, nettoie »).** Un redémarrage HA (session de déploiement
weishaupt partageant le connecteur, lot `…IX9R` 14:07) a tenu le verrou ; attendu sans l'annuler.
- `clear_override` 14:15:50 (lot `…ailD`) : override levé, retour à la consigne du programme (14 °C) ;
  `consigne_en_cours` 14, `demande_chaleur` false.
- `number…setpoint_offset_setting` → **0** 14:18:17 (lot `…ee7x`) : `confirmed_by_tunnel`, brut 0.
- Essai refermé 14:18:34 (lot `…MtH9`, `local_supervised_settings = []`, `local_supervised_head = ''`).

**État final (relu 14:20, tunnel + route cloud par appareil)** : consigne 14, décalage 0, pas de demande
de chaleur, programme du samedi intact, `OccupiedSetpoint` 1400. (La route cloud affichait encore une
vanne à 94 % — cache périmé ; tous les signaux frais disent NoHeat.) **À reprendre un jour de semaine
en créneau confort pour mesurer le palier** (la sonde cloud ne suit pas en réduit samedi).
