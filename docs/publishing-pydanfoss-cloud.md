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
`pydanfoss_cloud.local` (including `local/tunnel.py`), plus `LICENSE` and the `README.md`
(long_description in markdown).

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

In `~/dev/danfoss-ally-mcp/pyproject.toml`, add the dependency (plus `[local]` if the tunnel is
used) and remove the editable install:

```toml
dependencies = [
    "mcp>=1.2",
    "httpx>=0.27",
    "pydanfoss-cloud>=0.2.0",   # (add; extra [local] if the Zigbee tunnel is used)
]
```

Update the comment (lines ~16-22) and the MCP's `README.md` (pydanfoss-cloud section) to say the
lib now comes from PyPI, then validate:

```bash
cd ~/dev/danfoss-ally-mcp
.venv/bin/pip install -e .          # pulls pydanfoss-cloud from PyPI
.venv/bin/pytest                    # the 65 tests must stay green
```

## 4. Versioning

- **Unofficial** API: pin an exact version on the MCP side rather than following `latest`.
- Bump the `pydanfoss-cloud` version (root `pyproject.toml`) on every change to the `api/` layer;
  republish (steps 1-2) then raise the bound on the MCP side.
