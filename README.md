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

## État

Amorçage (squelette). Voir `docs/roadmap.md`.
