# Publishing `pydanfoss-cloud` to PyPI (R-4)

The integration's `api/` layer is packaged under the name **`pydanfoss-cloud`** (see
`pyproject.toml`: `package-dir` maps `pydanfoss_cloud` → `custom_components/danfoss_ally_cloud/api`,
**without moving files**). Once published, the MCP connector `danfoss-ally-mcp` can depend on it via
`pip install pydanfoss-cloud` instead of the editable install.

Name verified **available** on PyPI as of 2026-11-17.

## 1. Build and verify (done, reproducible)

```bash
cd ~/dev/ha-danfoss-ally
.venv/bin/pip install --upgrade build twine
rm -rf dist build
.venv/bin/python -m build          # → dist/pydanfoss_cloud-<version>.tar.gz + .whl
.venv/bin/twine check dist/*       # must print PASSED for both artifacts
```

The wheel must contain all sub-packages: `pydanfoss_cloud`, `pydanfoss_cloud._tuya`,
`pydanfoss_cloud.local` (including `local/tunnel.py`), the MQTT modules (`mqtt_publish.py`,
`mqtt_client.py`), plus `LICENSE` and the `README.md` (long_description in markdown). Its metadata
must declare the extras `local` (tinytuya) and `mqtt` (paho-mqtt `>=1.6.1,<3`). CI checks the wheel
content and the imports on every push (`.github/workflows/test.yml`); to check a build by hand in a
clean environment:

```bash
python3 -m venv /tmp/pdc && /tmp/pdc/bin/pip install "dist/pydanfoss_cloud-<version>-py3-none-any.whl[mqtt]"
/tmp/pdc/bin/python -c "from pydanfoss_cloud import CloudClient, mqtt_publish, mqtt_client"
```

## 2. Publish — Rémi's step (PyPI account required)

The upload is done under Rémi's PyPI account, with an **API token** (never a password); Claude does
not publish under its own identity.

Recommended: first a dry run on **TestPyPI**, then PyPI.

```bash
# (optional) dry run on TestPyPI
.venv/bin/twine upload --repository testpypi dist/*
# real publish
.venv/bin/twine upload dist/*
```

The token is configured in `~/.pypirc` or via `TWINE_USERNAME=__token__` /
`TWINE_PASSWORD=pypi-…`. Never commit the token.

## 3. Point the MCP connector at the published version (after the upload)

In `~/dev/danfoss-ally-mcp/pyproject.toml`, raise the bound (plus the extras the connector uses)
and make sure its venv no longer points at an editable install of this repository:

```toml
dependencies = [
    "mcp>=1.2",
    "httpx>=0.27",
    "pydanfoss-cloud>=0.3.0",   # extras: [local] for the Zigbee tunnel, [mqtt] for the cloud-MQTT link
]
```

Update the comment (lines ~16-22) and the MCP's `README.md` (pydanfoss-cloud section) to say the
lib now comes from PyPI, then validate:

```bash
cd ~/dev/danfoss-ally-mcp
.venv/bin/pip install -e .          # pulls pydanfoss-cloud from PyPI
.venv/bin/pytest                    # the whole suite must stay green
```

## 4. Versioning

- **Unofficial** API: pin an exact version on the MCP side rather than following `latest`.
- Bump the `pydanfoss-cloud` version (root `pyproject.toml`) on every change to the `api/` layer;
  republish (steps 1-2) then raise the bound on the MCP side. Note the change in the "Changes"
  section of `custom_components/danfoss_ally_cloud/api/README.md` (the PyPI long description) and in
  `CHANGELOG.md`.
- Released: 0.2.0 (English public API, first PyPI release); 0.3.0 (`gw_id` on `async_write_setting`, distinct deviceId,
  cloud-MQTT modules, `[mqtt]` extra).
- Prepared, **not published yet**: 0.3.1 (candidate DPs on the cloud-MQTT write path
  (`MQTT_CANDIDATE_DPS`, `mqtt_dp_open`, `supervised` argument of `mqtt_write_value`); completeness
  indicators of the device list on `CloudClient`). The later DPs of the cloud-MQTT stack (bounds,
  isolated-head setpoints) also add to `api/writes.py` and `api/const.py`: if they merge after
  0.3.1 is published they need their own bump; if before, they belong in the 0.3.1 notes.
