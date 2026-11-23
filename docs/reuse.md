# Reuse of existing code

| Need | Where to take it from |
|---|---|
| Cloud API client, signature | `~/dev/danfoss-ally-signing-re` |
| Fetching gateway keys (path 1a) | `~/dev/danfoss-ally-mcp` → `danfoss_ally_mcp/tuya/pilote_tuya.py` (`cles_etat`, `_parc_1a`, `_lire_maitre`) |
| DP read/write, rooms, schedules | `~/dev/danfoss-ally-mcp` → `tuya/pilote_tuya.py` |
| Zigbee tunnel DP 198/199, pure frames | `~/dev/danfoss-ally-mcp` → `danfoss_ally_mcp/local.py` (`trame_*`, `decoder_*`, `Lien`, `releve`) |
| Fault-code decoding E1..E15 | `~/dev/danfoss-ally-mcp` → `danfoss_ally_mcp/modeles.py` (`decoder_defaut`, `DEFAUTS_BITS`) |
| Official DP names | `~/dev/danfoss-app-capture/dp_schema_officiel.md` |
| Decoding the Zigbee frames pushed in DP 199 over Tuya cloud MQTT | this repo → `api/local/tunnel.py` (`decode_frame`, `decode_attributes`): same layout as the LAN tunnel (`docs/cloud-mqtt-channel.md` §7) |
| Listen-only capture of the Tuya cloud MQTT push | `~/dev/danfoss-ally-mcp` → `danfoss_ally_mcp/tuya/mqtt_cloud.py` (`ecoute_lancer`, `resumer`) |
| Write guard-rails (model) | `~/dev/danfoss-ally-mcp` → `ecritures.py` (value validation) |

Note: the MCP connector keeps its prepare→confirm logic (specific to the MCP). In the HA
integration, write safety comes from value validation and diagnostics redaction, not from a
confirmation token.

## Extraction into a library (v0.6)

The `custom_components/danfoss_ally_cloud/api/` layer is now **free of any Home Assistant
dependency** and packaged under the name **`pydanfoss-cloud`** by the repo's `pyproject.toml`
(`package-dir` pointing at this folder, single source, without moving files). See
`custom_components/danfoss_ally_cloud/api/README.md`.

- The integration keeps "vendoring" this code (relative import) → self-contained HACS install.
- The library is **published to PyPI** (`docs/publishing-pydanfoss-cloud.md`); the MCP connector
  depends on it for the fault decoding and the cloud-MQTT codec and link (extra `mqtt`), and can
  progressively replace the rest of its copy (`tuya/`, `local.py`).
- The integration may later reference the version in `manifest.json -> requirements` instead of
  vendoring.

## Official Danfoss path (OAuth2): outside the lib, outside the integration

The **official Danfoss path** — public API `api.danfoss.com`, **OAuth2** authentication with a
developer app and an API key — **stays in the MCP connector `danfoss-ally-mcp`** (for diagnostics
and compatibility) and **enters neither `pydanfoss-cloud` nor the integration**.

This is a **deliberate design choice**, not a gap: the integration and the library are
**cloud-first path 1a**, i.e. the same cloud API as the mobile app, precisely to **avoid the
developer app and its shared quota** (see README and `architecture.md`). Bringing OAuth2 into the
lib would reintroduce exactly the dependency this project avoids.

**So: do not port the OAuth2 path into `pydanfoss-cloud`.** If a diagnostic need requires it, it
goes through the MCP connector, which keeps it separate.
