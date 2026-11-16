# Danfoss Ally (Cloud) — intégration Home Assistant

Intégration communautaire **non officielle** pour les têtes thermostatiques
Danfoss Ally, qui parle à la **même API cloud que l'application mobile** — sans
application développeur ni clé API, sans quota partagé.

Objectifs :
- mise en route simple (identifiants de l'app) ;
- toutes les fonctions du cloud, y compris celles absentes de l'API publique
  (programme hebdomadaire, détection de fenêtre, verrouillage enfant…) ;
- récupération automatique des **clés locales des passerelles** pour un accès
  Zigbee direct, sans émulateur ni Frida ;
- **publication MQTT** des appareils, en deux modes configurables : MQTT
  Discovery de HA, ou structure de topics compatible zigbee2mqtt.

## Avertissement

Projet indépendant, **non affilié à Danfoss ni à Tuya**. L'API cloud est
non documentée et obtenue par observation du protocole réseau de l'application.
Elle peut changer ou être coupée à tout moment, ce qui casserait l'intégration.
À utiliser à vos risques. Les mots de passe ne sont jamais demandés par Home
Assistant en dehors de l'écran de connexion de l'intégration.

## Installation (dépôt custom)

1. HACS → ⋮ → Dépôts personnalisés → ajouter `https://github.com/aghulas/ha-danfoss-ally` (catégorie Intégration).
2. Installer « Danfoss Ally (Cloud) », redémarrer Home Assistant.
3. Réglages → Appareils et services → Ajouter une intégration.

## Configuration

L'écran de configuration demande :

- **Identifiant / Mot de passe** : le compte de l'application Danfoss Ally / Smart Life.
- **Indicatif pays** : ex. `33` pour la France.
- **Datacenter** : `eu`, `us`, `cn` ou `in` (France → `eu`).
- **Secrets d'installation** : `sign_key`, `device_id` (`deviceId`), `ch_key` (`chKey`).

Les trois secrets d'installation sont propres à une installation de l'application et **se
capturent une fois** (ils restent stables ensuite). Ils sont indispensables à la signature et au
chiffrement de l'API mobile Tuya ; le serveur refuse un `chKey` inconnu. La méthode de capture est
décrite dans `docs/` (hook natif / capture réseau). Ces valeurs, le mot de passe et le matériel de
session (`sid`/`ecode`) sont des **secrets** : ils ne sont jamais écrits dans les journaux ni les
diagnostics (voir `diagnostics.py`).

## État

**v0.1 — lecture seule cloud** : chaque tête apparaît comme un thermostat (température, consigne) ;
capteurs batterie, ouverture de vanne, code défaut ; capteurs binaires en ligne / fenêtre. Pas
encore d'écriture. Voir `docs/roadmap.md`.
