# Publishing `pydanfoss-cloud` to PyPI

`pydanfoss-cloud` is the Home-Assistant-free library behind this integration's `api/` layer (cloud
client, gateway keys, local tunnel, cloud-MQTT codec and link, the `danfoss2mqtt` daemon). Since
2026-11-22 it is released from **its own repository, `aghulas/pydanfoss-cloud`**, not from this
one. Latest release: **0.4.5**.

## Releasing (in `aghulas/pydanfoss-cloud`)

Publication uses PyPI **Trusted Publishing** (OIDC): no API token, nothing secret to configure.

1. Bump `version` in that repository's `pyproject.toml`; merge.
2. Create the tag `vX.Y.Z` and **publish** a GitHub release on it (a draft triggers nothing).
3. The `publish.yml` workflow (environment `pypi`) builds the wheel and the sdist and uploads them
   with provenance.

A PyPI version cannot be replaced: check the version and the notes before publishing the release.
After the upload, check the per-version endpoint rather than the project page (the aggregate is
cached for about a minute).

## Consumers

| Consumer | How it depends on the library |
|---|---|
| This integration | Vendors the `api/` folder (relative imports), so a HACS install is self-contained. The root `pyproject.toml` still maps `pydanfoss_cloud` onto that folder for the tests and the wheel check in CI; it is not the release source |
| MCP connector `danfoss-ally-mcp` | `pydanfoss-cloud` from PyPI, with the `mqtt` extra |
| `danfoss2mqtt` add-on | Pins an exact `pydanfoss-cloud[mqtt]` version in its image |

## Rules

- The API is **unofficial**: consumers pin a lower bound or an exact version, never `latest`.
- A change to `custom_components/danfoss_ally_cloud/api/` that the other consumers need must be
  carried to `aghulas/pydanfoss-cloud` and released there; note it in `CHANGELOG.md` here.
- The extras are `local` (tinytuya, Zigbee tunnel) and `mqtt` (paho-mqtt, cloud-MQTT link).
- The official Danfoss OAuth2 path stays out of the library (`docs/reuse.md`).
