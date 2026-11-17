# Publier `pydanfoss-cloud` sur PyPI (R-4)

La couche `api/` de l'intégration est packagée sous le nom **`pydanfoss-cloud`** (voir
`pyproject.toml` : `package-dir` mappe `pydanfoss_cloud` → `custom_components/danfoss_ally_cloud/api`,
**sans déplacer les fichiers**). Une fois publiée, le connecteur MCP `danfoss-ally-mcp` pourra en
dépendre par `pip install pydanfoss-cloud` au lieu de l'installation éditable.

Nom vérifié **libre** sur PyPI au 17/11/2026.

## 1. Construire et vérifier (fait, reproductible)

```bash
cd ~/dev/ha-danfoss-ally
.venv/bin/pip install --upgrade build twine
rm -rf dist build
.venv/bin/python -m build          # → dist/pydanfoss_cloud-<version>.tar.gz + .whl
.venv/bin/twine check dist/*       # doit afficher PASSED pour les deux artefacts
```

Le wheel doit contenir tous les sous-paquets : `pydanfoss_cloud`, `pydanfoss_cloud._tuya`,
`pydanfoss_cloud.local` (dont `local/tunnel.py`), plus `LICENSE` et le `README.md` (long_description
en markdown).

## 2. Publier — étape de Rémi (compte PyPI requis)

L'upload se fait sous le compte PyPI de Rémi, avec un **jeton d'API** (jamais mot de passe) ; Claude
ne publie pas sous son identité.

Recommandé : d'abord un essai sur **TestPyPI**, puis PyPI.

```bash
# (optionnel) essai sur TestPyPI
.venv/bin/twine upload --repository testpypi dist/*
# publication réelle
.venv/bin/twine upload dist/*
```

Le jeton se configure dans `~/.pypirc` ou via `TWINE_USERNAME=__token__` /
`TWINE_PASSWORD=pypi-…`. Ne jamais committer le jeton.

## 3. Brancher le connecteur MCP sur la version publiée (après l'upload)

Dans `~/dev/danfoss-ally-mcp/pyproject.toml`, ajouter la dépendance (le `[local]` si le tunnel est
utilisé) et retirer l'installation éditable :

```toml
dependencies = [
    "mcp>=1.2",
    "httpx>=0.27",
    "pydanfoss-cloud>=0.1.0",   # (ajouter ; extra [local] si le tunnel Zigbee est utilisé)
]
```

Mettre à jour le commentaire (lignes ~16-22) et le `README.md` du MCP (section pydanfoss-cloud) pour
dire que la lib vient désormais de PyPI, puis valider :

```bash
cd ~/dev/danfoss-ally-mcp
.venv/bin/pip install -e .          # tire pydanfoss-cloud depuis PyPI
.venv/bin/pytest                    # 65 tests doivent rester verts
```

## 4. Versionnage

- API **non officielle** : figer une version exacte côté MCP plutôt que suivre `latest`.
- Faire évoluer la version de `pydanfoss-cloud` (`pyproject.toml` racine) à chaque changement de la
  couche `api/` ; republier (étapes 1-2) puis remonter la borne côté MCP.
