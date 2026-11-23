# Validation réelle — préchauffe (P-1, P-2, P-3), matin du jeudi 2026-11-19

Lecture seule, sans aucune écriture sur le Pi ni sur les têtes. Ce fichier complète
`docs/real-validation-results.md`, tenu par la session de validation, et détaille le §3 de
`docs/real-validation-plan.md`.

## Sources

- **État de la préchauffe (le levier réel, 0x0025)** : historique HA des
  `switch.*_pre_heating` de l'intégration `danfoss_ally_cloud`, alimentés par le relevé local du
  tunnel (`DanfossLocalCoordinator.survey_preheat`). Contrôle ponctuel par
  `danfoss_local_tete("E-0 Buanderie")` : `pre_chauffage: false`, plage du jeudi 08:30–17:30,
  confort 20, réduit 14.
- **Courbes** : historique HA (`/api/history/period`, lu via le proxy du Supervisor) de
  `sensor.*_valve_opening*` et `sensor.*_temperature*` de l'intégration, du 18/11 16:00 au
  19/11 10:30. Toutes les heures sont celles de Paris (UTC+1).
- **Recoupement indépendant** : `binary_sensor.*_pre_heating` de l'intégration `danfoss_ally`
  de MTrab, qui remonte le drapeau cloud « préchauffe en cours ».
- **Programmes** : `danfoss_tuya_programmes` (A-0, A-1, A-2, C-, D-, E-0, E-1).
  - Jeudi, créneau confort à **08:30** partout.
  - Exceptions : **08:00** pour A-0 Secrétariat, Dégagement Cours, Sanitaires RdC,
    Hall Garderie, A02 #1/#2 et Local Photocopieur ; **07:00** pour D-0 Cuisine.

Méthode : on prend comme **premier démarrage de chauffe** le premier relevé de vanne ≥ 10 %
depuis minuit (la vanne restait à 0–1 % toute la soirée). On calcule ensuite
**avance = début du créneau − démarrage**. La vanne n'est relevée qu'environ toutes les
5 minutes, d'où une précision de ±5 min.

## Résultat

| Étape | Verdict | Résumé |
|---|---|---|
| **P-1** préchauffe ON → chauffe anticipée | ✅ | 70 têtes ON exploitables. La vanne s'ouvre de **52 à 448 min avant le créneau (médiane 252 min, ~4 h 10)**. Le drapeau cloud « Pre-Heating » passe à ON au même moment, à quelques minutes près. Les pièces atteignent ~21 °C vers 07:00–08:00, donc avant 08:30. |
| **P-2** préchauffe OFF → chauffe au créneau | ✅ (2 têtes nettes) | E-0 Buanderie et E-1 Local Photocopieur : vanne à 1 % jusqu'à **08:34**, soit le créneau 08:30 + 4 min (pas de relevé), sans aucune rampe anticipée et sans drapeau cloud. Les autres têtes OFF ne sont pas concluantes (voir plus bas). |
| **P-3** switch indisponible quand le tunnel ne répond pas | ✅ partiel | Plusieurs cas par tête : le switch préchauffe passe `unavailable` alors que `online` reste `on` et que les autres switches cloud de la tête (verrouillage, détection de fenêtre) restent disponibles. Il ne ment donc jamais en ON/OFF. Pas de coupure totale du tunnel observée dans la fenêtre. |

### Tableau par tête (échantillon représentatif)

| Tête | Préchauffe (switch, nuit) | Créneau jeudi | 1er démarrage (vanne ≥ 10 %) | Avance | Drapeau cloud ON | T 06:00 → 08:30 | Verdict |
|---|---|---|---|---|---|---|---|
| A-0 A01 #1 | ON | 08:30 | 03:39 | 291 min | 03:36 | 17.7 → 21.0 | P-1 ✅ |
| A-0 A03 | ON | 08:30 | 06:04 | 146 min | 06:06 | 17.0 → 21.1 | P-1 ✅ |
| A-0 A02 #1 | ON | 08:00 | 04:03 | 237 min | 04:29 | — | P-1 ✅ |
| A-1 A11 #1 | ON | 08:30 | 04:07 | 263 min | 04:29 | 17.5 → 21.9 | P-1 ✅ |
| A-1 A12 #1 | ON | 08:30 | 04:58 | 212 min | 05:14 | 17.8 → 20.9 | P-1 ✅ |
| A-1 A13 #2 | ON | 08:30 | 04:16 | 254 min | 04:29 | 17.3 → 21.1 | P-1 ✅ |
| A-1 Bureau Direction #1 | ON | 08:30 | 04:22 | 248 min | 04:29 | 17.4 → 21.9 | P-1 ✅ |
| A-1 SAS | ON | 08:30 | 05:25 | 185 min | 06:06 | — | P-1 ✅ |
| A-2 A21 #1 | ON | 08:30 | 01:36 | 414 min | 02:59 | 17.7 → 21.0 | P-1 ✅ (très tôt) |
| C-1 Salle des Professeurs #1 | ON | 08:30 | 03:39 | 291 min | 03:36 | 18.1 → 22.1 | P-1 ✅ |
| C-2 Salle Anglais | ON | 08:30 | 05:45 | 165 min | 06:06 | 16.1 → 20.7 | P-1 ✅ |
| D-0 Réfectoire #4 | ON | 08:30 | 04:46 | 224 min | 04:44 | — | P-1 ✅ |
| E-0 Préau #1 | ON | 08:30 | 03:27 | 303 min | 03:36 | 16.9 → 19.9 | P-1 ✅ |
| E-1 E11 | ON | 08:30 | 05:12 | 198 min | 05:14 | 17.5 → 21.8 | P-1 ✅ |
| E-1 E12 #2 | ON | 08:30 | 05:13 | 197 min | 05:14 | 17.2 → 21.0 | P-1 ✅ |
| E-1 E13 | ON | 08:30 | 06:18 | 132 min | 06:21 | 16.8 → 21.8 | P-1 ✅ |
| **E-0 Buanderie** | **OFF** (local : `pre_chauffage=false`) | 08:30 | **08:34** | −4 min | jamais | 14.2 → 15.4 → 19.1 à 10:00 | **P-2 ✅** |
| **E-1 Local Photocopieur** | **OFF** | 08:30 | **08:34** | −4 min | jamais | 16.6 → 17.5 → 22.1 à 10:00 | **P-2 ✅** |
| E-1 CTA | OFF | 08:30 | — (vanne 0 toute la matinée) | — | jamais | 15.2 → 16.5 | non concluant |
| E-1 Local Ménage | OFF | 08:30 | — (vanne 0) | — | jamais | 14.8 → 14.9 | non concluant |
| D-1 Local APEL #1/#2 | OFF / indispo | 08:30 | — (vanne 0) | — | jamais | ~14.6–15 | non concluant |

Liste complète, 99 têtes : relevé reproductible avec les requêtes de la section Sources. Les
avances vont de 52 min (E-0 Préau #5, hors ligne jusqu'à 07:09) à 469 min (sanitaires et
lave-mains de E-2, ouverts dès 00:40).

### P-2 : pourquoi seulement deux têtes

Treize switches sont à OFF, ce qui correspond à 7 têtes, les autres étant les doublons
`switch.*_pre_heat` de MTrab.
- **E-0 Buanderie** et **E-1 Local Photocopieur** sont les seules têtes OFF qui ont eu une vraie
  demande de chaleur au créneau. Elles démarrent à 08:34, quatre minutes après le créneau, sans
  anticipation. En miroir, les têtes ON du même bâtiment et de la même passerelle démarrent
  entre 03:00 et 06:20.
- **E-1 CTA** et **E-1 Local Ménage** ont la vanne à 0 avant comme après 08:30 : il n'y a pas de
  demande, probablement parce que la consigne de confort est basse. On ne peut donc pas trancher.
- **D-1 Local APEL #1/#2/#3** ont une consigne de 5 °C (hors gel) : pas de demande non plus. Le
  switch de #1 est en plus indisponible de 00:46 à 09:50, et celui de #3 l'est en permanence.
- Limite : ces têtes étaient déjà OFF avant le début de la fenêtre (au moins depuis le 18/11
  13:11). P-2 valide donc le **comportement de la tête et la lecture** du switch, **pas le
  chemin d'écriture** (bascule du switch → 0x0025). Voir la proposition d'essai plus bas.

### P-3 : indisponibilités observées (18/11 13:00 → 19/11 10:30)

- **Coupures globales** à 13:08, 14:59, 15:12 et 20:08 le 18/11, puis à 09:08 le 19/11, chaque
  fois pendant 2 à 4 minutes. Toutes les entités de l'intégration (`online`, verrouillage
  enfant…) tombent en même temps : ce sont des rechargements de l'intégration ou des
  redémarrages de HA, pas un signal propre au tunnel.
- **Coupures propres au tunnel, tête par tête** : le switch préchauffe est `unavailable` alors
  que `binary_sensor.*_online` est `on` et que `switch.*_child_lock` et
  `switch.*_open_window_detection_2` restent disponibles. Cela correspond au chemin
  `coordinator.data[id] is None` de `switch.py:156`.
  - A-0 A03 : 07:34–07:51, 08:24–08:33, 08:58–09:08, 09:26–10:07, 10:23–10:25.
  - A-0 A04 / A05 #1 / A05 #2 : mêmes fenêtres, ce qui évoque des réponses manquées de la
    passerelle A-0. A05 #2 et A-2 A23 #1 sont encore indisponibles à 10:23.
  - D-1 Local APEL #1 : 00:46 → 09:50 (toute la matinée).
  - E-2 E22 #2 : 00:46–02:28, 03:02–04:45, 06:10–07:01, 07:17–08:24 (tête manipulée dans la
    matinée, mais les coupures commencent avant).
  - D-0 Réfectoire #1/#2/#3 : alternance disponible/indisponible toute la nuit, d'environ
    17 min à quelques heures.
  - D-0 Cuisine : préchauffe indisponible du 18/11 13:11 au 19/11 06:44. Elle était `online`
    jusqu'à 23:04 : il y a d'abord un défaut de lecture locale, puis la tête passe hors ligne.
- **Cas cohérent avec `online`** : E-0 Préau #5 (21:33 → 07:09) et E-0 Circulation Buanderie
  (23:08 → 09:32). Ici, `online=off` rend toute la tête indisponible, préchauffe comprise.
- Aucune de ces fenêtres ne montre un ON/OFF fictif : soit le switch a une valeur lue en local,
  soit il est indisponible.
- **Non observé** : une coupure totale du tunnel (échec de `survey_preheat`, `UpdateFailed`), qui
  rendrait tous les switches préchauffe indisponibles en laissant les autres entités
  disponibles. Pour la couvrir, il faudrait un essai provoqué, par exemple en coupant
  `enable_local` ou l'accès à une passerelle. Ce serait une écriture, à décider par Rémi et la
  session de validation.

## Points à écarter ou à interpréter avec prudence

- **C-1 Salle ASH** : vanne ouverte à 07:09, drapeau cloud à 07:06, soit 80 min d'avance. Cela
  ressemble à une préchauffe normale, mais la pièce a été manipulée entre 08:30 et 10:30 : elle
  est donc écartée du verdict.
- **E-2** (E21, E22, E23, sanitaires, lave-mains, escaliers) : têtes manipulées ce matin. Leur
  comportement avant 08:30 est cohérent avec P-1, mais elles sont exclues des chiffres.
- **A-0 Hall Garderie** : vanne à 98–100 % sans interruption depuis le 18/11 après-midi. Elle
  n'atteint probablement pas sa consigne. Ce n'est pas un signal de préchauffe : écartée.
- **D-0 Cuisine** : hors ligne jusqu'à 06:42 pour un créneau à 07:00, vanne à 99 % dès sa
  reconnexion. Non concluant.
- **B-0 Clocher** : pas de programme relu, écarté.

## Observations annexes (hors périmètre, à suivre)

- **Préchauffe très en avance** : la médiane est de ~4 h. A-2 et les sanitaires de E-1 et E-2
  ouvrent dès 00:40–01:50, soit jusqu'à 7 h 50 d'avance.
  - Sur plusieurs pièces, la température ne monte nettement qu'**entre 06:00 et 07:00**, quelle
    que soit l'heure d'ouverture de la vanne. Les pièces sont ensuite à ~21 °C vers 07:00, soit
    1 h 30 avant le créneau.
  - Hypothèse : la chaufferie ne fournit de l'eau chaude qu'à partir de ~06:00 (à vérifier côté
    ebusd/Weishaupt). L'algorithme adaptatif de la tête « apprend » alors une montée très lente
    et anticipe de plus en plus. Il y a là un enjeu d'énergie et de réglage, pas de bug de
    l'intégration.
- **Entités orphelines** : `switch.b_0_chapelle_{1..4}_pre_heating`,
  `switch.a_0_secretariat_pre_heating` (l'entité vivante est `…_pre_heating_2`) et
  `switch.d_1_local_apel_3_pre_heating` sont restaurées `unavailable` sans tête correspondante
  dans l'intégration (99 têtes mappées). Elles sont à nettoyer, et à ne pas confondre avec
  P-3.

## Proposition d'essai contrôlé (non exécuté, à valider par Rémi)

Objectif : valider le **chemin d'écriture** (switch → 0x0025) et P-2 sur une pièce occupée.
Fenêtre proposée : la nuit du jeudi 19 au vendredi 20/11, créneau vendredi 08:30.

| Action (par la session de validation, seule à écrire) | Tête | Attendu vendredi |
|---|---|---|
| `switch.turn_off` sur `switch.e_1_e13_pre_heating` | E-1 E13 (aujourd'hui ON, démarrage 06:18) | vanne fermée jusqu'à ~08:30, pas de drapeau cloud |
| `switch.turn_on` sur `switch.e_1_local_photocopieur_pre_heating` | E-1 Local Photocopieur (aujourd'hui OFF, démarrage 08:34) | ouverture anticipée avant 08:30, drapeau cloud ON |

- Vérification immédiate après chaque bascule : `danfoss_local_tete` doit relire
  `pre_chauffage` à la nouvelle valeur.
- Remise en état vendredi après 09:00 : rétablir les deux valeurs d'origine.
- Risque : E-1 E13 sera plus froide à l'arrivée des élèves vendredi (≈17 °C à 08:30 au lieu de
  ~21,8 °C). Il vaut mieux choisir une pièce peu occupée tôt si Rémi préfère.
