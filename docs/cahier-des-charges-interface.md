# Cahier des charges — programmes par pièce et interface embarquée

But : permettre de consulter et de modifier le programme hebdomadaire d'une pièce depuis Home Assistant, sans
ouvrir l'application mobile, avec une carte de tableau de bord livrée par l'intégration. Référence des formes
et des règles : `docs/contrat-interface.md` (R1 à R7). En cas de contradiction, **le contrat fait foi** ; s'il
se révèle faux ou incomplet, on le corrige d'abord, dans un commit à part.

Objectif d'ensemble (rappel) : parité avec l'app, tout dans la version publique HACS, écriture réservée aux
administrateurs, programme écrit par pièce via le cloud, tunnel local pour vérifier.

## État d'avancement (au 17/11/2026)

Le backend a été livré directement sur `main`, hors de la numérotation d'origine des lots, par les PR #10
(consigne durable de pièce), #12 (un `climate` par pièce) et #17 (édition du programme : `api/schedule.py`,
`operations.py`, `services.py` + `services.yaml`, `websocket_api.py`, `writejob.py`). Le modèle de pièce, la
validation R1, les actions (§5.2) et les commandes WebSocket (§5.3) du contrat sont donc **en place et
conformes au contrat**.

- **Lots 0, 1, 2 — faits** (fusionnés dans `main`). Les sections ci-dessous valent comme spécification de
  référence et trace historique.
- **Lot 3 — en cours** : socle de l'interface embarquée (PR #11).
- **Lot 4 — à rebaser sur `main`** : carte Programme en lecture (PR #16, aujourd'hui empilée sur le lot 3).
- **Lot 5 — à faire** : carte Programme en écriture.

Seuls les lots 3 à 5 restent à produire ; ils ne partagent aucun fichier avec le backend déjà fusionné.

## Périmètre

Dans ce cahier des charges :
- lots 0 à 5 ci-dessous : mise à niveau des documents, couche `api/`, câblage Home Assistant, socle de
  l'interface, carte Programme en lecture puis en écriture.

Hors périmètre (ne pas commencer) : vacances, dérogation confort / réduit, gestion des pièces, relais, panneau
latéral complet, publication MQTT des programmes.

## Lot 0 — Mise à niveau des documents et du thermostat

Les essais du 16/11/2026 corrigent deux affirmations du dépôt.

1. `CLAUDE.md` et `docs/architecture.md` disent que « `at_home` / `leaving_home` cloud → tête en manuel ». Le
   mécanisme réel est R4 et R5 : c'est le **passage en manuel** qui efface le programme, et `at_home` /
   `leaving_home` ne sont que des étiquettes. Corriger les deux documents en renvoyant au contrat.
2. `docs/roadmap.md` : ajouter les jalons de ce cahier des charges.
3. **Thermostat** : une modification en cours (peut-être déjà fusionnée) fait écrire la consigne du mode actif
   (`at_home_setting`…) quand l'utilisateur change la température. D'après R3, sans réécriture du programme
   derrière, la tête reprendra l'ancienne valeur à la transition suivante. Vérifier l'état de cette
   modification dans `main` et l'aligner : soit la consigne de mode n'est écrite que par les entités `number`
   de la pièce (section 5.1 du contrat) avec réécriture du programme, soit le thermostat fait de même. Ne pas
   laisser une écriture de consigne de mode sans R3.

Livrable : un commit de documentation, et si besoin un commit correctif du thermostat avec ses tests.

## Lot 1 — Couche `api/` : pièces, programme, état réel

Dans `custom_components/danfoss_ally_cloud/api/` (c'est aussi la bibliothèque `pydanfoss_cloud` : aucune
dépendance à Home Assistant dans ce dossier).

1. `schedule.py` (nouveau), fonctions pures :
   - modèle `Schedule` / plages ; conversion depuis la réponse `week.timer.list` (minutes → `HH:MM`, masque
     `loops` dimanche en premier) et vers le corps de `week.timer.create` ;
   - `count_transitions(day)` et `validate_days(days)` selon R1, renvoyant les erreurs du contrat (5.4).
2. `client.py` :
   - `async_list_rooms()` : pièces de toutes les maisons, avec leurs têtes (4.1 et section 1 du contrat) ;
   - `async_get_schedule(target)` ; `async_set_schedule_days(target, days)` (valide, puis `delete` + `create`
     par jour) ; `async_restore_schedule(target)` (R4) ;
   - `async_publish_room_dps(group_id, dps)` avec **liste blanche** des DP permis (118, 109 + 119, 2 limité à
     `manual` et `at_home`, 1, 30, 116, 18) ; toute autre clé est refusée.
3. `decode.py` : `schedule_active`, `preheat` (DP 172), `mounting` (DP 149), `inconsistent`, sur le modèle
   d'appareil existant.

Code de référence à porter (ne pas réinventer) : `~/dev/danfoss-ally-mcp/danfoss_ally_mcp/tuya/pilote_tuya.py`
— `decoder_programme`, `_valider_fenetres`, `compter_transitions`, `programme_confirmer`, `pieces`,
`membres_par_piece`, `modes_tetes`, `_mode_piece_executer`. Ses tests (`tests/test_tuya.py`) donnent les cas
limites. Différence voulue : ici pas de jeton préparer → confirmer ; la sûreté passe par la validation.

Tests (données synthétiques uniquement) : chaque règle R1 a ses cas — 3 plages séparées (valide, 6), 4 plages
(refusé), plage à `00:00`, plages qui se touchent, chevauchement, fin à `23:59` ; décodage d'une réponse réelle
anonymisée ; `restore` : sept `delete`, les `create` nécessaires, puis `{"2": "at_home"}` **en dernier** ;
liste blanche des DP.

## Lot 2 — Câblage Home Assistant

1. **Coordinateur** : pièces et états des têtes à chaque rafraîchissement (aucun appel de plus, 4.3). Les
   programmes ne sont **pas** relus à chaque cycle : cache par cible, rempli à la demande et rafraîchi au plus
   une fois par heure et après chaque écriture. Le compte est celui de l'utilisateur : rester économe.
2. **Appareils** : un appareil par pièce ; entités de la section 5.1 du contrat ; traductions `en` et `fr`.
3. **Actions** (5.2) dans `services.yaml` + `strings.json`, avec réponse (`SupportsResponse`), contrôle
   administrateur, et erreurs du contrat sous forme de `ServiceValidationError` traduites.
4. **WebSocket** (5.3) dans `websocket_api.py` ; mêmes fonctions que les actions.
5. **Lots d'écriture** (`WriteJob`) : file en mémoire, événements pour `jobs/subscribe` ; vérification par
   DP 172 pour le mode, par le tunnel local pour le programme quand `enable_local` est actif (lecture du
   programme dans la tête : voir `api/local/`), sinon `unverified`. La vérification locale est différée de
   5 minutes et ne bloque jamais l'appel.
6. **Diagnostics** : pièces et états sans identifiant réel (rédaction existante à étendre).

Tests : harnais `pytest-homeassistant-custom-component` existant ; refus d'un non-administrateur ; `set_schedule`
invalide → aucune requête envoyée ; réécriture du programme après un changement de consigne (R3) ; maintien de
la couverture et de mypy au niveau actuel.

## Lot 3 — Socle de l'interface

1. Dossier `frontend/` : TypeScript + Lit, build par Vite ou Rollup vers
   `custom_components/danfoss_ally_cloud/frontend/danfoss-ally-cloud.js` (un seul fichier, sans dépendance
   chargée au vol). Tests unitaires (Vitest) pour la logique pure.
2. **Le fichier compilé est versionné** dans le dépôt, pour que l'installation HACS fonctionne depuis n'importe
   quelle branche ou étiquette. La CI reconstruit et échoue si le fichier versionné n'est pas à jour.
3. Enregistrement côté Python (`frontend.py`) : chemin statique, ressource Lovelace, nettoyage au retrait de la
   dernière entrée ; dépendances `http` et `frontend` dans le manifest (et `lovelace` si l'enregistrement de la
   ressource l'exige — à vérifier sur la version de Home Assistant visée ; clés du manifest dans l'ordre exigé
   par hassfest).
4. Contrôle de version (section 6 du contrat) avec proposition de rechargement.
5. Une carte minimale `danfoss-ally-schedule-card` qui affiche le nom de la pièce choisie et la version, avec
   son éditeur de configuration (choix de la pièce parmi `danfoss_ally_cloud/rooms`).
6. Page de démonstration hors Home Assistant (`frontend/demo/`) avec un faux objet `hass` et des données
   d'essai, pour développer la carte sans instance.
7. README : installation, mode YAML, capture d'écran.

Critère : la carte apparaît dans le sélecteur de cartes d'un Home Assistant réel après installation par HACS
(dépôt personnalisé), sans manipulation manuelle en mode stockage.

## Lot 4 — Carte Programme, lecture

- Grille des sept jours, plages de confort positionnées sur 24 h, consignes confort et réduit, nom de la pièce.
- État des têtes de la pièce : en ligne, programme actif, incohérente, en montage (icônes + infobulle).
- Bouton « actualiser » (`refresh: true`), date de dernière lecture.
- Thème clair / sombre par les variables de Home Assistant ; utilisable au clavier ; textes traduits `en` / `fr`
  par le mécanisme de localisation du frontend (pas de texte en dur).
- Largeur : une colonne de tableau de bord sur mobile, sans défilement horizontal.

## Lot 5 — Carte Programme, écriture

- Édition d'un jour : ajouter, déplacer, redimensionner, supprimer une plage (pas de 5 minutes ; saisie directe
  des heures possible, indispensable au clavier et sur mobile).
- Validation immédiate par `schedule/validate` et, localement, par la même règle R1 portée en TypeScript avec
  ses tests ; le compteur de transitions du jour est affiché (« 4 / 6 ») ; l'enregistrement est impossible tant
  qu'un jour est invalide.
- Copier un jour vers d'autres jours.
- Enregistrer n'envoie que les jours modifiés ; suivi du lot par `jobs/subscribe` : « envoyé », puis par tête
  « appliqué », « différent », « injoignable » ou « non vérifié ».
- Bouton « revenir au programme » visible quand une tête de la pièce n'a plus son programme actif.
- Lecture seule pour un utilisateur non administrateur.
- Annuler les modifications non enregistrées ; avertir avant de quitter une édition en cours.

## Validation en réel

Les tests automatiques ne suffisent pas : chaque lot qui écrit est validé sur une installation réelle.
- Une **pièce d'essai** désignée par le propriétaire de l'installation, sans enjeu de confort.
- Avant toute écriture réelle : montrer ce qui va être envoyé et attendre l'accord.
- Après : relire dans la tête (tunnel local) et noter le délai ; remettre la pièce dans son état d'origine.
- Consigner les résultats dans la description de la demande de fusion (date, pièce anonymisée, constat).

## Règles du dépôt à respecter

Celles de `CLAUDE.md` : aucun secret ni identifiant réel dans le code, les tests, les journaux ou les
diagnostics ; `ruff`, `mypy`, `pytest` verts ; une branche par lot ; commit et push seulement sur demande ;
messages en français. Le dépôt est destiné à devenir public : aucune donnée propre à une installation.

## Ordre et dépendances

Lot 0 → lot 1 → lot 2, et lot 3 en parallèle des lots 1 et 2 → lot 4 → lot 5. Les lots 1 et 3 ne touchent
aucun fichier commun. Un lot = une branche = une demande de fusion, avec sa validation.
