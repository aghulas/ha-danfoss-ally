# Architecture

## Principe : cloud-first, repli local

L'API cloud couvre l'essentiel du contrôle. Mais on a établi en réel des cas
où le cloud **ment ou n'agit pas**, qu'il faut traiter en local :

- C'est le **passage en mode manuel** (DP 2 `manual`) qui efface le programme
  de la tête (R4). `at_home` / `leaving_home` publiés par le DP 2 ne sont que
  des **étiquettes** côté cloud : la tête garde la consigne de son programme
  (R5). Le passage confort/réduit et le retour au programme passent donc par la
  réécriture du programme de la pièce, pas par un simple write cloud du mode.
  Règles R1–R7 et appels : `docs/contrat-interface.md`.
- Pré-chauffage : écrire le DP 1 côté cloud ne change que le cache de la
  passerelle. Le vrai levier est l'attribut Zigbee **0x0025** (bit 0 programme,
  bit 1 pré-chauffage), accessible seulement par le tunnel local.
- `update_time` est un horodatage d'enregistrement événementiel : ne jamais en
  déduire la fraîcheur. `online` fait foi pour la connectivité.

Donc : **cloud par défaut, tunnel local (optionnel) pour les opérations que le
cloud rate**. La même intégration récupère les clés passerelles, donc le repli
local reste interne, sans rien demander de plus à l'utilisateur.

## Couches

- `api/client.py` — API cloud (voie 1a) : session, appareils, DP, pièces,
  programmes.
- `api/keys.py` — récupération des localKey des passerelles (remplace
  émulateur/Frida ; validé en réel).
- `api/local/tunnel.py` — tunnel Zigbee DP 198→199 (tinytuya) : programme réel,
  attribut 0x0025, vrais attributs.
- `coordinator.py` — polling cloud conservateur + superposition des vérités
  locales.
- Plateformes : `climate` (consigne, préréglages), `sensor` (batterie, vanne,
  demande de chaleur, code défaut), `binary_sensor` (en ligne, fenêtre),
  `number` (vacances, bornes), `switch` (verrou enfant, fenêtre, pré-chauffage).
- `mqtt_publisher.py` — publication MQTT, modes `discovery` / `zigbee2mqtt`,
  source `cloud` / `local`.
- `diagnostics.py` — rédaction stricte des secrets.

## Session Tuya partagée avec le connecteur MCP (deviceId commun)

L'intégration `danfoss_ally_cloud` et le connecteur MCP `danfoss-ally-mcp`
utilisent le **même matériel d'installation capturé de l'application** :
`deviceId`, `sign_key` et `chKey` (voir README, « Secrets d'installation »).
Côté serveur Tuya, ce triplet identifie **une seule installation**, donc **une
seule session active**. Si les deux clients tournent en parallèle contre le
compte réel, la connexion de l'un **invalide la session de l'autre** : ils se
délogent mutuellement, chacun déclenchant chez l'autre une ré-authentification,
d'où une boucle de reconnexions et des erreurs intermittentes (`session_expired`,
appels refusés) des deux côtés.

> Le connecteur `tuya-mcp` (radiateurs du bâtiment F) n'est **pas** concerné : il
> passe par le SDK de partage Smart Life avec son propre `terminal_id`.

### Règle opérationnelle (tant qu'un seul jeu de secrets existe)

**Ne jamais faire tourner les deux en même temps contre le compte réel.** Un seul
porteur de session à la fois :

- tant que le connecteur MCP sert (session Claude active sur `danfoss-ally-mcp`),
  l'intégration reste **désactivée** côté Home Assistant ;
- inversement, pour utiliser l'intégration en continu, on arrête d'utiliser le
  connecteur MCP sur ce compte.

Désactiver l'intégration côté HA la décharge **et** l'empêche de se recharger au
démarrage, ce qui libère la session ; un simple « recharger » ne suffit pas. État
actuel sur le Pi de l'école : l'intégration est `disabled_by: user` (désactivée),
le connecteur MCP garde donc la main. C'est un **contournement**, pas la cible.

### Piste de fond : une installation virtuelle distincte pour l'intégration

La vraie coexistence suppose de donner à l'intégration **son propre jeu de
secrets** (`deviceId` / `sign_key` / `chKey` distincts), c.-à-d. une **deuxième
« installation » virtuelle** de l'application vis-à-vis du serveur Tuya. Deux
installations = deux sessions indépendantes, qui ne se délogent plus.

Marche à suivre, au niveau conceptuel (étape manuelle **à venir**, non réalisée
ici) :

1. produire un nouveau triplet d'installation à l'aide du dépôt de signature
   `~/dev/danfoss-ally-signing-re` et de l'application réelle (capture / hook) —
   l'opération demande **Rémi** et l'app, elle ne peut pas être automatisée depuis
   ce dépôt ;
2. enregistrer cette installation sur le compte comme un appareil mobile
   supplémentaire (le serveur refuse un `chKey` inconnu : le triplet doit être un
   vrai couple installation ↔ compte, pas une valeur fabriquée) ;
3. configurer l'intégration avec ce triplet distinct, et réserver le triplet
   d'origine au connecteur MCP ;
4. vérifier en réel que les deux sessions coexistent sans se déloger.

Tant que cette capture n'est pas faite, la règle opérationnelle ci-dessus reste la
seule garantie contre les délogements mutuels.

## Sécurité

Jetons de session et localKey sont des secrets : jamais dans les logs, les
diagnostics ni le dépôt. Défauts de polling conservateurs (sécurité du compte
réel de l'utilisateur). Re-authentification robuste (Tuya invalide la session
quand l'app se reconnecte).

## Codes DP

Source de vérité : `~/dev/danfoss-app-capture/dp_schema_officiel.md`. Pièges
repris dans `const.py` (DP 18 = borne haute, 171 = consigne, 114 = manuel,
1 = pré-chauffage, 30 = verrou enfant, 116 = fenêtre, 162 = demande de chaleur).
