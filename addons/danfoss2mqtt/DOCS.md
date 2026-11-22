# Home Assistant Add-on: danfoss2mqtt

Pont autonome **Danfoss Ally Cloud → Mosquitto** parlant le dialecte **Zigbee2MQTT** (`docs/companion-contract.md`).

Il tourne à côté de **Mosquitto** et **Zigbee2MQTT** (comme `ebusd` pour une chaudière) et expose les têtes restées sur une passerelle Danfoss Ally sous `danfoss2mqtt/<nom_tete>`, exactement comme des têtes Zigbee2MQTT.

L'intégration **Danfoss Ally Companion (v2)** se connecte ensuite uniquement à Mosquitto et pilote indifféremment les têtes `zigbee2mqtt` et `danfoss2mqtt`.

## Configuration

| Option | Description |
| --- | --- |
| `base_topic` | Préfixe MQTT du pont (défaut : `danfoss2mqtt`). |
| `mqtt_host` / `mqtt_port` / `mqtt_username` / `mqtt_password` | Laisser `mqtt_host` vide pour auto-découvrir l'add-on **Mosquitto broker** de Home Assistant. |
| `mqtt_tls` | Activer TLS vers le broker MQTT (défaut : `false`). |
| `username`, `password`, `country_code`, `region` | Identifiants du compte Danfoss Ally / Smart Life. |
| `sign_key`, `device_id`, `ch_key` | Secrets d'installation Danfoss Ally (identiques à la v1). |
| `poll_interval` | Intervalle de rafraîchissement cloud en secondes (15 à 600, défaut : 60). |

## Contrat MQTT

- `danfoss2mqtt/bridge/state` : `"online"` / `"offline"` (Last Will & Testament configuré).
- `danfoss2mqtt/bridge/devices` : inventaire au format Zigbee2MQTT.
- `danfoss2mqtt/<friendly_name>` : état JSON normalisé (`local_temperature`, `occupied_heating_setpoint`, `pi_heating_demand`, `battery`, …).
- `danfoss2mqtt/<friendly_name>/availability` : `"online"` / `"offline"`.
- `danfoss2mqtt/<friendly_name>/set` : commandes entrantes (`occupied_heating_setpoint`, `system_mode`, `keypad_lockout`, …).
- `danfoss2mqtt/bridge/request/refresh` : force un rafraîchissement immédiat.
