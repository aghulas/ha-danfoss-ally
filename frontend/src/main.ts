/**
 * Point d'entrée du bundle `danfoss-ally-cloud.js`.
 *
 * Importe la carte (qui définit les éléments personnalisés via `@customElement`)
 * et l'inscrit au sélecteur de cartes de Lovelace (`window.customCards`), afin
 * qu'elle apparaisse dans le sélecteur après installation par HACS, sans
 * manipulation manuelle (critère de fin du lot 3).
 */
import "./schedule-card";
import "./room-card";
import { CARD_VERSION } from "./version";

const DOC_URL = "https://github.com/aghulas/ha-danfoss-ally";

interface CustomCardEntry {
  type: string;
  name: string;
  description: string;
  preview?: boolean;
  documentationURL?: string;
}

const CARDS: CustomCardEntry[] = [
  {
    type: "danfoss-ally-schedule-card",
    // Libellés bilingues courts (le frontend HA ne localise pas encore ces entrées).
    name: "Danfoss Ally — Programme / Schedule",
    description:
      "Programme hebdomadaire d'une pièce Danfoss Ally (cloud). / Weekly schedule of a Danfoss Ally room.",
    preview: false,
    documentationURL: DOC_URL,
  },
  {
    type: "danfoss-ally-room-card",
    name: "Danfoss Ally — Pièce / Room",
    description:
      "Une pièce Danfoss Ally : climat, programme, têtes et actions. / A Danfoss Ally room: climate, schedule, thermostats and actions.",
    preview: false,
    documentationURL: DOC_URL,
  },
];

window.customCards = window.customCards ?? [];
for (const card of CARDS) {
  if (!window.customCards.some((c) => c.type === card.type)) {
    window.customCards.push(card);
  }
}

// eslint-disable-next-line no-console
console.info(
  `%c DANFOSS-ALLY-CLOUD %c ${CARD_VERSION} `,
  "color:#fff;background:#e2001a;font-weight:700",
  "color:#e2001a;background:#fff",
);
