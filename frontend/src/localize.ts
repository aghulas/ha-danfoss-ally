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
    // --- Lot 5 : édition ---
    edit: "Edit",
    cancel: "Cancel",
    save: "Save",
    saving: "Saving…",
    discard: "Discard changes",
    add_range: "Add a range",
    delete_range: "Delete this range",
    range_start: "Start",
    range_end: "End",
    transitions_count: "{n} / {max}",
    transitions_aria: "{day}: {n} of {max} transitions",
    transitions_label: "transitions",
    midnight_note: "The thermostat drops the midnight step and keeps the previous evening setpoint until the first range.",
    copy_day: "Copy to…",
    copy_apply: "Copy",
    copy_cancel: "Close",
    copy_heading: "Copy {day} to:",
    copy_select_all: "All days",
    no_changes: "No unsaved changes.",
    save_blocked: "Fix the invalid days before saving.",
    unsaved_hint: "Unsaved changes — save or discard.",
    leave_confirm: "Discard your unsaved schedule changes?",
    beforeunload: "You have unsaved schedule changes.",
    // Erreurs (contrat §5.4)
    err_invalid_time: "Invalid time",
    err_empty_or_reversed: "Empty or reversed range",
    err_overlap: "Overlapping ranges",
    err_too_many_transitions: "Too many transitions (max {max})",
    err_unknown_target: "Unknown room",
    err_grouped_device: "Grouped thermostat: target its room",
    err_not_admin: "You are not an administrator",
    err_cloud_refused: "The cloud refused the change",
    err_session_expired: "Session expired, retry shortly",
    err_unknown: "The change could not be sent",
    // Suivi du lot
    job_heading: "Last send",
    job_status_sent: "Sent to the cloud",
    job_status_applied: "Applied to all thermostats",
    job_status_partial: "Applied to some thermostats",
    job_status_unverified: "Sent (not verified)",
    job_status_failed: "Refused by the cloud",
    head_job_pending: "Pending",
    head_job_applied: "Applied",
    head_job_mismatch: "Different",
    head_job_unreachable: "Unreachable",
    head_job_unverified: "Not verified",
    // Retour au programme (R4)
    restore_schedule: "Back to schedule",
    restore_hint: "A thermostat no longer follows its schedule.",
    restore_done: "Restore sent.",
    // --- Axe D : carte pièce + panneau ---
    room_card_name: "Danfoss Ally — Room",
    room_card_description:
      "A Danfoss Ally room at a glance: climate, schedule, thermostats and actions.",
    current_temp: "Current {value}",
    setpoint_label: "Setpoint {value}",
    mode_label: "Mode {mode}",
    mode_at_home: "Comfort",
    mode_leaving_home: "Setback",
    mode_manual: "Manual",
    mode_pause: "Pause",
    mode_holiday: "Holiday",
    warmer: "Warmer",
    cooler: "Cooler",
    edit_schedule: "Edit schedule",
    setpoint_readonly: "Setpoint set from the schedule or the thermostat.",
    head_battery: "Battery {value}%",
    head_valve: "Valve {value}%",
    head_window_open: "Window open",
    head_low_battery: "Low battery",
    head_child_lock: "Child lock",
    head_fault: "Fault {code}",
    // Panneau (vue d'ensemble)
    panel_title: "Danfoss Ally — Building",
    overview_unavailable: "Fleet overview unavailable (the integration may not expose it yet).",
    fleet_rooms: "Rooms",
    fleet_heads: "Thermostats",
    fleet_gateways: "Gateways",
    fleet_offline: "Offline",
    fleet_low_battery: "Low battery",
    fleet_heating: "Calling for heat",
    fleet_faults: "Faults",
    fleet_relays_on: "Relays on",
    holiday_active: "Holiday",
    gateway_online: "{n} online",
    rooms_linked: "{n} linked rooms",
    relay_offline: "Offline",
    relay_on: "On",
    relay_off: "Off",
    room_offline_n: "{n} offline",
    room_low_battery_n: "{n} low battery",
    room_faults_n: "{n} faults",
    room_calling: "Calling for heat",
    room_window: "Window open",
    room_ok: "OK",
    room_single_head: "Single head, no group",
    room_named_after_head: "Room not found in the app: head's name",
    // --- Carte par zone, autres zones du panneau (§8.3) ---
    pick_area: "Area (any thermostat)",
    allow_foreign_writes: "Allow setpoint changes on thermostats of other integrations",
    allow_foreign_writes_hint:
      "Off by default: those thermostats are then read only. Administrators only, and never for a Danfoss Ally head seen through another integration.",
    pick_hint: "Pick a Danfoss Ally room, or a Home Assistant area to show every thermostat in it.",
    areas_unavailable: "No area holds a thermostat.",
    unknown_area: "Unknown area ({id})",
    area_ally_room: "Danfoss Ally room: {name}",
    area_climates: "Thermostats",
    area_other_climates: "Other thermostats in this area",
    area_no_climate: "No thermostat in this area.",
    area_ally_climate: "Danfoss Ally: set from its room card",
    climate_write_failed: "{name}: the setpoint could not be sent",
    head_heat_required: "Heat required",
    head_linkquality: "Link quality {value}",
    action_heating: "Heating",
    action_preheating: "Preheating",
    action_idle: "Idle",
    action_off: "Off",
    panel_other_areas: "Other thermostats by area",
    panel_other_areas_hint: "Climate entities of other integrations, grouped by Home Assistant area. Read only.",
    panel_show_other_areas: "Other areas",
    panel_no_other_areas: "No area holds a thermostat of another integration.",
    area_thermostats_n: "{n} thermostats",
    area_heating_n: "{n} heating",
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
    // --- Lot 5 : édition ---
    edit: "Modifier",
    cancel: "Annuler",
    save: "Enregistrer",
    saving: "Enregistrement…",
    discard: "Annuler les modifications",
    add_range: "Ajouter une plage",
    delete_range: "Supprimer cette plage",
    range_start: "Début",
    range_end: "Fin",
    transitions_count: "{n} / {max}",
    transitions_aria: "{day} : {n} transitions sur {max}",
    transitions_label: "transitions",
    midnight_note: "La tête abandonne la transition de minuit et garde, jusqu'à la première plage, la consigne de la veille au soir.",
    copy_day: "Copier vers…",
    copy_apply: "Copier",
    copy_cancel: "Fermer",
    copy_heading: "Copier {day} vers :",
    copy_select_all: "Tous les jours",
    no_changes: "Aucune modification à enregistrer.",
    save_blocked: "Corrigez les jours invalides avant d'enregistrer.",
    unsaved_hint: "Modifications non enregistrées — enregistrez ou annulez.",
    leave_confirm: "Abandonner les modifications non enregistrées du programme ?",
    beforeunload: "Des modifications du programme ne sont pas enregistrées.",
    // Erreurs (contrat §5.4)
    err_invalid_time: "Heure invalide",
    err_empty_or_reversed: "Plage vide ou inversée",
    err_overlap: "Plages qui se chevauchent",
    err_too_many_transitions: "Trop de transitions (max {max})",
    err_unknown_target: "Pièce inconnue",
    err_grouped_device: "Tête groupée : visez sa pièce",
    err_not_admin: "Vous n'êtes pas administrateur",
    err_cloud_refused: "Le cloud a refusé la modification",
    err_session_expired: "Session expirée, réessayez dans un instant",
    err_unknown: "La modification n'a pas pu être envoyée",
    // Suivi du lot
    job_heading: "Dernier envoi",
    job_status_sent: "Envoyé au cloud",
    job_status_applied: "Appliqué sur toutes les têtes",
    job_status_partial: "Appliqué sur une partie des têtes",
    job_status_unverified: "Envoyé (non vérifié)",
    job_status_failed: "Refusé par le cloud",
    head_job_pending: "En attente",
    head_job_applied: "Appliqué",
    head_job_mismatch: "Différent",
    head_job_unreachable: "Injoignable",
    head_job_unverified: "Non vérifié",
    // Retour au programme (R4)
    restore_schedule: "Revenir au programme",
    restore_hint: "Une tête ne suit plus son programme.",
    restore_done: "Retour au programme envoyé.",
    // --- Axe D : carte pièce + panneau ---
    room_card_name: "Danfoss Ally — Pièce",
    room_card_description:
      "Une pièce Danfoss Ally d'un coup d'œil : climat, programme, têtes et actions.",
    current_temp: "Actuel {value}",
    setpoint_label: "Consigne {value}",
    mode_label: "Mode {mode}",
    mode_at_home: "Confort",
    mode_leaving_home: "Réduit",
    mode_manual: "Manuel",
    mode_pause: "Pause",
    mode_holiday: "Vacances",
    warmer: "Plus chaud",
    cooler: "Plus froid",
    edit_schedule: "Modifier le programme",
    setpoint_readonly: "Consigne définie par le programme ou le thermostat.",
    head_battery: "Batterie {value} %",
    head_valve: "Vanne {value} %",
    head_window_open: "Fenêtre ouverte",
    head_low_battery: "Batterie faible",
    head_child_lock: "Verrouillage enfant",
    head_fault: "Défaut {code}",
    // Panneau (vue d'ensemble)
    panel_title: "Danfoss Ally — Bâtiment",
    overview_unavailable:
      "Vue d'ensemble indisponible (l'intégration ne l'expose peut-être pas encore).",
    fleet_rooms: "Pièces",
    fleet_heads: "Têtes",
    fleet_gateways: "Passerelles",
    fleet_offline: "Hors ligne",
    fleet_low_battery: "Batterie faible",
    fleet_heating: "En demande de chauffe",
    fleet_faults: "Défauts",
    fleet_relays_on: "Relais actifs",
    holiday_active: "Vacances",
    gateway_online: "{n} en ligne",
    rooms_linked: "{n} pièces liées",
    relay_offline: "Hors ligne",
    relay_on: "Marche",
    relay_off: "Arrêt",
    room_offline_n: "{n} hors ligne",
    room_low_battery_n: "{n} batterie faible",
    room_faults_n: "{n} défauts",
    room_calling: "Demande de chauffe",
    room_window: "Fenêtre ouverte",
    room_ok: "OK",
    room_single_head: "Tête seule, sans groupe",
    room_named_after_head: "Pièce de l'app non retrouvée : nom de la tête",
    // --- Carte par zone, autres zones du panneau (§8.3) ---
    pick_area: "Zone (tout thermostat)",
    allow_foreign_writes: "Autoriser le réglage de la consigne des thermostats d'autres intégrations",
    allow_foreign_writes_hint:
      "Désactivé par défaut : ces thermostats sont alors en lecture seule. Réservé aux administrateurs, et jamais pour une tête Danfoss Ally vue par une autre intégration.",
    pick_hint: "Choisissez une pièce Danfoss Ally, ou une zone Home Assistant pour en montrer tous les thermostats.",
    areas_unavailable: "Aucune zone ne contient de thermostat.",
    unknown_area: "Zone inconnue ({id})",
    area_ally_room: "Pièce Danfoss Ally : {name}",
    area_climates: "Thermostats",
    area_other_climates: "Autres thermostats de la zone",
    area_no_climate: "Aucun thermostat dans cette zone.",
    area_ally_climate: "Danfoss Ally : se règle depuis sa carte pièce",
    climate_write_failed: "{name} : la consigne n'a pas pu être envoyée",
    head_heat_required: "Demande de chauffe",
    head_linkquality: "Qualité du lien {value}",
    action_heating: "Chauffe",
    action_preheating: "Préchauffe",
    action_idle: "Au repos",
    action_off: "Arrêt",
    panel_other_areas: "Autres thermostats par zone",
    panel_other_areas_hint: "Entités climate des autres intégrations, regroupées par zone Home Assistant. Lecture seule.",
    panel_show_other_areas: "Autres zones",
    panel_no_other_areas: "Aucune zone ne contient de thermostat d'une autre intégration.",
    area_thermostats_n: "{n} thermostats",
    area_heating_n: "{n} en chauffe",
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

const MODE_KEYS: Record<string, StringKey> = {
  at_home: "mode_at_home",
  leaving_home: "mode_leaving_home",
  manual: "mode_manual",
  pause: "mode_pause",
  holiday: "mode_holiday",
  holiday_sat: "mode_holiday",
};

/** Libellé localisé d'un mode (DP 2). Un mode inconnu retombe sur sa valeur brute. */
export function modeLabel(hass: HassLike | undefined, mode: string | null | undefined): string {
  const key = mode ? MODE_KEYS[mode] : undefined;
  return key ? t(hass, key) : (mode ?? "—");
}

const ACTION_KEYS: Record<string, StringKey> = {
  heating: "action_heating",
  preheating: "action_preheating",
  idle: "action_idle",
  off: "action_off",
};

/** Libellé localisé d'un `hvac_action` ; une valeur inconnue retombe sur sa valeur brute. */
export function actionLabel(hass: HassLike | undefined, action: string): string {
  const key = ACTION_KEYS[action];
  return key ? t(hass, key) : action;
}

const ERROR_KEYS = new Set<StringKey>([
  "err_invalid_time",
  "err_empty_or_reversed",
  "err_overlap",
  "err_too_many_transitions",
  "err_unknown_target",
  "err_grouped_device",
  "err_not_admin",
  "err_cloud_refused",
  "err_session_expired",
  "err_unknown",
]);

/**
 * Texte traduit d'un code d'erreur du contrat (§5.4). Les codes inconnus
 * retombent sur `err_unknown`, pour ne jamais afficher un code brut.
 */
export function errorText(
  hass: HassLike | undefined,
  code: string,
  vars: Record<string, string | number> = {},
): string {
  const key = `err_${code}` as StringKey;
  return t(hass, ERROR_KEYS.has(key) ? key : "err_unknown", vars);
}
