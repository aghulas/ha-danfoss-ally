/**
 * Jeton remplacé au build par Vite (`define`) avec la version du manifest de l'intégration.
 * Déclaré ici pour que TypeScript et Vitest l'acceptent même hors build.
 */
declare const __CARD_VERSION__: string;

interface Window {
  // Registre des cartes personnalisées lu par le sélecteur de cartes de Lovelace.
  customCards?: Array<{
    type: string;
    name: string;
    description?: string;
    preview?: boolean;
    documentationURL?: string;
  }>;
}
