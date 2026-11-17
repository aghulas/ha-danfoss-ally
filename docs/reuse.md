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

## Extraction en bibliothèque (v0.6)

La couche `custom_components/danfoss_ally_cloud/api/` est désormais **sans dépendance Home
Assistant** et packagée sous le nom **`pydanfoss-cloud`** par le `pyproject.toml` du dépôt
(`package-dir` pointant sur ce dossier, source unique, sans déplacement). Voir
`custom_components/danfoss_ally_cloud/api/README.md`.

- L'intégration continue de « vendre » ce code (import relatif) → installation HACS autonome.
- Le connecteur MCP pourra remplacer sa copie (`tuya/`, `local.py`, `modeles.py`) par une dépendance
  `pydanfoss-cloud` une fois la bibliothèque **publiée sur PyPI** (repo/compte à décider par Rémi).
- Ensuite seulement, l'intégration référencera la version dans `manifest.json -> requirements`.

## Voie officielle Danfoss (OAuth2) : hors lib, hors intégration

La **voie officielle Danfoss** — API publique `api.danfoss.com`, authentification **OAuth2** avec
application développeur et clé API — **reste dans le connecteur MCP `danfoss-ally-mcp`** (pour le
diagnostic et la compatibilité) et **n'entre ni dans `pydanfoss-cloud` ni dans l'intégration**.

C'est un **choix de conception assumé**, pas un manque : l'intégration et la bibliothèque sont
**cloud-first voie 1a**, c.-à-d. la même API cloud que l'application mobile, précisément pour
**éviter l'application développeur et son quota partagé** (voir README et `architecture.md`). Faire
entrer OAuth2 dans la lib ré-introduirait exactement la dépendance que ce projet écarte.

**Donc : ne pas porter la voie OAuth2 dans `pydanfoss-cloud`.** Si un besoin de diagnostic l'exige,
il passe par le connecteur MCP, qui la conserve à part.
