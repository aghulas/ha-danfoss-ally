# Réutilisation du code existant

| Besoin | Où le prendre |
|---|---|
| Client API cloud, signature | `~/dev/danfoss-ally-signing-re` |
| Récupération des clés passerelles (voie 1a) | `~/dev/danfoss-ally-mcp` → `danfoss_ally_mcp/tuya/pilote_tuya.py` (`cles_etat`, `_parc_1a`, `_lire_maitre`) |
| Lecture/écriture DP, pièces, programmes | `~/dev/danfoss-ally-mcp` → `tuya/pilote_tuya.py` |
| Tunnel Zigbee DP 198/199, trames pures | `~/dev/danfoss-ally-mcp` → `danfoss_ally_mcp/local.py` (`trame_*`, `decoder_*`, `Lien`, `releve`) |
| Décodage code défaut E1..E15 | `~/dev/danfoss-ally-mcp` → `danfoss_ally_mcp/modeles.py` (`decoder_defaut`, `DEFAUTS_BITS`) |
| Noms officiels des DP | `~/dev/danfoss-app-capture/dp_schema_officiel.md` |
| Garde-fous d'écriture (modèle) | `~/dev/danfoss-ally-mcp` → `ecritures.py` (validation des valeurs) |

Note : le connecteur MCP garde sa logique préparer→confirmer (propre au MCP).
Dans l'intégration HA, la sûreté d'écriture passe par la validation des valeurs
et la rédaction des diagnostics, pas par un jeton de confirmation.
