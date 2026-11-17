/// <reference types="vitest/config" />
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const here = (p: string): string => fileURLToPath(new URL(p, import.meta.url));

// Version injectée au build = version du manifest de l'intégration. Même source
// que la commande WebSocket `danfoss_ally_cloud/info` -> le contrôle de version
// de la carte (contrat §6) compare bien deux valeurs issues du manifest.
const manifest = JSON.parse(
  readFileSync(
    here("../custom_components/danfoss_ally_cloud/manifest.json"),
    "utf8",
  ),
) as { version: string };

export default defineConfig({
  define: {
    __CARD_VERSION__: JSON.stringify(manifest.version),
  },
  build: {
    // Un seul fichier versionné, servi tel quel par HACS depuis n'importe quelle
    // branche / étiquette : aucune dépendance chargée au vol.
    outDir: here("../custom_components/danfoss_ally_cloud/frontend"),
    emptyOutDir: false,
    target: "es2021",
    // Sortie NON minifiée : stable d'une version d'outil/Node à l'autre, pour que
    // la CI ne rougisse pas sur une diff cosmétique (cf. cahier des charges lot 3).
    minify: false,
    sourcemap: false,
    cssCodeSplit: false,
    lib: {
      entry: here("src/main.ts"),
      formats: ["es"],
      fileName: () => "danfoss-ally-cloud.js",
    },
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
      },
    },
  },
  test: {
    // Logique pure : environnement Node suffit (pas de DOM).
    environment: "node",
    include: ["test/**/*.test.ts"],
  },
});
