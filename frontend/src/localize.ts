/**
 * Localisation minimale de la carte (fr / en), le temps que le lot 4 câble la
 * carte sur le mécanisme de localisation du frontend HA. Aucun texte visible
 * n'est écrit en dur dans les composants : tout passe par `t()`.
 */
import type { DayKey, HassLike } from "./types";

type Dict = Record<string, string>;

const STRINGS = {
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
    rooms_unavailable: "Room list unavailable (the integration may not expose it yet).",
    read_only: "Read-only (not an administrator).",
    comfort: "Comfort",
    setback: "Setback",
    refresh: "Refresh",
    last_read: "Last read {when}",
    never_read: "Not read yet",
    schedule_unavailable:
      "Schedule unavailable (not yet exposed by the integration).",
    setback_all_day: "Setback all day",
    heads_heading: "Thermostats",
    heads_none: "No thermostat in this room.",
    head_online: "Online",
    head_offline: "Offline",
    head_schedule_on: "Schedule active",
    head_schedule_off: "Not following the schedule",
    head_inconsistent: "Inconsistent (left in manual mode)",
    head_mounting: "Mounting mode (not regulating)",
    day_mon: "Mon",
    day_tue: "Tue",
    day_wed: "Wed",
    day_thu: "Thu",
    day_fri: "Fri",
    day_sat: "Sat",
    day_sun: "Sun",
    range_label: "Comfort {start}–{end}",
    degree: "{value} °C",
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
    comfort: "Confort",
    setback: "Réduit",
    refresh: "Actualiser",
    last_read: "Dernière lecture {when}",
    never_read: "Pas encore lu",
    schedule_unavailable:
      "Programme indisponible (pas encore exposé par l'intégration).",
    setback_all_day: "Réduit toute la journée",
    heads_heading: "Têtes",
    heads_none: "Aucune tête dans cette pièce.",
    head_online: "En ligne",
    head_offline: "Hors ligne",
    head_schedule_on: "Programme actif",
    head_schedule_off: "Ne suit pas le programme",
    head_inconsistent: "Incohérente (restée en manuel)",
    head_mounting: "Mode montage (ne régule pas)",
    day_mon: "Lun",
    day_tue: "Mar",
    day_wed: "Mer",
    day_thu: "Jeu",
    day_fri: "Ven",
    day_sat: "Sam",
    day_sun: "Dim",
    range_label: "Confort {start}–{end}",
    degree: "{value} °C",
  },
} satisfies Record<"en" | "fr", Dict>;

function lang(hass: HassLike | undefined): "en" | "fr" {
  const code = (hass?.language ?? "en").toLowerCase();
  return code.startsWith("fr") ? "fr" : "en";
}

type StringKey = keyof (typeof STRINGS)["en"];

/** Traduit une clé, avec substitution `{nom}` -> valeur. */
export function t(
  hass: HassLike | undefined,
  key: StringKey,
  vars: Record<string, string | number> = {},
): string {
  const dict = STRINGS[lang(hass)];
  let text = dict[key] ?? STRINGS.en[key] ?? String(key);
  for (const [name, value] of Object.entries(vars)) {
    text = text.replace(`{${name}}`, String(value));
  }
  return text;
}

const DAY_LABEL_KEYS: Record<DayKey, StringKey> = {
  mon: "day_mon",
  tue: "day_tue",
  wed: "day_wed",
  thu: "day_thu",
  fri: "day_fri",
  sat: "day_sat",
  sun: "day_sun",
};

/** Libellé court et localisé d'un jour (`mon` → « Lun » / « Mon »). */
export function dayLabel(hass: HassLike | undefined, day: DayKey): string {
  return t(hass, DAY_LABEL_KEYS[day]);
}

/** Langue effective ('en' ou 'fr') pour formater dates et nombres. */
export function language(hass: HassLike | undefined): "en" | "fr" {
  return lang(hass);
}
