/**
 * Point d'entrée du bundle `danfoss-ally-cloud.js`.
 *
 * Importe la carte (qui définit les éléments personnalisés via `@customElement`)
 * et l'inscrit au sélecteur de cartes de Lovelace (`window.customCards`), afin
 * qu'elle apparaisse dans le sélecteur après installation par HACS, sans
 * manipulation manuelle (critère de fin du lot 3).
 */
import "./schedule-card";
import { CARD_VERSION } from "./version";

const CARD_TYPE = "danfoss-ally-schedule-card";

window.customCards = window.customCards ?? [];
if (!window.customCards.some((card) => card.type === CARD_TYPE)) {
  window.customCards.push({
    type: CARD_TYPE,
    // Textes du sélecteur : le frontend HA n'est pas encore localisé pour cette
    // carte au lot 3 ; libellés bilingues courts en attendant le lot 4.
    name: "Danfoss Ally — Programme / Schedule",
    description:
      "Programme hebdomadaire d'une pièce Danfoss Ally (cloud). / Weekly schedule of a Danfoss Ally room.",
    preview: false,
    documentationURL: "https://github.com/aghulas/ha-danfoss-ally",
  });
}

// eslint-disable-next-line no-console
console.info(
  `%c DANFOSS-ALLY-CLOUD %c ${CARD_VERSION} `,
  "color:#fff;background:#e2001a;font-weight:700",
  "color:#e2001a;background:#fff",
);
