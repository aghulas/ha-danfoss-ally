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

## Sécurité

Jetons de session et localKey sont des secrets : jamais dans les logs, les
diagnostics ni le dépôt. Défauts de polling conservateurs (sécurité du compte
réel de l'utilisateur). Re-authentification robuste (Tuya invalide la session
quand l'app se reconnecte).

## Codes DP

Source de vérité : `~/dev/danfoss-app-capture/dp_schema_officiel.md`. Pièges
repris dans `const.py` (DP 18 = borne haute, 171 = consigne, 114 = manuel,
1 = pré-chauffage, 30 = verrou enfant, 116 = fenêtre, 162 = demande de chaleur).
