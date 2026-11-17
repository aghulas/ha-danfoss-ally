# Interface embarquée — `frontend/`

Sources TypeScript + Lit de la carte de tableau de bord livrée par l'intégration
`danfoss_ally_cloud`. Le build produit **un seul fichier**, versionné dans le dépôt :
`../custom_components/danfoss_ally_cloud/frontend/danfoss-ally-cloud.js`.

## Commande de build EXACTE

```bash
npm ci        # dépendances épinglées (package-lock.json)
npm run build # régénère le bundle versionné
```

Le bundle est **versionné** pour que l'installation HACS fonctionne depuis n'importe
quelle branche ou étiquette (aucune dépendance chargée au vol). La CI
(`.github/workflows/frontend.yml`) rejoue ce build et **échoue** si le fichier
versionné n'est pas à jour.

### Déterminisme

- Node épinglé par `.nvmrc` (la CI l'utilise) ; dépendances épinglées par
  `package-lock.json` (`npm ci`).
- Sortie **non minifiée** (`vite.config.ts`, `minify: false`) : stable d'une version
  d'outil à l'autre, pour que la CI ne rougisse pas sur une diff cosmétique. La sortie
  de Rollup/esbuild dépend de la version des outils (verrouillée), pas de la version de
  Node ni de la plateforme.
- La version de la carte est injectée au build depuis `manifest.json`
  (`__CARD_VERSION__`), même source que la commande WebSocket `danfoss_ally_cloud/info`.

## Autres commandes

| Commande | Rôle |
|---|---|
| `npm test` | tests unitaires Vitest (logique pure) |
| `npm run typecheck` | vérification TypeScript (`tsc --noEmit`) |
| `npm run demo` | page de démonstration hors Home Assistant (données synthétiques), sur http://localhost:5173/demo/ |

## Arborescence

- `src/` — sources de la carte (`schedule-card.ts`, éditeur, WebSocket, version, i18n).
- `demo/` — page de démonstration (faux `hass`, données d'essai synthétiques).
- `test/` — tests Vitest.
- `vite.config.ts` — build (bundle unique) et config Vitest.

Le contrat d'interface fait foi : `../docs/interface-contract.md` (section 6).
