# Changelog

## 0.3.0 — English base language

The whole repository is now authored in **English** (code, docstrings, comments, docs),
with user-facing strings translated per Home Assistant's configured language. The **French
translation is kept** (`translations/fr.json`), so a Home Assistant set to French still shows
French labels.

### Migration — automatic, no action required

Entity `unique_id` slugs were anglicised (for example `…_consigne_confort` → `…_comfort_setpoint`,
`…_detection_fenetre` → `…_window_detection`). On the **first start after updating**, existing
entities are migrated automatically (`async_migrate_entries`): their **`entity_id`, history,
automations and dashboards are preserved**. The migration is idempotent and conservative.

- A Home Assistant running **in English** sees **no visible change** (the `entity_id`s were already
  English; only the internal `unique_id` is remapped).
- A Home Assistant running **in French** keeps its existing French `entity_id`s unchanged.

### Changed

- English as the base language across code, docstrings, comments, docs and `README`.
- Shared library **`pydanfoss-cloud` 0.2.0**: public API renamed to English
  (`FAULT_BITS`, `decode_fault`, `decode_device`, …) and published to PyPI. The MCP connector
  `danfoss-ally-mcp` was updated in lockstep.

### Fixed

- Diagnostics now **redact the account `username`** (the account e-mail — personal data that was
  previously left in clear).

## 0.2.0

- Per-room `climate`, `number` comfort/setback setpoints, weekly schedule card (read + write).

## 0.1.0

- Initial cloud read/write, local tunnel (preheat, schedule read), MQTT publisher.
