# pydanfoss-cloud

Access library for the **unofficial Danfoss Ally cloud API** (path 1a, the mobile app's one — with
no developer app and no shared quota), extracted from the Home Assistant integration
[`danfoss_ally_cloud`](https://github.com/aghulas/ha-danfoss-ally). **No Home Assistant dependency.**

It provides:

- `CloudClient` — email/password login (+ installation secrets), list of heads, guarded writes
  (`tuya.m.custom.wkf.settings.change`), robust re-authentication.
- `decode` / `DanfossDevice` — decoding of the Tuya `dps` into a normalised model (product schema
  `03wvrwpv`), decoding of the E1–E15 fault codes.
- `writes` — value validation before sending and a per-model guard-rail.
- `keys` — fetching the gateways' `localKey` + LAN IP from the cloud.
- `local/` — local Zigbee tunnel (DP 198→199, tinytuya): attribute read/write (preheat 0x0025),
  weekly schedule.

## Extraction status (roadmap v0.6)

**Single** source: this folder (`custom_components/danfoss_ally_cloud/api/`). It is packaged under
the name `pydanfoss_cloud` by the repo's `pyproject.toml`, **without moving files**:

- the Home Assistant integration keeps "vendoring" this code (relative import `from .api import …`),
  which keeps the HACS install self-contained;
- the MCP connector (`danfoss-ally-mcp`) can depend on it via `pip install pydanfoss-cloud` once the
  library is **published to PyPI**, then the integration will switch to a `requirements` dependency
  in `manifest.json`.

Development install:

```
pip install -e .            # exposes the pydanfoss_cloud package
pip install -e '.[local]'   # + tinytuya for the local tunnel
```

## Dependencies

`pycryptodome`, `requests` (core); `tinytuya` (extra `local`, Zigbee tunnel). Python ≥ 3.12.

## Disclaimer

Undocumented API, obtained by observing the app's protocol: it can change or be cut off. Secrets
(session token, `localKey`, credentials): never logged or committed.
