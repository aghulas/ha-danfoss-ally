/**
 * Localisation minimale de la carte (fr / en), le temps que le lot 4 câble la
 * carte sur le mécanisme de localisation du frontend HA. Aucun texte visible
 * n'est écrit en dur dans les composants : tout passe par `t()`.
 */
import type { HassLike } from "./types";

type Dict = Record<string, string>;

const STRINGS: Record<"en" | "fr", Dict> = {
  en: {
    card_name: "Danfoss Ally — Schedule",
    card_description:
      "Weekly schedule of a Danfoss Ally room (cloud). Minimal card — editing comes later.",
    no_room: "No room selected",
    unknown_room: "Unknown room ({id})",
    version: "Version {version}",
    reload_available: "A new version of the card is available.",
    reload: "Reload",
    pick_room: "Room",
    rooms_unavailable:
      "Room list unavailable (the integration may not expose it yet).",
    read_only: "Read-only (not an administrator).",
  },
  fr: {
    card_name: "Danfoss Ally — Programme",
    card_description:
      "Programme hebdomadaire d'une pièce Danfoss Ally (cloud). Carte minimale — l'édition viendra plus tard.",
    no_room: "Aucune pièce choisie",
    unknown_room: "Pièce inconnue ({id})",
    version: "Version {version}",
    reload_available: "Une nouvelle version de la carte est disponible.",
    reload: "Recharger",
    pick_room: "Pièce",
    rooms_unavailable:
      "Liste des pièces indisponible (l'intégration ne l'expose peut-être pas encore).",
    read_only: "Lecture seule (pas administrateur).",
  },
};

function lang(hass: HassLike | undefined): "en" | "fr" {
  const code = (hass?.language ?? "en").toLowerCase();
  return code.startsWith("fr") ? "fr" : "en";
}

/** Traduit une clé, avec substitution `{nom}` -> valeur. */
export function t(
  hass: HassLike | undefined,
  key: keyof (typeof STRINGS)["en"],
  vars: Record<string, string | number> = {},
): string {
  const dict = STRINGS[lang(hass)];
  let text = dict[key] ?? STRINGS.en[key] ?? String(key);
  for (const [name, value] of Object.entries(vars)) {
    text = text.replace(`{${name}}`, String(value));
  }
  return text;
}
